"""LinkedIn manual login and session persistence module.

Launches a headful Playwright browser for the operator to solve any
2FA / CAPTCHA challenges, verifies successful navigation to the feed,
and serializes cookies and localStorage state to session.json.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from rich.console import Console

logger = logging.getLogger("recruitment_automation.linkedin_login")
console = Console()

# Centralized UI Selectors for LinkedIn Login
LOGIN_SELECTORS: dict[str, str] = {
    "login_url": "https://www.linkedin.com/login",
    "feed_url_part": "/feed",
    "global_nav": "#global-nav, .global-nav__me, nav[aria-label='Primary'], .feed-identity-module",
    "captcha_indicator": "iframe[title*='challenge'], div.checkpoint-challenge, #captcha-internal",
}


def login_and_save_session(
    session_path: str | Path = "session.json",
    timeout_seconds: int = 300,
) -> bool:
    """Launch headful browser for manual operator login and export session.json.

    Args:
        session_path: Destination path for serialized Playwright storage state.
        timeout_seconds: Maximum time to wait for operator login and feed detection.

    Returns:
        bool: True if session state was successfully saved.
    """
    load_dotenv()
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError:
        logger.error("Playwright is not installed. Please run: pip install playwright && playwright install chromium")
        console.print("[bold red]Error: Playwright not installed. Run 'pip install playwright'[/bold red]")
        return False

    out_path = Path(session_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    console.print("\n[bold cyan]=== LinkedIn Session Login ===[/bold cyan]")
    console.print(f"Target session file: [yellow]{out_path}[/yellow]")
    console.print("Launching headful browser. Please solve any 2FA/CAPTCHA in the opened window...\n")

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(
                headless=False,
                args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = context.new_page()

            page.goto(LOGIN_SELECTORS["login_url"], wait_until="domcontentloaded")
            console.print("[dim]Navigated to login page. Waiting for operator authentication...[/dim]")

            # Wait until user reaches feed or global nav element appears
            try:
                page.wait_for_selector(
                    LOGIN_SELECTORS["global_nav"],
                    timeout=timeout_seconds * 1000,
                )
            except PlaywrightTimeoutError:
                # Also check if URL indicates we are on feed
                if LOGIN_SELECTORS["feed_url_part"] in page.url:
                    logger.info("Feed URL detected despite nav selector timeout.")
                else:
                    console.print("[bold red]Login timed out before reaching feed.[/bold red]")
                    logger.error("Timed out waiting for LinkedIn login completion after %ds", timeout_seconds)
                    browser.close()
                    return False

            # Wait a moment for cookies to settle
            page.wait_for_timeout(3000)

            # Save state
            context.storage_state(path=str(out_path))
            browser.close()

            console.print(f"[bold green][SUCCESS] Session successfully captured and saved to: {out_path}[/bold green]\n")
            logger.info("Successfully exported LinkedIn session to %s", out_path)
            return True

        except Exception as e:
            console.print(f"[bold red]Failed to capture LinkedIn session: {e}[/bold red]")
            logger.exception("Unexpected error during LinkedIn session capture: %s", e)
            return False


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Authenticate and save LinkedIn session.")
    parser.add_argument("--session", default="session.json", help="Path to save session.json")
    parser.add_argument("--timeout", type=int, default=300, help="Timeout in seconds")
    args = parser.parse_args()

    success = login_and_save_session(session_path=args.session, timeout_seconds=args.timeout)
    sys.exit(0 if success else 1)
