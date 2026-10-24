"""LinkedIn post scraper for USA C2C recruitment posts.

Runs headless using stored session cookies, executes boolean search queries,
expands post text, extracts recruiter emails, filters non-USA / bench spam,
validates domain alignment, and saves pending recruiters to CSV.
"""

from __future__ import annotations

import logging
import random
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from bs4 import BeautifulSoup

from client_config import (
    BENCH_MARKETING_PHRASES,
    CandidateProfile,
    NON_USA_INDICATORS,
    RoleDefinition,
    USA_GEO_INDICATORS,
    get_role_definition,
)
from csv_store import CSVStore

logger = logging.getLogger("recruitment_automation.linkedin_scraper")

# Centralized Selector Dictionary for LinkedIn DOM Elements
# Modifying any selector here automatically updates scraper behavior throughout the app.
SELECTORS: dict[str, str] = {
    # Post containers
    "post_card": "div.feed-shared-update-v2, div[data-urn*='urn:li:activity']",
    "post_text_container": (
        ".feed-shared-update-v2__description, .update-components-text, "
        ".feed-shared-inline-show-more-text, .feed-shared-text"
    ),
    "see_more_button": (
        "button.feed-shared-inline-show-more-text__see-more-less-toggle, "
        "button[aria-label*='see more' i], .feed-shared-see-more"
    ),
    # Author details
    "author_name": (
        ".update-components-actor__name, .feed-shared-actor__name, "
        ".update-components-actor__single-line-truncate, span[dir='ltr']"
    ),
    "author_title": (
        ".update-components-actor__description, .feed-shared-actor__description, "
        ".update-components-actor__sub-description"
    ),
    # Post control menu / permalink
    "control_menu_button": (
        "button[aria-label*='control menu for post' i], "
        "button[aria-label*='open control menu' i], "
        "button.feed-shared-control-menu__trigger"
    ),
    "copy_link_option": (
        "div.feed-shared-control-menu__item:has-text('Copy link'), "
        "div[role='button']:has-text('Copy link'), "
        "li:has-text('Copy link')"
    ),
    "post_anchor_fallback": "a[href*='/posts/'], a[href*='/feed/update/urn:li:activity:']",
    "global_nav": "#global-nav, .global-nav__me, nav[aria-label='Primary']",
}

# Regex for detecting email addresses
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")

# Ignored false positive email extensions or domains
IGNORED_EMAIL_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", "example.com"}


@dataclass
class ScrapedPost:
    """Represents an extracted LinkedIn hiring post."""
    recruiter_name: str
    recruiter_email: str
    role: str
    post_url: str
    job_description: str
    email_sent_status: str  # pending | mismatched_role
    timestamp: str


def clean_post_url(raw_url: str) -> str:
    """Strip tracking and session query parameters from LinkedIn post URLs.

    Args:
        raw_url: Raw URL copied from clipboard or anchor.

    Returns:
        Clean canonical URL.
    """
    if not raw_url:
        return ""
    parsed = urllib.parse.urlparse(raw_url)
    clean = urllib.parse.urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return clean.rstrip("/")


def extract_emails_from_text(text: str) -> list[str]:
    """Extract and validate email addresses from plain text using regex.

    Filters out binary file extensions and placeholder domains.
    """
    if not text:
        return []
    matches = EMAIL_REGEX.findall(text)
    valid_emails: list[str] = []
    seen: set[str] = set()

    for m in matches:
        email = m.strip().lower()
        # Filter out accidental regex matches against file names like 'image@2x.png'
        if any(email.endswith(suffix) for suffix in IGNORED_EMAIL_SUFFIXES):
            continue
        if email not in seen:
            seen.add(email)
            valid_emails.append(email)
    return valid_emails


def extract_mailto_emails(html_snippet: str) -> list[str]:
    """Extract target email addresses from anchor mailto links."""
    if not html_snippet:
        return []
    soup = BeautifulSoup(html_snippet, "html.parser")
    emails: list[str] = []
    seen: set[str] = set()

    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if href.lower().startswith("mailto:"):
            raw_email = href[7:].split("?")[0].strip().lower()
            if raw_email and raw_email not in seen and "@" in raw_email:
                seen.add(raw_email)
                emails.append(raw_email)
    return emails


def extract_all_emails(text: str, html_snippet: str = "") -> list[str]:
    """Combine mailto links first (primary), then regex findings without duplicates."""
    mailto_list = extract_mailto_emails(html_snippet)
    regex_list = extract_emails_from_text(text)

    combined: list[str] = []
    seen: set[str] = set()
    for e in mailto_list + regex_list:
        if e not in seen:
            seen.add(e)
            combined.append(e)
    return combined


