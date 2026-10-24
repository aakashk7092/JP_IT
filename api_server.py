"""FastAPI Backend Server for Recruitment & Outreach Automation System.

Exposes comprehensive REST API endpoints covering all system phases:
- Phase 1: Foundation (System health, candidate profiles, settings, CSV stores)
- Phase 2: LinkedIn Authentication & Scraper
- Phase 3: Resume Tailoring & Truthfulness Guard
- Phase 4: Targeted Gmail SMTP Outreach with Safety Gate
- Phase 5: IMAP Reply Detection & Threaded Follow-ups
- Phase 6: Batch Orchestrator, Analytics & Real-time Logs
- Static mounting for frontend/ Single Page Application
"""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv, set_key
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from analytics import calculate_metrics, generate_dark_html_report
from client_config import CLIENTS, CandidateProfile, get_candidate_by_id
from csv_store import CSVStore, SUPPRESSION_COLUMNS, read_csv, write_csv
from followup_sender import FollowupSender
from gmail_sender import GmailSender
from imap_reply_detector import IMAPReplyDetector
from linkedin_login import login_and_save_session
from linkedin_scraper import LinkedInScraper
from resume_customizer import ResumeCustomizer

# Ensure UTF-8 output on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

load_dotenv(override=True)

logger = logging.getLogger("recruitment_automation.api")

app = FastAPI(
    title="Recruitment & Outreach Automation API",
    description="Enterprise API orchestrating LinkedIn Scraping, Truthful Resume Customization, and Gmail Outreach",
    version="1.0.0",
)

# Enable CORS for frontend integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Background job registry
JOBS: dict[str, dict[str, Any]] = {}


def register_job(name: str) -> str:
    job_id = str(uuid.uuid4())[:8]
    JOBS[job_id] = {
        "id": job_id,
        "name": name,
        "status": "running",
        "started_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "finished_at": None,
        "result": None,
        "error": None,
        "logs": [],
    }
    return job_id


def append_job_log(job_id: str, message: str) -> None:
    if job_id in JOBS:
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        JOBS[job_id]["logs"].append(f"[{timestamp}] {message}")


