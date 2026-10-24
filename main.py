"""Main orchestrator and Rich CLI interactive interface for Recruitment & Outreach Automation System.

Provides setup validation, manual LinkedIn session capture, selective phase execution,
safety-guarded live email dispatch requiring confirmation ("SEND"), batch execution
for all candidates (Option 8), and dark-themed analytics export.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.table import Table

from analytics import calculate_metrics, generate_dark_html_report
from client_config import CLIENTS, CandidateProfile, get_candidate_by_id
from csv_store import CSVStore
from followup_sender import FollowupSender
from gmail_sender import GmailSender
from imap_reply_detector import IMAPReplyDetector
from linkedin_login import login_and_save_session
from linkedin_scraper import LinkedInScraper
from resume_customizer import ResumeCustomizer

# Ensure Windows console handles UTF-8 cleanly
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

console = Console()
logger = logging.getLogger("recruitment_automation.main")


def setup_logging(
    log_file: str | Path = "app.log",
    level: int = logging.INFO,
) -> logging.Logger:
    """Configure dual logging: formatted file output and rich console output."""
    log_path = Path(log_file).resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=True,
    )
    rich_handler.setLevel(level)
    root_logger.addHandler(rich_handler)

    file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
    file_handler.setLevel(level)
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s:%(lineno)d] %(message)s"
    )
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    return logging.getLogger("recruitment_automation")


def check_setup_status(load_env: bool = True) -> dict[str, Any]:
    """Inspect environment variables, credentials, file paths, and candidate profiles."""
    if load_env:
        load_dotenv()
    session_file = Path("session.json")
    has_session = session_file.exists() and session_file.stat().st_size > 0

    results = {
        "gemini_api_key": bool(os.getenv("GEMINI_API_KEY")),
        "groq_api_key": bool(os.getenv("GROQ_API_KEY")),
        "openrouter_api_key": bool(os.getenv("OPENROUTER_API_KEY")),
        "gmail_configured": bool(os.getenv("GMAIL_EMAIL") and os.getenv("GMAIL_APP_PASSWORD")),
        "operator_email": os.getenv("OPERATOR_EMAIL", ""),
        "test_mode": os.getenv("TEST_MODE", "true").lower() in ("true", "1", "yes"),
        "session_active": has_session,
        "candidates_count": len(CLIENTS),
    }
    return results


def display_setup_validation() -> None:
    """Render a Rich table showing system readiness and configuration status."""
    status = check_setup_status()

    table = Table(title="System Setup & Configuration Status", border_style="cyan")
    table.add_column("Component", style="bold")
    table.add_column("Status", justify="center")
    table.add_column("Details", style="dim")

    def icon(val: bool) -> str:
        return "[bold green][OK] READY[/bold green]" if val else "[bold red][X] MISSING[/bold red]"

    table.add_row("Google Gemini API", icon(status["gemini_api_key"]), "Primary LLM for tailoring")
    table.add_row("Groq API", icon(status["groq_api_key"]), "Secondary LLM fallback")
    table.add_row("OpenRouter API", "[dim]Optional[/dim]" if not status["openrouter_api_key"] else icon(True), "Optional LLM fallback (not required)")
    table.add_row("Gmail Credentials", icon(status["gmail_configured"]), "SMTP and IMAP sync")
    table.add_row(
        "LinkedIn Session",
        icon(status["session_active"]),
        "session.json storage state" if status["session_active"] else "Run Option 2 to authenticate",
    )
    mode_text = "[bold yellow]TEST MODE (Safe)[/bold yellow]" if status["test_mode"] else "[bold red]LIVE OUTREACH[/bold red]"
    table.add_row("Outreach Operating Mode", mode_text, f"Operator: {status['operator_email']}")
    table.add_row("Registered Candidates", f"[bold green]{status['candidates_count']}[/bold green]", "Loaded from client_config.py")

    console.print(table)


def run_linkedin_login_flow() -> None:
    """Option 2: Guide operator through headful LinkedIn authentication."""
    console.print("\n[bold cyan]Starting LinkedIn Session Login...[/bold cyan]")
    timeout = IntPrompt.ask("Enter timeout in seconds for operator login", default=300)
    success = login_and_save_session(session_path="session.json", timeout_seconds=timeout)
    if success:
        console.print("[bold green]LinkedIn session successfully saved! Headless scraper is now ready.[/bold green]")
    else:
        console.print("[bold red]Failed to capture LinkedIn session. Please try again.[/bold red]")


def select_candidate() -> Optional[CandidateProfile]:
    """Prompt operator to select a registered candidate."""
    if not CLIENTS:
        console.print("[bold red]No candidates registered in client_config.py![/bold red]")
        return None

    table = Table(title="Registered Candidates", border_style="blue")
    table.add_column("No.", style="cyan", justify="center")
    table.add_column("Candidate ID", style="bold")
    table.add_column("Name")
    table.add_column("Primary Role")

    for idx, c in enumerate(CLIENTS, 1):
        table.add_row(str(idx), c.id, c.name, c.primary_role)

    console.print(table)
    choice = IntPrompt.ask("Select candidate number", default=1)
    if 1 <= choice <= len(CLIENTS):
        return CLIENTS[choice - 1]
    console.print("[bold red]Invalid selection.[/bold red]")
    return None


def run_scrape_flow(candidate: Optional[CandidateProfile] = None) -> None:
    """Option 3: Scrape LinkedIn C2C postings."""
    target_candidate = candidate or select_candidate()
    if not target_candidate:
        return

    session_path = Path("session.json")
    if not session_path.exists():
        console.print("[bold red]Error: session.json not found! Please run Option 2 first.[/bold red]")
        return

    console.print(f"[cyan]Scraping LinkedIn for candidate: [bold]{target_candidate.name}[/bold] ({target_candidate.primary_role})...[/cyan]")
    scraper = LinkedInScraper(session_path=session_path)
    try:
        results = scraper.run_scraper(candidate=target_candidate, headless=True)
        console.print(f"[bold green]Scraping complete. Found {len(results)} qualified postings.[/bold green]")
    except Exception as e:
        console.print(f"[bold red]Scraping failed: {e}[/bold red]")


def run_resume_customization_flow() -> None:
    """Option 4: Tailor resumes for pending recruiters."""
    store = CSVStore()
    pending = store.get_pending_recruiters()

    if not pending:
        console.print("[yellow]No pending recruiters found in recruiters.csv.[/yellow]")
        return

    candidate = select_candidate()
    if not candidate:
        return

    console.print(f"[cyan]Found {len(pending)} pending posts. Tailoring resumes for [bold]{candidate.name}[/bold]...[/cyan]")
    customizer = ResumeCustomizer()

    tailored_count = 0
    for idx, rec in enumerate(pending[:5], 1):
        jd = rec.get("job_description", "")
        rec_name = rec.get("recruiter_name", "Recruiter")
        console.print(f"[{idx}/{min(len(pending), 5)}] Tailoring for {rec_name}...")
        try:
            pdf_path = customizer.customize_resume(candidate=candidate, job_description=jd)
            console.print(f"[green][SUCCESS] Generated tailored resume: {pdf_path.name}[/green]")
            tailored_count += 1
        except Exception as e:
            console.print(f"[red][FAILED] Failed tailoring: {e}[/red]")

    console.print(f"[bold green]Tailoring finished for {tailored_count} posts.[/bold green]")


def run_send_outreach_flow() -> None:
    """Option 5: Send outreach emails with mandatory confirmation safety check."""
    store = CSVStore()
    pending = store.get_pending_recruiters()

    if not pending:
        console.print("[yellow]No pending recruiters to contact.[/yellow]")
        return

    candidate = select_candidate()
    if not candidate:
        return

    load_dotenv()
    test_mode = os.getenv("TEST_MODE", "true").lower() in ("true", "1", "yes")

    # Display preview table
    table = Table(title="Pending Outreach Preview", border_style="yellow")
    table.add_column("Recruiter Name", style="bold")
    table.add_column("Email", style="cyan")
    table.add_column("Role", style="green")
    table.add_column("Post URL", style="dim", overflow="ellipsis")

    for r in pending[:10]:
        table.add_row(
            r.get("recruiter_name", ""),
            r.get("recruiter_email", ""),
            r.get("role", ""),
            r.get("post_url", ""),
        )

    console.print(table)
    console.print(f"\nTotal Pending: [bold cyan]{len(pending)}[/bold cyan]")
    console.print(f"Operating Mode: [bold {'yellow' if test_mode else 'red'}]{'TEST MODE' if test_mode else 'LIVE OUTREACH'}[/bold]")

    # Check for latest diff report
    scratch_diffs = sorted(Path("scratch").glob("candidate_diff_*.diff"), key=os.path.getmtime, reverse=True)
    if scratch_diffs:
        console.print(f"[dim]Latest Truthfulness diff report: {scratch_diffs[0]}[/dim]")

    # MANDATORY CONFIRMATION GUARD
    if not test_mode:
        console.print("[bold red]WARNING: You are in LIVE OUTREACH mode. Real emails will be dispatched to recruiters.[/bold red]")
        confirmation = Prompt.ask("[bold red]Type 'SEND' to confirm live email dispatch[/bold red]")
        if confirmation.strip() != "SEND":
            console.print("[yellow]Dispatch cancelled by operator.[/yellow]")
            return
    else:
        if not Confirm.ask("Proceed with sending in TEST MODE? (Emails sent safely to operator)", default=True):
            console.print("[yellow]Cancelled.[/yellow]")
            return

    # Execute sends
    sender = GmailSender(csv_store=store)
    sent_count = 0
    failed_count = 0

    for rec in pending:
        success, info = sender.send_outreach_email(
            candidate=candidate,
            recruiter_name=rec.get("recruiter_name", "Hiring Manager"),
            recruiter_email=rec.get("recruiter_email", ""),
            role=rec.get("role", candidate.primary_role),
            post_url=rec.get("post_url", ""),
            job_description=rec.get("job_description", ""),
            pdf_path=candidate.get_absolute_resume_path(),
        )
        if success:
            console.print(f"[green][SUCCESS] Sent email to {rec.get('recruiter_email')}[/green]")
            sent_count += 1
        else:
            console.print(f"[yellow][SKIPPED/FAILED] {rec.get('recruiter_email')}: {info}[/yellow]")
            failed_count += 1

    console.print(f"\n[bold green]Outreach completed: {sent_count} sent, {failed_count} failed/skipped.[/bold green]")


def run_full_pipeline_all_candidates() -> None:
    """Option 8: Run Full Pipeline for ALL Registered Candidates (Batch Mode)."""
    console.print(Panel("[bold cyan]=== Run Full Pipeline for ALL Candidates (Batch Mode) ===[/bold cyan]"))

    load_dotenv()
    # 1. Ask Test/Live mode and global limit
    is_test = Confirm.ask("Run in safe TEST MODE? (Emails directed to operator)", default=True)
    os.environ["TEST_MODE"] = "true" if is_test else "false"

    daily_limit = IntPrompt.ask("Enter global daily email limit", default=50)
    os.environ["GLOBAL_DAILY_LIMIT"] = str(daily_limit)

    # 2. Check LinkedIn session
    session_path = Path("session.json")
    if not session_path.exists():
        console.print("[bold red]session.json not found! Please run Option 2 to authenticate LinkedIn first.[/bold red]")
        return

    # 3. Setup modules
    store = CSVStore()
    scraper = LinkedInScraper(session_path=session_path, csv_store=store)
    customizer = ResumeCustomizer()
    sender = GmailSender(csv_store=store)
    sender.test_mode = is_test
    sender.global_daily_limit = daily_limit

    # 4. Mandatory confirmation if LIVE
    if not is_test:
        console.print("[bold red]LIVE MODE SELECTED: Emails will be dispatched to real recruiters.[/bold red]")
        confirm = Prompt.ask("[bold red]Type 'SEND' to authorize full batch pipeline[/bold red]")
        if confirm.strip() != "SEND":
            console.print("[yellow]Batch execution aborted by operator.[/yellow]")
            return

    console.print(f"[green]Starting batch run across {len(CLIENTS)} registered candidates...[/green]\n")

    for cand_idx, candidate in enumerate(CLIENTS, 1):
        console.print(Panel(f"Processing [{cand_idx}/{len(CLIENTS)}] [bold]{candidate.name}[/bold] - {candidate.primary_role}"))

        # Verify candidate resume
        resume_path = candidate.get_absolute_resume_path()
        if not resume_path.exists():
            console.print(f"[bold red]Resume not found for {candidate.name}: {resume_path}. Skipping.[/bold red]")
            continue

        # Scrape
        console.print("[cyan]Step 1: Scraping fresh LinkedIn C2C postings...[/cyan]")
        try:
            scraped = scraper.run_scraper(candidate=candidate, headless=True)
            console.print(f"[green]Scraped {len(scraped)} qualified postings.[/green]")
        except Exception as e:
            console.print(f"[red]Scraping encountered error: {e}[/red]")

        # Fetch pending recruiters for this role
        pending = store.get_pending_recruiters()
        role_pending = [r for r in pending if r.get("role") == candidate.primary_role]
        console.print(f"[cyan]Step 2: Tailoring resumes and dispatching outreach ({len(role_pending)} pending)...[/cyan]")

        for rec in role_pending:
            if sender.sent_today_count >= sender.global_daily_limit:
                console.print("[yellow]Global daily limit reached. Stopping outreach.[/yellow]")
                break

            rec_email = rec.get("recruiter_email", "")
            rec_name = rec.get("recruiter_name", "Recruiter")
            post_url = rec.get("post_url", "")
            jd = rec.get("job_description", "")

            # Tailor resume
            try:
                pdf_path = customizer.customize_resume(candidate=candidate, job_description=jd)
            except Exception as e:
                logger.error("Tailoring error for %s: %s", rec_email, e)
                pdf_path = resume_path

            # Send email
            ok, info = sender.send_outreach_email(
                candidate=candidate,
                recruiter_name=rec_name,
                recruiter_email=rec_email,
                role=candidate.primary_role,
                post_url=post_url,
                job_description=jd,
                pdf_path=pdf_path,
            )
            if ok:
                console.print(f"[green][SUCCESS] Dispatched to {rec_email}[/green]")
            else:
                console.print(f"[yellow][SKIPPED] {rec_email} ({info})[/yellow]")

    # Run reply sync & follow-ups
    console.print("\n[cyan]Step 3: Running IMAP reply sync and checking follow-ups...[/cyan]")
    followup_orchestrator = FollowupSender(csv_store=store, gmail_sender=sender)
    followup_orchestrator.process_all_followups(days_threshold=7)

    # Generate analytics report
    summary = calculate_metrics(csv_store=store)
    report_file = generate_dark_html_report(summary)
    console.print(f"[bold green][SUCCESS] Full batch pipeline completed! Analytics report updated: {report_file}[/bold green]")


def run_analytics_flow() -> None:
    """Option 9: Calculate outreach metrics and export dark HTML report."""
    store = CSVStore()
    summary = calculate_metrics(csv_store=store)
    report_path = generate_dark_html_report(summary)

    table = Table(title="Live Outreach Statistics", border_style="cyan")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="center")

    table.add_row("Total Scraped Recruiters", str(summary.total_recruiters))
    table.add_row("Pending Outreach", str(summary.pending_recruiters))
    table.add_row("Outreach Sent", str(summary.sent_outreach))
    table.add_row("Replies Received", str(summary.total_replies))
    table.add_row("Reply Rate", f"{summary.reply_rate_pct}%")
    table.add_row("Threaded Follow-ups Sent", str(summary.followups_sent))
    table.add_row("Suppressed / Opt-out", str(summary.total_suppressed))

    console.print(table)
    console.print(f"\n[bold green][SUCCESS] Standalone Dark HTML Dashboard saved to: [underline]{report_path}[/underline][/bold green]")


def display_menu() -> str:
    """Render interactive main menu and return selected choice."""
    console.print()
    menu_table = Table(
        title="Recruitment & Outreach Automation System",
        subtitle="Version 1.0 • Enterprise Edition",
        border_style="bright_blue",
    )
    menu_table.add_column("Option", style="bold cyan", justify="center", width=8)
    menu_table.add_column("Workflow Action", style="bold")
    menu_table.add_column("Description", style="dim")

    menu_table.add_row("1", "Setup & Environment Validation", "Inspect API keys, session, and candidates")
    menu_table.add_row("2", "Setup/Test LinkedIn Session", "Manual headful 2FA/CAPTCHA login -> session.json")
    menu_table.add_row("3", "Scrape LinkedIn C2C Jobs", "Query C2C posts, filter spam & USA geo")
    menu_table.add_row("4", "Tailor Resumes for Pending Jobs", "Run LLM customizer with Truthfulness Guard")
    menu_table.add_row("5", "Send Outreach Emails", "SMTP dispatch with safety confirmation ('SEND')")
    menu_table.add_row("6", "Sync IMAP Recruiter Replies", "Scan Gmail INBOX read-only & auto-suppress STOP")
    menu_table.add_row("7", "Process Threaded Follow-ups", "Send In-Reply-To 7-day follow-ups with AI hook")
    menu_table.add_row("8", "Run Full Pipeline for ALL Candidates", "End-to-End automated batch pipeline")
    menu_table.add_row("9", "Export Analytics Dashboard", "Generate premium dark HTML report")
    menu_table.add_row("0", "Exit", "Exit application cleanly")

    console.print(menu_table)
    return Prompt.ask("[bold green]Select an option[/bold green]", choices=["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"], default="1")


def main() -> int:
    """Interactive CLI execution entrypoint."""
    setup_logging()
    load_dotenv()

    console.print(Panel.fit(
        "[bold cyan]Recruitment & Outreach Automation System[/bold cyan]\n"
        "[dim]Automated LinkedIn Scraping, Truthful Resume Tailoring & Gmail Outreach[/dim]",
        border_style="cyan",
    ))

    while True:
        try:
            choice = display_menu()
            if choice == "0":
                console.print("[green]Exiting system. Goodbye![/green]")
                break
            elif choice == "1":
                display_setup_validation()
            elif choice == "2":
                run_linkedin_login_flow()
            elif choice == "3":
                run_scrape_flow()
            elif choice == "4":
                run_resume_customization_flow()
            elif choice == "5":
                run_send_outreach_flow()
            elif choice == "6":
                detector = IMAPReplyDetector()
                res = detector.sync_replies()
                console.print(f"[bold green]Reply sync complete: {res['replied_count']} replies matched, {res['suppressed_count']} added to suppression.[/bold green]")
            elif choice == "7":
                followup = FollowupSender()
                sent = followup.process_all_followups()
                console.print(f"[bold green]Processed follow-ups: {sent} dispatched.[/bold green]")
            elif choice == "8":
                run_full_pipeline_all_candidates()
            elif choice == "9":
                run_analytics_flow()
        except KeyboardInterrupt:
            console.print("\n[yellow]Operation cancelled by operator. Returning to main menu...[/yellow]")
        except Exception as e:
            logger.exception("Error during option execution: %s", e)
            console.print(f"[bold red]Unexpected error: {e}[/bold red]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