def is_usa_job(text: str) -> bool:
    """Check if the job posting is strictly located within the USA.

    Rejects postings with NON_USA_INDICATORS (India, Canada, etc.)
    and confirms presence of USA_GEO_INDICATORS or remote US indicators.
    """
    lowered = text.lower()

    # Reject non-USA locations
    for non_usa in NON_USA_INDICATORS:
        pattern = rf"\b{re.escape(non_usa)}\b"
        if re.search(pattern, lowered):
            return False

    # Check for presence of USA indicators
    for usa in USA_GEO_INDICATORS:
        pattern = rf"\b{re.escape(usa)}\b"
        if re.search(pattern, lowered):
            return True

    # General US remote phrases
    if "remote" in lowered and ("c2c" in lowered or "contract" in lowered):
        return True

    return False


def matches_strict_filter(text: str) -> tuple[bool, str]:
    """Check if post is a genuine hiring requirement and not bench marketing.

    Returns:
        (True, "valid") if acceptable.
        (False, reason) if rejected.
    """
    lowered = text.lower()

    # Check for bench marketing / candidate representation
    for phrase in BENCH_MARKETING_PHRASES:
        if phrase in lowered:
            return False, f"bench_marketing: '{phrase}'"

    # Must contain C2C or Contractual indicator
    c2c_indicators = ["c2c", "corp to corp", "corp-to-corp", "c-to-c", "corp2corp", "1099", "contract"]
    if not any(ci in lowered for ci in c2c_indicators):
        return False, "missing_c2c_indicator"

    return True, "valid"


def check_domain_match(text: str, role_def: RoleDefinition) -> tuple[bool, str]:
    """Check if the post aligns with candidate's primary domain and exclusions.

    Returns:
        (True, "matched") if post matches target role domain.
        (False, "mismatched_role") if post is exclusively for an excluded domain.
    """
    lowered = text.lower()

    # If any exclusion keyword is the core focus without the primary role keywords
    has_primary_role = any(role_term.lower() in lowered for role_term in role_def.search_roles)

    for excl in role_def.exclusion_keywords:
        pattern = rf"\b{re.escape(excl.lower())}\b"
        if re.search(pattern, lowered) and not has_primary_role:
            return False, f"mismatched_role: excluded domain '{excl}'"

    return True, "matched"


def build_search_query(role_title: str) -> str:
    """Format LinkedIn boolean search query for C2C requirements."""
    # Query: "<Role> + C2C -hotlist -fulltime -"available consultants" -Bench"
    return f'"{role_title}" + C2C -hotlist -fulltime -"available consultants" -Bench'


def build_search_url(query: str) -> str:
    """Build LinkedIn content search URL with 24h filter and US geo target."""
    encoded_query = urllib.parse.quote(query)
    # geoUrn 103644278 is United States
    return (
        f"https://www.linkedin.com/search/results/content/?"
        f"keywords={encoded_query}&sortBy=%22date_posted%22&datePosted=%22past-24h%22&geoUrn=103644278"
    )


def parse_post_card(card_html: str, fallback_url: str = "") -> Optional[dict[str, Any]]:
    """Parse a single post card HTML snippet into structured post fields.

    Decoupled helper for offline unit testing without Playwright.
    """
    soup = BeautifulSoup(card_html, "html.parser")

    # Author name
    author_name = "Hiring Manager"
    for sel in [".update-components-actor__name", ".feed-shared-actor__name", "span[dir='ltr']"]:
        elem = soup.select_one(sel)
        if elem and elem.get_text(strip=True):
            author_name = elem.get_text(strip=True)
            break

    # Post text
    text_parts: list[str] = []
    text_containers = soup.select(
        ".feed-shared-update-v2__description, .update-components-text, .feed-shared-text, p"
    )
    for c in text_containers:
        t = c.get_text(separator="\n", strip=True)
        if t:
            text_parts.append(t)
    post_text = "\n".join(text_parts)

    if not post_text:
        return None

    # Emails
    emails = extract_all_emails(post_text, card_html)
    if not emails:
        return None

    # Post URL fallback
    post_url = fallback_url
    if not post_url:
        anchor = soup.select_one("a[href*='/posts/'], a[href*='/feed/update/']")
        if anchor and anchor.get("href"):
            post_url = clean_post_url(anchor["href"])

    return {
        "recruiter_name": author_name,
        "recruiter_email": emails[0],
        "all_emails": emails,
        "job_description": post_text,
        "post_url": post_url or "https://www.linkedin.com/feed/",
    }