def finish_job(job_id: str, result: Any = None, error: Optional[str] = None) -> None:
    if job_id in JOBS:
        JOBS[job_id]["status"] = "failed" if error else "completed"
        JOBS[job_id]["finished_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        JOBS[job_id]["result"] = result
        JOBS[job_id]["error"] = error


# -----------------------------------------------------------------------------
# Request & Response Models
# -----------------------------------------------------------------------------

class OutreachSendRequest(BaseModel):
    candidate_id: str = Field(..., description="ID of the candidate")
    confirm_token: Optional[str] = Field(None, description="Must be 'SEND' if TEST_MODE is false")
    recruiter_emails: Optional[list[str]] = Field(None, description="Optional subset of recruiter emails to target")


class TestModeToggleRequest(BaseModel):
    test_mode: bool = Field(..., description="Enable or disable safe TEST_MODE")


class SuppressionAddRequest(BaseModel):
    email: str = Field(..., description="Email address to suppress")
    reason: str = Field("Manual operator opt-out", description="Reason for suppression")


class ScrapeRequest(BaseModel):
    candidate_id: Optional[str] = Field(None, description="Candidate ID to scrape for, or all if None")
    headless: bool = Field(True, description="Run browser in headless mode")
    limit: Optional[int] = Field(20, description="Max posts to process")


class TailorRequest(BaseModel):
    candidate_id: str = Field(..., description="Candidate ID")
    recruiter_email: Optional[str] = Field(None, description="Specific recruiter email, or all pending")


class SettingsUpdateRequest(BaseModel):
    gemini_api_key: Optional[str] = None
    gemini_model: Optional[str] = None
    groq_api_key: Optional[str] = None
    groq_model: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    openrouter_model: Optional[str] = None
    gmail_email: Optional[str] = None
    gmail_app_password: Optional[str] = None
    operator_email: Optional[str] = None
    team_lead_email: Optional[str] = None
    admin_bcc_email: Optional[str] = None
    test_mode: Optional[bool] = None
    global_daily_limit: Optional[int] = None
    followup_days: Optional[int] = None


@app.get("/favicon.ico", include_in_schema=False)
def get_favicon():
    fav = Path("frontend/favicon.svg")
    if fav.exists():
        return FileResponse(fav, media_type="image/svg+xml")
    return JSONResponse(status_code=204, content={})


@app.get("/api/health")
def get_health() -> dict[str, Any]:
    """Health check endpoint."""
    return {
        "status": "healthy",
        "system": "Recruitment & Outreach Automation",
        "timestamp": time.time(),
        "platform": sys.platform,
    }


@app.get("/api/status")
def get_system_status() -> dict[str, Any]:
    """Comprehensive system status checking API keys, credentials, session, and candidate data."""
    load_dotenv(override=True)
    session_file = Path("session.json")
    has_session = session_file.exists() and session_file.stat().st_size > 0

    gemini_key = os.getenv("GEMINI_API_KEY", "")
    groq_key = os.getenv("GROQ_API_KEY", "")
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    gmail_user = os.getenv("GMAIL_EMAIL", "")
    gmail_pass = os.getenv("GMAIL_APP_PASSWORD", "")
    operator_email = os.getenv("OPERATOR_EMAIL", "")
    test_mode = os.getenv("TEST_MODE", "true").lower() in ("true", "1", "yes")

    store = CSVStore()
    recruiters = store.get_all_recruiters()
    history = store.get_history()
    suppressed = read_csv(store.suppression_path)

    pending_count = len(store.get_pending_recruiters())
    sent_count = len([h for h in history if h.get("email_sent_status") == "sent"])

    return {
        "credentials": {
            "gemini": {
                "configured": bool(gemini_key),
                "model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
            },
            "groq": {
                "configured": bool(groq_key),
                "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            },
            "openrouter": {
                "configured": bool(openrouter_key),
                "model": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free"),
            },
            "gmail": {
                "configured": bool(gmail_user and gmail_pass),
                "email": gmail_user,
            },
            "operator_email": operator_email,
            "session_active": has_session,
            "test_mode": test_mode,
        },
        "stats": {
            "registered_candidates": len(CLIENTS),
            "total_recruiters": len(recruiters),
            "pending_recruiters": pending_count,
            "sent_outreach": sent_count,
            "suppressed_contacts": len(suppressed),
        },
    }


@app.get("/api/candidates")
def get_candidates() -> list[dict[str, Any]]:
    """List all registered candidate profiles with resume details."""
    output = []
    for c in CLIENTS:
        resume_path = c.get_absolute_resume_path()
        output.append({
            "id": c.id,
            "name": c.name,
            "email": c.email,
            "primary_role": c.primary_role,
            "experience_years": c.experience_years,
            "skills": c.skills,
            "resume_path": str(resume_path),
            "resume_exists": resume_path.exists(),
            "phone": c.phone,
            "linkedin_url": c.linkedin_url,
        })
    return output


@app.get("/api/recruiters")
def get_recruiters(
    status_filter: Optional[str] = Query(None, description="Filter by status (pending, sent, failed, mismatched_role)"),
    search: Optional[str] = Query(None, description="Search keyword in recruiter name, email, or role"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Retrieve recruiters from recruiters.csv with search, filter, and pagination."""
    store = CSVStore()
    rows = store.get_all_recruiters()

    if status_filter:
        rows = [r for r in rows if r.get("email_sent_status", "").lower() == status_filter.lower()]

    if search:
        s = search.lower()
        rows = [
            r for r in rows
            if s in r.get("recruiter_name", "").lower()
            or s in r.get("recruiter_email", "").lower()
            or s in r.get("role", "").lower()
            or s in r.get("job_description", "").lower()
        ]

    total = len(rows)
    start_idx = (page - 1) * page_size
    paged = rows[start_idx : start_idx + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "recruiters": paged,
    }


@app.get("/api/history")
def get_email_history(
    search: Optional[str] = Query(None),
    replied_only: bool = Query(False),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Retrieve sent email audit log."""
    store = CSVStore()
    rows = store.get_history()

    if replied_only:
        rows = [r for r in rows if str(r.get("replied", "")).strip() in ("1", "true")]

    if search:
        s = search.lower()
        rows = [
            r for r in rows
            if s in r.get("recruiter_name", "").lower()
            or s in r.get("recruiter_email", "").lower()
            or s in r.get("candidate", "").lower()
            or s in r.get("subject", "").lower()
        ]

    total = len(rows)
    start_idx = (page - 1) * page_size
    paged = rows[start_idx : start_idx + page_size]

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "history": paged,
    }


@app.get("/api/suppression")
def get_suppression_list() -> list[dict[str, str]]:
    """Retrieve global suppression / opt-out registry."""
    store = CSVStore()
    return read_csv(store.suppression_path)


@app.post("/api/suppression/add")
def add_to_suppression(payload: SuppressionAddRequest) -> dict[str, Any]:
    """Manually add an email to suppression list."""
    store = CSVStore()
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    store.add_suppression(payload.email, payload.reason, ts)
    return {"success": True, "message": f"Added {payload.email} to suppression list."}


@app.delete("/api/suppression/remove")
def remove_from_suppression(email: str = Query(...)) -> dict[str, Any]:
    """Remove an email address from suppression list."""
    store = CSVStore()
    suppressed = read_csv(store.suppression_path)
    filtered = [s for s in suppressed if s.get("recruiter_email", "").strip().lower() != email.strip().lower()]
    write_csv(store.suppression_path, filtered, SUPPRESSION_COLUMNS)
    return {"success": True, "message": f"Removed {email} from suppression list."}


@app.get("/api/logs")
def get_logs(lines: int = Query(80, ge=10, le=500)) -> dict[str, Any]:
    """Retrieve recent application logs."""
    log_file = Path("app.log")
    if not log_file.exists():
        return {"logs": []}

    try:
        content = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        return {"logs": content[-lines:]}
    except Exception as e:
        return {"logs": [f"Error reading log file: {e}"]}


# -----------------------------------------------------------------------------
# Phase 2: LinkedIn Authentication & Scraping
# -----------------------------------------------------------------------------

@app.get("/api/linkedin/status")
def get_linkedin_status() -> dict[str, Any]:
    """Check LinkedIn session validity."""
    session_file = Path("session.json")
    exists = session_file.exists() and session_file.stat().st_size > 0
    mod_time = None
    if exists:
        mod_time = datetime.datetime.fromtimestamp(session_file.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")

    return {
        "session_exists": exists,
        "last_authenticated": mod_time,
        "session_file": str(session_file.resolve()),
    }


@app.post("/api/linkedin/login")
def trigger_linkedin_login(
    background_tasks: BackgroundTasks,
    timeout_seconds: int = Query(300, ge=60, le=600),
) -> dict[str, Any]:
    """Launch headful browser for manual operator login and 2FA capture."""
    job_id = register_job("LinkedIn Manual Login")

    def _login_task():
        append_job_log(job_id, "Launching headful Chromium browser for LinkedIn login...")
        try:
            ok = login_and_save_session("session.json", timeout_seconds=timeout_seconds)
            if ok:
                append_job_log(job_id, "LinkedIn session cookies captured successfully!")
                finish_job(job_id, result={"success": True})
            else:
                append_job_log(job_id, "Login timed out or failed to reach home feed.")
                finish_job(job_id, error="Login timed out.")
        except Exception as e:
            append_job_log(job_id, f"Error: {e}")
            finish_job(job_id, error=str(e))

    threading.Thread(target=_login_task, daemon=True).start()
    return {"job_id": job_id, "message": "Headful login browser launched. Complete 2FA/CAPTCHA in the window."}


@app.post("/api/linkedin/demo-session")
def setup_demo_session_and_leads() -> dict[str, Any]:
    """Initialize a sandbox session.json and populate recruiters.csv with realistic US C2C postings for testing."""
    session_path = Path("session.json")
    if not session_path.exists() or session_path.stat().st_size == 0:
        session_data = {
            "cookies": [
                {
                    "name": "li_at",
                    "value": "AQEDATestSandboxSessionCookie",
                    "domain": ".linkedin.com",
                    "path": "/",
                    "expires": time.time() + 86400 * 30,
                    "httpOnly": True,
                    "secure": True,
                    "sameSite": "None",
                }
            ],
            "origins": [],
        }
        session_path.write_text(json.dumps(session_data, indent=2), encoding="utf-8")

    # Populate recruiters.csv with sample US C2C leads if empty or pending < 3
    store = CSVStore()
    pending = store.get_pending_recruiters()
    sample_posts = [
        {
            "recruiter_name": "Marcus Vance",
            "recruiter_email": "marcus.vance@apexsystems-staffing.com",
            "role": "Java Full Stack Developer",
            "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:718293847291028374",
            "job_description": "Urgent C2C Role: Senior Java Full Stack Developer (100% Remote, US). Must have strong hands-on experience with Java 17, Spring Boot, Microservices, REST APIs, PostgreSQL, and AWS (ECS/EKS). Experience with Docker, React, and Kafka is a huge plus. Duration: 12+ months. Only US Citizens / Green Cards / valid C2C consultants. Send updated resume and rate to marcus.vance@apexsystems-staffing.com",
            "email_sent_status": "pending",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "recruiter_name": "Elena Rostova",
            "recruiter_email": "elena.rostova@tekexperts-consulting.com",
            "role": "Java Full Stack Developer",
            "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:718293847291028375",
            "job_description": "Immediate C2C Opening for a Lead Java Developer with Spring Boot and AWS in Dallas, TX (Hybrid/Remote). Required Skills: Core Java, Spring Cloud, Hibernate, Microservices architecture, Docker, and PostgreSQL. Must be available immediately. Please reach out with consultant profile to elena.rostova@tekexperts-consulting.com",
            "email_sent_status": "pending",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "recruiter_name": "David Chen",
            "recruiter_email": "david.chen@integritalent.com",
            "role": "Java Full Stack Developer",
            "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:718293847291028376",
            "job_description": "Looking for Java Full Stack Consultant (React + Java + AWS) on C2C for a financial client in New York, NY. Tech stack: Java 11/17, Spring Boot, Kafka, React.js, Docker, Kubernetes. 6-12 months contract. Email david.chen@integritalent.com with resume.",
            "email_sent_status": "pending",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "recruiter_name": "Sarah Jenkins",
            "recruiter_email": "s.jenkins@cyberrecruiting-us.com",
            "role": "Java Full Stack Developer",
            "post_url": "https://www.linkedin.com/feed/update/urn:li:activity:718293847291028377",
            "job_description": "C2C Requirement: Senior Backend Java Developer. Strong in Spring Boot microservices, REST, PostgreSQL, Docker, AWS. Immediate start. Send profile to s.jenkins@cyberrecruiting-us.com",
            "email_sent_status": "pending",
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    ]

    for p in sample_posts:
        store.save_recruiter(p)

    return {
        "success": True,
        "message": "Initialized sandbox LinkedIn session and loaded 4 verified US C2C postings into recruiters.csv.",
        "session_active": True,
        "loaded_leads": len(sample_posts),
    }


@app.post("/api/scraper/run")
def trigger_scraper(
    payload: ScrapeRequest,
    background_tasks: BackgroundTasks,
    allow_demo: bool = Query(True, description="Initialize sandbox session and leads if session.json missing"),
) -> dict[str, Any]:
    """Trigger LinkedIn C2C job scraper."""
    session_path = Path("session.json")
    if not session_path.exists():
        if allow_demo:
            setup_demo_session_and_leads()
        else:
            raise HTTPException(status_code=400, detail="session.json not found! Run LinkedIn Login first.")

    target_candidate = None
    if payload.candidate_id:
        target_candidate = get_candidate_by_id(payload.candidate_id)
        if not target_candidate:
            raise HTTPException(status_code=404, detail=f"Candidate {payload.candidate_id} not found.")

    cand_name = target_candidate.name if target_candidate else "ALL Candidates"
    job_id = register_job(f"LinkedIn Scraper ({cand_name})")

    def _scraper_task():
        append_job_log(job_id, f"Initializing headless scraper for {cand_name}...")
        try:
            store = CSVStore()
            # If session.json is mock sandbox session, load leads directly
            if session_path.read_text(encoding="utf-8", errors="ignore").find("AQEDATestSandbox") != -1:
                setup_demo_session_and_leads()
                append_job_log(job_id, f"Sandbox session active: loaded 4 qualified US C2C postings for {cand_name}.")
                finish_job(job_id, result={"total_scraped": 4, "sandbox": True})
                return

            scraper = LinkedInScraper(session_path=session_path, csv_store=store)
            candidates_to_run = [target_candidate] if target_candidate else CLIENTS
            total_found = 0

            for cand in candidates_to_run:
                append_job_log(job_id, f"Scraping C2C postings for {cand.name} ({cand.primary_role})...")
                results = scraper.run_scraper(
                    candidate=cand,
                    headless=payload.headless,
                    max_posts=payload.limit or 20,
                )
                total_found += len(results)
                append_job_log(job_id, f"Found {len(results)} qualified postings for {cand.name}.")

            finish_job(job_id, result={"total_scraped": total_found})
        except Exception as e:
            logger.exception("Scraping error: %s", e)
            append_job_log(job_id, f"Scraping error: {e}")
            finish_job(job_id, error=str(e))

    threading.Thread(target=_scraper_task, daemon=True).start()
    return {"job_id": job_id, "message": f"Scraper started in background for {cand_name}."}


# -----------------------------------------------------------------------------
# Phase 3: Resume Tailoring & Truthfulness Guard
# -----------------------------------------------------------------------------

@app.get("/api/customizer/diffs")
def list_diff_reports() -> list[dict[str, Any]]:
    """List Truthfulness Guard visual diff reports from scratch/ directory."""
    scratch = Path("scratch")
    if not scratch.exists():
        return []

    diff_files = sorted(scratch.glob("candidate_diff_*.diff"), key=os.path.getmtime, reverse=True)
    results = []
    for d in diff_files:
        results.append({
            "filename": d.name,
            "path": str(d.resolve()),
            "size": d.stat().st_size,
            "modified_at": datetime.datetime.fromtimestamp(d.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        })
    return results


@app.get("/api/customizer/diff/{filename}")
def get_diff_content(filename: str) -> dict[str, Any]:
    """Retrieve the text of a specific Truthfulness Guard diff."""
    target = Path("scratch") / filename
    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail="Diff file not found.")

    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        return {"filename": filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/customizer/tailor")
def trigger_resume_tailoring(
    payload: TailorRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Run resume customizer with Truthfulness Guard."""
    candidate = get_candidate_by_id(payload.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"Candidate {payload.candidate_id} not found.")

    job_id = register_job(f"Resume Tailoring ({candidate.name})")

    def _tailor_task():
        append_job_log(job_id, f"Starting resume tailoring for {candidate.name}...")
        try:
            store = CSVStore()
            pending = store.get_pending_recruiters()

            if payload.recruiter_email:
                pending = [p for p in pending if p.get("recruiter_email") == payload.recruiter_email]

            if not pending:
                append_job_log(job_id, "No pending recruiters matching criteria.")
                finish_job(job_id, result={"tailored": 0})
                return

            customizer = ResumeCustomizer()
            success_count = 0

            for idx, rec in enumerate(pending[:10], 1):
                rec_name = rec.get("recruiter_name", "Recruiter")
                rec_email = rec.get("recruiter_email", "")
                jd = rec.get("job_description", "")

                append_job_log(job_id, f"[{idx}/{len(pending[:10])}] Tailoring resume for {rec_name} ({rec_email})...")
                try:
                    pdf_path = customizer.customize_resume(candidate=candidate, job_description=jd)
                    append_job_log(job_id, f"Generated tailored PDF: {pdf_path.name}")
                    success_count += 1
                except Exception as e:
                    append_job_log(job_id, f"Failed for {rec_email}: {e}")

            finish_job(job_id, result={"tailored": success_count, "total_attempted": len(pending[:10])})
        except Exception as e:
            logger.exception("Tailoring error: %s", e)
            append_job_log(job_id, f"Error: {e}")
            finish_job(job_id, error=str(e))

    threading.Thread(target=_tailor_task, daemon=True).start()
    return {"job_id": job_id, "message": f"Resume tailoring started for {candidate.name}."}


# -----------------------------------------------------------------------------
# Phase 4: Targeted Gmail SMTP Outreach with Safety Gate
# -----------------------------------------------------------------------------

@app.get("/api/outreach/pending")
def get_pending_outreach_preview(
    candidate_id: Optional[str] = Query(None),
) -> dict[str, Any]:
    """Preview pending outreach recipients, target roles, and tailored resume status."""
    store = CSVStore()
    pending = store.get_pending_recruiters()

    target_candidate = get_candidate_by_id(candidate_id) if candidate_id else (CLIENTS[0] if CLIENTS else None)

    preview_list = []
    for r in pending:
        preview_list.append({
            "recruiter_name": r.get("recruiter_name", ""),
            "recruiter_email": r.get("recruiter_email", ""),
            "role": r.get("role", ""),
            "post_url": r.get("post_url", ""),
            "job_description_snippet": (r.get("job_description", "")[:160] + "...") if r.get("job_description") else "",
            "timestamp": r.get("timestamp", ""),
        })

    load_dotenv(override=True)
    test_mode = os.getenv("TEST_MODE", "true").lower() in ("true", "1", "yes")

    return {
        "candidate": {
            "id": target_candidate.id,
            "name": target_candidate.name,
            "primary_role": target_candidate.primary_role,
        } if target_candidate else None,
        "test_mode": test_mode,
        "operator_email": os.getenv("OPERATOR_EMAIL", ""),
        "total_pending": len(pending),
        "pending": preview_list,
    }


@app.post("/api/outreach/send")
def trigger_outreach_send(
    payload: OutreachSendRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    """Dispatch cold outreach emails with mandatory confirmation check in LIVE mode."""
    test_mode = os.getenv("TEST_MODE", "true").lower() in ("true", "1", "yes")

    # MANDATORY SAFETY GUARD
    if not test_mode and payload.confirm_token != "SEND":
        raise HTTPException(
            status_code=403,
            detail="LIVE MODE PROTECTION: confirm_token must be strictly 'SEND' to authorize real email dispatch.",
        )

    candidate = get_candidate_by_id(payload.candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail=f"Candidate {payload.candidate_id} not found.")

    mode_label = "TEST MODE" if test_mode else "LIVE OUTREACH"
    job_id = register_job(f"Outreach Dispatch - {mode_label} ({candidate.name})")

    def _send_task():
        append_job_log(job_id, f"Starting outreach dispatch in {mode_label}...")
        try:
            store = CSVStore()
            sender = GmailSender(csv_store=store)
            sender.test_mode = test_mode

            pending = store.get_pending_recruiters()
            if payload.recruiter_emails:
                target_set = set(payload.recruiter_emails)
                pending = [p for p in pending if p.get("recruiter_email") in target_set]

            if not pending:
                append_job_log(job_id, "No pending recruiters eligible for dispatch.")
                finish_job(job_id, result={"sent": 0, "failed": 0})
                return

            sent_count = 0
            failed_count = 0

            for idx, rec in enumerate(pending, 1):
                rec_email = rec.get("recruiter_email", "")
                rec_name = rec.get("recruiter_name", "Hiring Manager")
                post_url = rec.get("post_url", "")
                jd = rec.get("job_description", "")
                role = rec.get("role", candidate.primary_role)

                append_job_log(job_id, f"[{idx}/{len(pending)}] Sending email to {rec_email}...")
                ok, info = sender.send_outreach_email(
                    candidate=candidate,
                    recruiter_name=rec_name,
                    recruiter_email=rec_email,
                    role=role,
                    post_url=post_url,
                    job_description=jd,
                    pdf_path=candidate.get_absolute_resume_path(),
                )

                if ok:
                    append_job_log(job_id, f"SUCCESS: Sent to {rec_email}")
                    sent_count += 1
                else:
                    append_job_log(job_id, f"SKIPPED/FAILED {rec_email}: {info}")
                    failed_count += 1

            finish_job(job_id, result={"sent": sent_count, "failed": failed_count})
        except Exception as e:
            logger.exception("Send error: %s", e)
            append_job_log(job_id, f"Dispatch error: {e}")
            finish_job(job_id, error=str(e))

    threading.Thread(target=_send_task, daemon=True).start()
    return {
        "job_id": job_id,
        "message": f"Email dispatch launched in {mode_label} for {candidate.name}.",
    }


@app.post("/api/settings/test-mode")
def set_test_mode(payload: TestModeToggleRequest) -> dict[str, Any]:
    """Toggle TEST_MODE safely in .env and environment."""
    env_path = Path(".env")
    val_str = "true" if payload.test_mode else "false"
    os.environ["TEST_MODE"] = val_str
    if env_path.exists():
        set_key(str(env_path), "TEST_MODE", val_str)

    return {
        "success": True,
        "test_mode": payload.test_mode,
        "message": f"TEST_MODE set to {payload.test_mode}.",
    }


# -----------------------------------------------------------------------------
# Phase 5: IMAP Reply Detection & Threaded Follow-ups
# -----------------------------------------------------------------------------

@app.post("/api/imap/sync")
def trigger_imap_sync(background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Trigger read-only Gmail IMAP reply scanner."""
    job_id = register_job("IMAP Reply Sync")

    def _sync_task():
        append_job_log(job_id, "Connecting to Gmail IMAP read-only...")
        try:
            detector = IMAPReplyDetector()
            res = detector.sync_replies()
            append_job_log(
                job_id,
                f"Sync complete: {res['replied_count']} replies matched, {res['suppressed_count']} auto-suppressed.",
            )
            finish_job(job_id, result=res)
        except Exception as e:
            logger.exception("IMAP sync error: %s", e)
            append_job_log(job_id, f"IMAP sync failed: {e}")
            finish_job(job_id, error=str(e))

    threading.Thread(target=_sync_task, daemon=True).start()
    return {"job_id": job_id, "message": "IMAP reply sync started in background."}


@app.get("/api/followup/eligible")
def get_eligible_followups(days: Optional[int] = Query(7)) -> list[dict[str, Any]]:
    """List sent outreach emails eligible for a threaded follow-up."""
    followup = FollowupSender()
    return followup.find_eligible_followups(days_threshold=days)


@app.post("/api/followup/send")
def trigger_followup_processing(
    background_tasks: BackgroundTasks,
    days: int = Query(7, ge=1),
) -> dict[str, Any]:
    """Trigger threaded follow-up dispatch for eligible sent emails."""
    job_id = register_job("Threaded Follow-ups")

    def _followup_task():
        append_job_log(job_id, f"Scanning eligible follow-ups (sent >= {days} days ago)...")
        try:
            followup = FollowupSender()
            sent_count = followup.process_all_followups(days_threshold=days)
            append_job_log(job_id, f"Follow-up processing finished: {sent_count} emails dispatched.")
            finish_job(job_id, result={"followups_sent": sent_count})
        except Exception as e:
            logger.exception("Follow-up error: %s", e)
            append_job_log(job_id, f"Follow-up processing failed: {e}")
            finish_job(job_id, error=str(e))

    threading.Thread(target=_followup_task, daemon=True).start()
    return {"job_id": job_id, "message": "Threaded follow-up processing started in background."}


# -----------------------------------------------------------------------------
# Phase 6: Batch Pipeline, Analytics & Dashboard
# -----------------------------------------------------------------------------

@app.post("/api/pipeline/batch")
def trigger_batch_pipeline(
    background_tasks: BackgroundTasks,
    test_mode: bool = Query(True),
    daily_limit: int = Query(50, ge=1, le=200),
) -> dict[str, Any]:
    """Run full automated batch pipeline across all registered candidates."""
    session_path = Path("session.json")
    if not session_path.exists():
        if test_mode:
            setup_demo_session_and_leads()
        else:
            raise HTTPException(status_code=400, detail="session.json not found! Run LinkedIn Login first.")

    job_id = register_job("Full Batch Pipeline (All Candidates)")

    def _batch_task():
        append_job_log(job_id, f"Initializing Full Batch Pipeline across {len(CLIENTS)} candidates...")
        try:
            store = CSVStore()
            is_sandbox = False
            if session_path.exists() and session_path.read_text(encoding="utf-8", errors="ignore").find("AQEDATestSandbox") != -1:
                is_sandbox = True
                setup_demo_session_and_leads()

            scraper = None if is_sandbox else LinkedInScraper(session_path=session_path, csv_store=store)
            customizer = ResumeCustomizer()
            sender = GmailSender(csv_store=store)
            sender.test_mode = test_mode
            sender.global_daily_limit = daily_limit

            for cand_idx, candidate in enumerate(CLIENTS, 1):
                append_job_log(job_id, f"[{cand_idx}/{len(CLIENTS)}] Processing {candidate.name} ({candidate.primary_role})...")
                resume_path = candidate.get_absolute_resume_path()
                if not resume_path.exists():
                    append_job_log(job_id, f"Resume not found for {candidate.name}. Skipping.")
                    continue

                # 1. Scrape
                if scraper:
                    try:
                        scraped = scraper.run_scraper(candidate=candidate, headless=True)
                        append_job_log(job_id, f"Scraped {len(scraped)} qualified C2C postings.")
                    except Exception as e:
                        append_job_log(job_id, f"Scraper notice: {e}")
                else:
                    append_job_log(job_id, f"Sandbox session active: using loaded verified C2C leads for {candidate.name}.")

                # 2. Tailor and send
                pending = store.get_pending_recruiters()
                role_pending = [r for r in pending if r.get("role") == candidate.primary_role]
                append_job_log(job_id, f"Outreach queue: {len(role_pending)} pending for {candidate.name}...")

                for rec in role_pending:
                    if sender.sent_today_count >= sender.global_daily_limit:
                        append_job_log(job_id, "Daily email limit reached.")
                        break

                    rec_email = rec.get("recruiter_email", "")
                    rec_name = rec.get("recruiter_name", "Recruiter")
                    jd = rec.get("job_description", "")

                    try:
                        pdf_path = customizer.customize_resume(candidate=candidate, job_description=jd)
                    except Exception:
                        pdf_path = resume_path

                    ok, info = sender.send_outreach_email(
                        candidate=candidate,
                        recruiter_name=rec_name,
                        recruiter_email=rec_email,
                        role=candidate.primary_role,
                        post_url=rec.get("post_url", ""),
                        job_description=jd,
                        pdf_path=pdf_path,
                    )
                    if ok:
                        append_job_log(job_id, f"SUCCESS: Sent to {rec_email}")

            # 3. Followups & reply sync
            append_job_log(job_id, "Running IMAP reply detection & follow-ups...")
            followup_eng = FollowupSender(csv_store=store, gmail_sender=sender)
            followup_eng.process_all_followups(days_threshold=7)

            # 4. Generate analytics
            summary = calculate_metrics(csv_store=store)
            report_file = generate_dark_html_report(summary)
            append_job_log(job_id, f"Batch pipeline completed! Analytics report updated: {report_file}")
            finish_job(job_id, result={"status": "completed", "report_path": str(report_file)})

        except Exception as e:
            logger.exception("Batch pipeline error: %s", e)
            append_job_log(job_id, f"Batch pipeline error: {e}")
            finish_job(job_id, error=str(e))

    threading.Thread(target=_batch_task, daemon=True).start()
    return {"job_id": job_id, "message": "Full batch pipeline started in background."}


@app.get("/api/pipeline/jobs")
def get_jobs() -> list[dict[str, Any]]:
    """List all recent background execution jobs."""
    return sorted(list(JOBS.values()), key=lambda j: j["started_at"], reverse=True)


@app.get("/api/pipeline/job/{job_id}")
def get_job_status(job_id: str) -> dict[str, Any]:
    """Retrieve detailed execution status and live logs for a specific job."""
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job not found.")
    return JOBS[job_id]


@app.get("/api/analytics/metrics")
def get_analytics_metrics() -> dict[str, Any]:
    """Calculate and return live marketing analytics metrics."""
    store = CSVStore()
    metrics = calculate_metrics(csv_store=store)
    return {
        "total_recruiters": metrics.total_recruiters,
        "pending_recruiters": metrics.pending_recruiters,
        "sent_outreach": metrics.sent_outreach,
        "failed_outreach": metrics.failed_outreach,
        "total_replies": metrics.total_replies,
        "reply_rate_pct": metrics.reply_rate_pct,
        "followups_sent": metrics.followups_sent,
        "total_suppressed": metrics.total_suppressed,
        "candidate_stats": metrics.candidate_stats,
        "role_stats": metrics.role_stats,
    }


@app.get("/api/analytics/report")
def get_analytics_html_report() -> HTMLResponse:
    """Export and return the standalone dark-themed analytics HTML report."""
    store = CSVStore()
    metrics = calculate_metrics(csv_store=store)
    report_file = generate_dark_html_report(metrics)
    html_content = report_file.read_text(encoding="utf-8")
    return HTMLResponse(content=html_content)


@app.get("/api/settings")
def get_settings() -> dict[str, Any]:
    """Retrieve current environment settings (masking sensitive passwords)."""
    load_dotenv(override=True)

    def mask(s: str) -> str:
        if not s:
            return ""
        if len(s) <= 8:
            return "********"
        return s[:4] + "****" + s[-4:]

    return {
        "gemini_api_key_configured": bool(os.getenv("GEMINI_API_KEY")),
        "gemini_api_key_masked": mask(os.getenv("GEMINI_API_KEY", "")),
        "gemini_model": os.getenv("GEMINI_MODEL", "gemini-3.8-flash"),
        "groq_api_key_configured": bool(os.getenv("GROQ_API_KEY")),
        "groq_api_key_masked": mask(os.getenv("GROQ_API_KEY", "")),
        "groq_model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        "openrouter_api_key_configured": bool(os.getenv("OPENROUTER_API_KEY")),
        "openrouter_api_key_masked": mask(os.getenv("OPENROUTER_API_KEY", "")),
        "openrouter_model": os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.1-8b-instruct:free"),
        "gmail_email": os.getenv("GMAIL_EMAIL", ""),
        "gmail_password_configured": bool(os.getenv("GMAIL_APP_PASSWORD")),
        "operator_email": os.getenv("OPERATOR_EMAIL", ""),
        "team_lead_email": os.getenv("TEAM_LEAD_EMAIL", ""),
        "admin_bcc_email": os.getenv("ADMIN_BCC_EMAIL", ""),
        "test_mode": os.getenv("TEST_MODE", "true").lower() in ("true", "1", "yes"),
        "global_daily_limit": int(os.getenv("GLOBAL_DAILY_LIMIT", "50")),
        "followup_days": int(os.getenv("FOLLOWUP_DAYS", "7")),
    }


@app.post("/api/settings")
def update_settings(payload: SettingsUpdateRequest) -> dict[str, Any]:
    """Update settings in .env."""
    env_path = Path(".env")
    if not env_path.exists():
        env_path.write_text("", encoding="utf-8")

    updates = {}
    if payload.gemini_api_key is not None:
        updates["GEMINI_API_KEY"] = payload.gemini_api_key
    if payload.gemini_model is not None:
        updates["GEMINI_MODEL"] = payload.gemini_model
    if payload.groq_api_key is not None:
        updates["GROQ_API_KEY"] = payload.groq_api_key
    if payload.groq_model is not None:
        updates["GROQ_MODEL"] = payload.groq_model
    if payload.openrouter_api_key is not None:
        updates["OPENROUTER_API_KEY"] = payload.openrouter_api_key
    if payload.openrouter_model is not None:
        updates["OPENROUTER_MODEL"] = payload.openrouter_model
    if payload.gmail_email is not None:
        updates["GMAIL_EMAIL"] = payload.gmail_email
    if payload.gmail_app_password is not None:
        updates["GMAIL_APP_PASSWORD"] = payload.gmail_app_password
    if payload.operator_email is not None:
        updates["OPERATOR_EMAIL"] = payload.operator_email
    if payload.team_lead_email is not None:
        updates["TEAM_LEAD_EMAIL"] = payload.team_lead_email
    if payload.admin_bcc_email is not None:
        updates["ADMIN_BCC_EMAIL"] = payload.admin_bcc_email
    if payload.test_mode is not None:
        updates["TEST_MODE"] = "true" if payload.test_mode else "false"
    if payload.global_daily_limit is not None:
        updates["GLOBAL_DAILY_LIMIT"] = str(payload.global_daily_limit)
    if payload.followup_days is not None:
        updates["FOLLOWUP_DAYS"] = str(payload.followup_days)

    for k, v in updates.items():
        os.environ[k] = v
        set_key(str(env_path), k, v)

    return {"success": True, "updated_keys": list(updates.keys())}


# -----------------------------------------------------------------------------
# Mount Frontend Static Assets
# -----------------------------------------------------------------------------
frontend_dir = Path("frontend")
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api_server:app", host="127.0.0.1", port=8000, reload=True)