class LinkedInScraper:
    """Headless scraper for LinkedIn C2C postings using saved session state."""

    def __init__(
        self,
        session_path: str | Path = "session.json",
        csv_store: Optional[CSVStore] = None,
        max_scrolls: int = 6,
        post_cap: int = 25,
    ) -> None:
        self.session_path = Path(session_path).resolve()
        self.csv_store = csv_store or CSVStore()
        self.max_scrolls = max_scrolls
        self.post_cap = post_cap

    def run_scraper(
        self,
        candidate: CandidateProfile,
        headless: bool = True,
    ) -> list[ScrapedPost]:
        """Scrape posts for the candidate's target roles and save to recruiters.csv."""
        if not self.session_path.exists():
            raise FileNotFoundError(
                f"Session file not found at {self.session_path}. "
                "Please run Option 2 (linkedin_login.py) to generate session.json first."
            )

        from playwright.sync_api import sync_playwright

        role_def = get_role_definition(candidate.primary_role)
        if not role_def:
            # Fallback to single primary role
            role_def = RoleDefinition(
                primary_role=candidate.primary_role,
                search_roles=[candidate.primary_role],
                exclusion_keywords=[],
            )

        scraped_results: list[ScrapedPost] = []
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            context = browser.new_context(
                storage_state=str(self.session_path),
                viewport={"width": 1366, "height": 900},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                permissions=["clipboard-read", "clipboard-write"],
            )
            page = context.new_page()

            for search_role in role_def.search_roles:
                if len(scraped_results) >= self.post_cap:
                    break

                query = build_search_query(search_role)
                search_url = build_search_url(query)
                logger.info("Scraping role '%s': %s", search_role, search_url)

                try:
                    page.goto(search_url, wait_until="domcontentloaded", timeout=60000)
                    time.sleep(random.uniform(2.0, 3.5))

                    # Scroll and expand posts
                    for scroll_idx in range(self.max_scrolls):
                        page.evaluate("window.scrollBy(0, window.innerHeight * 0.8)")
                        time.sleep(random.uniform(1.2, 2.2))

                        # Click "See more" buttons to expand truncated post bodies
                        see_mores = page.locator(SELECTORS["see_more_button"])
                        count = see_mores.count()
                        for i in range(min(count, 5)):
                            try:
                                btn = see_mores.nth(i)
                                if btn.is_visible():
                                    btn.click(timeout=1000)
                                    time.sleep(0.3)
                            except Exception:
                                pass

                    # Locate post cards
                    cards = page.locator(SELECTORS["post_card"])
                    card_count = cards.count()
                    logger.info("Found %d post cards for query '%s'", card_count, search_role)

                    for idx in range(card_count):
                        if len(scraped_results) >= self.post_cap:
                            break

                        card = cards.nth(idx)
                        card_html = card.inner_html()
                        parsed = parse_post_card(card_html)
                        if not parsed or not parsed["recruiter_email"]:
                            continue

                        recruiter_email = parsed["recruiter_email"]
                        jd_text = parsed["job_description"]
                        recruiter_name = parsed["recruiter_name"]

                        # Check if candidate already contacted recruiter in history
                        if self.csv_store.is_already_contacted(candidate.name, recruiter_email):
                            logger.info("Skipping already contacted recruiter: %s", recruiter_email)
                            continue

                        # Check suppression list
                        if self.csv_store.is_suppressed(recruiter_email):
                            logger.info("Skipping suppressed recruiter: %s", recruiter_email)
                            continue

                        # Strict Filters
                        is_strict, strict_reason = matches_strict_filter(jd_text)
                        if not is_strict:
                            logger.debug("Filtered out post: %s", strict_reason)
                            continue

                        if not is_usa_job(jd_text):
                            logger.debug("Filtered out post: non-USA job")
                            continue

                        # Domain match
                        is_domain_match, domain_reason = check_domain_match(jd_text, role_def)
                        status = "pending" if is_domain_match else "mismatched_role"

                        # Extract post URL via control menu clipboard or fallback
                        post_url = parsed["post_url"]
                        try:
                            card.scroll_into_view_if_needed(timeout=2000)
                            menu_btn = card.locator(SELECTORS["control_menu_button"]).first
                            if menu_btn.is_visible():
                                menu_btn.click(timeout=1500)
                                time.sleep(0.5)
                                copy_item = page.locator(SELECTORS["copy_link_option"]).first
                                if copy_item.is_visible():
                                    copy_item.click(timeout=1500)
                                    time.sleep(0.5)
                                    clip_text = page.evaluate("navigator.clipboard.readText()")
                                    if clip_text and "linkedin.com" in clip_text:
                                        post_url = clean_post_url(clip_text)
                        except Exception as e:
                            logger.debug("Clipboard capture failed, using fallback URL: %s", e)

                        scraped_post = ScrapedPost(
                            recruiter_name=recruiter_name,
                            recruiter_email=recruiter_email,
                            role=candidate.primary_role,
                            post_url=post_url,
                            job_description=jd_text,
                            email_sent_status=status,
                            timestamp=now_ts,
                        )

                        # Save into recruiters.csv
                        self.csv_store.save_recruiter({
                            "recruiter_name": scraped_post.recruiter_name,
                            "recruiter_email": scraped_post.recruiter_email,
                            "role": scraped_post.role,
                            "post_url": scraped_post.post_url,
                            "job_description": scraped_post.job_description,
                            "email_sent_status": scraped_post.email_sent_status,
                            "timestamp": scraped_post.timestamp,
                        })

                        scraped_results.append(scraped_post)
                        # Randomized delay between processing cards
                        time.sleep(random.uniform(0.5, 1.2))

                except Exception as e:
                    logger.error("Error scraping role %s: %s", search_role, e)

            browser.close()

        logger.info("Scraping completed. Extracted %d qualified posts.", len(scraped_results))
        return scraped_results
