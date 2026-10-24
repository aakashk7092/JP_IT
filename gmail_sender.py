"""Gmail SMTP outreach engine with technology hook synthesis, MIME generation,
suppression enforcement, and rate-limited dispatch.
"""

from __future__ import annotations

import email.utils
import logging
import os
import re
import smtplib
import ssl
import time
import uuid
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from dotenv import load_dotenv

from client_config import CandidateProfile
from csv_store import CSVStore

logger = logging.getLogger("recruitment_automation.gmail_sender")

# Curated list of 60+ technical skills for matching JD to candidate experience
JD_KEYWORDS: list[str] = [
    # Languages & Core
    "Java", "Python", "C#", ".NET", ".NET Core", "TypeScript", "JavaScript",
    "Go", "Golang", "C++", "SQL", "HTML5", "CSS3",
    # Frameworks & Libraries
    "Spring Boot", "Spring", "Microservices", "Hibernate", "JPA",
    "React", "Angular", "Vue.js", "Node.js", "Express",
    "FastAPI", "Flask", "Django", "ASP.NET", "Next.js",
    # Databases & Caching
    "PostgreSQL", "MySQL", "Oracle", "SQL Server", "MongoDB",
    "Cassandra", "Redis", "DynamoDB", "Elasticsearch", "Snowflake",
    # Cloud & DevOps
    "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Terraform",
    "Ansible", "Jenkins", "GitLab CI", "CI/CD", "Helm",
    # Messaging & Streaming
    "Kafka", "RabbitMQ", "ActiveMQ", "SQS", "SNS",
    # API & Architecture
    "REST API", "RESTful", "GraphQL", "gRPC", "SOAP", "Event-Driven",
    # Testing & Methodologies
    "JUnit", "Mockito", "PyTest", "Selenium", "TDD", "Agile", "Scrum",
    # Big Data & AI
    "Spark", "Hadoop", "Databricks", "Airflow", "Kafka Streams",
]


def normalize_keyword(kw: str) -> str:
    """Normalize keyword for matching (alphanumeric only)."""
    return re.sub(r"[^a-zA-Z0-9]", "", kw).lower()


def find_top_matching_keywords(
    job_description: str,
    candidate_skills: Sequence[str],
    max_keywords: int = 3,
) -> list[str]:
    """Find top overlapping keywords present in both the JD and the candidate's skills.

    Args:
        job_description: Plain text of the job description.
        candidate_skills: List of skills from candidate's profile/resume.
        max_keywords: Maximum number of keywords to return (default: 3).

    Returns:
        List of matching keyword strings.
    """
    jd_lower = job_description.lower()
    cand_norm_map = {normalize_keyword(s): s for s in candidate_skills if s.strip()}

    matches: list[str] = []

    for kw in JD_KEYWORDS:
        norm_kw = normalize_keyword(kw)
        if norm_kw in cand_norm_map:
            # Check if this keyword is in the JD
            pattern = rf"\b{re.escape(kw.lower())}\b"
            if re.search(pattern, jd_lower):
                matches.append(cand_norm_map[norm_kw])
                if len(matches) >= max_keywords:
                    break

    # If no curated keywords overlapped, fallback to direct search of candidate skills in JD
    if not matches:
        for s in candidate_skills:
            if len(s) > 2 and re.search(rf"\b{re.escape(s.lower())}\b", jd_lower):
                matches.append(s)
                if len(matches) >= max_keywords:
                    break

    return matches


def build_custom_hook(
    job_description: str,
    candidate_skills: Sequence[str],
    primary_role: str,
) -> str:
    """Synthesize a personalized technology hook based on matching skills."""
    top_matches = find_top_matching_keywords(job_description, candidate_skills, max_keywords=3)

    if len(top_matches) == 3:
        hook = f"My hands-on experience with {top_matches[0]}, {top_matches[1]}, and {top_matches[2]} maps directly to what you are looking for in this role."
    elif len(top_matches) == 2:
        hook = f"My hands-on experience with {top_matches[0]} and {top_matches[1]} maps directly to what you are looking for."
    elif len(top_matches) == 1:
        hook = f"My extensive hands-on expertise with {top_matches[0]} aligns directly with your project requirements."
    else:
        hook = f"My strong background as a {primary_role} aligns closely with the core deliverables in your job post."

    return hook


def build_email_content(
    recruiter_name: str,
    candidate: CandidateProfile,
    job_description: str,
) -> tuple[str, str]:
    """Generate subject and plain-text body for outreach email."""
    hook = build_custom_hook(
        job_description=job_description,
        candidate_skills=candidate.skills,
        primary_role=candidate.primary_role,
    )

    greeting_name = recruiter_name.strip()
    if not greeting_name or greeting_name.lower() in ("hiring manager", "recruiter", "talent acquisition"):
        salutation = "Hi,"
    else:
        first_name = greeting_name.split()[0]
        salutation = f"Hi {first_name},"

    subject = f"{candidate.name} - {candidate.primary_role} - Immediate C2C Availability"

    body = f"""{salutation}

I came across your LinkedIn posting regarding the {candidate.primary_role} opportunity and wanted to reach out directly.

{hook}

Key Highlights:
• {candidate.experience_years}+ years of enterprise software engineering experience
• Available immediately for C2C contract engagements across the USA
• Core Skills: {', '.join(candidate.skills[:7])}

I have attached my tailored resume for your review. Please let me know if you would like to connect for a quick introductory conversation or if you need any additional details.

Best regards,

{candidate.name}
{candidate.primary_role}
Email: {candidate.email}
{f"Phone: {candidate.phone}" if candidate.phone else ""}

---
Reply STOP to opt out of future communications.
"""
    return subject, body


def sanitize_filename(name: str) -> str:
    """Sanitize filename to ASCII alphanumeric characters."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", name)


def build_mime_message(
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    pdf_attachment_path: Optional[Path | str] = None,
    candidate_name: str = "Candidate",
    cc_emails: Optional[list[str]] = None,
    bcc_emails: Optional[list[str]] = None,
    custom_message_id: Optional[str] = None,
    in_reply_to: Optional[str] = None,
    references: Optional[str] = None,
) -> MIMEMultipart:
    """Construct RFC-compliant MIME message with attachment and threading headers."""
    msg = MIMEMultipart()

    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email

    if cc_emails:
        msg["Cc"] = ", ".join(cc_emails)
    if bcc_emails:
        msg["Bcc"] = ", ".join(bcc_emails)

    msg["Date"] = email.utils.formatdate(localtime=True)

    # Message-ID
    domain = from_email.split("@")[-1] if "@" in from_email else "gmail.com"
    msg_id = custom_message_id or f"<{uuid.uuid4()}@{domain}>"
    msg["Message-ID"] = msg_id

    # Threading headers for follow-ups
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
    if references:
        msg["References"] = references

    # Plain text body
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Attachment
    if pdf_attachment_path:
        pdf_path = Path(pdf_attachment_path).resolve()
        if pdf_path.exists():
            attachment_name = sanitize_filename(
                f"{candidate_name.replace(' ', '_')}_Resume_{int(time.time())}.pdf"
            )
            with open(pdf_path, "rb") as f:
                part = MIMEApplication(f.read(), _subtype="pdf")
                part.add_header(
                    "Content-Disposition",
                    "attachment",
                    filename=attachment_name,
                )
                msg.attach(part)
        else:
            logger.warning("PDF attachment path not found: %s", pdf_path)

    return msg


class GmailSender:
    """Gmail SMTP client with dual connection strategy (STARTTLS & SSL fallback)."""

    def __init__(
        self,
        csv_store: Optional[CSVStore] = None,
        inter_email_delay: float = 3.0,
    ) -> None:
        load_dotenv(override=True)
        self.csv_store = csv_store or CSVStore()
        self.inter_email_delay = inter_email_delay

        self.gmail_email = os.getenv("GMAIL_EMAIL", "").strip()
        self.app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
        self.operator_email = os.getenv("OPERATOR_EMAIL", self.gmail_email).strip()
        self.team_lead_email = os.getenv("TEAM_LEAD_EMAIL", "").strip()
        self.admin_bcc_email = os.getenv("ADMIN_BCC_EMAIL", "").strip()

        # Safety mode
        test_mode_str = os.getenv("TEST_MODE", "true").lower()
        self.test_mode = test_mode_str in ("true", "1", "yes")

        # Daily rate limit
        self.global_daily_limit = int(os.getenv("GLOBAL_DAILY_LIMIT", "50"))
        self.sent_today_count = 0

    def _send_smtp(self, msg: MIMEMultipart, recipients: list[str]) -> None:
        """Dispatch email over SMTP with STARTTLS (587) and SSL (465) fallback."""
        if not self.gmail_email or not self.app_password:
            raise ValueError("GMAIL_EMAIL and GMAIL_APP_PASSWORD must be configured in .env.")

        # Try Port 587 (STARTTLS)
        try:
            logger.debug("Connecting to smtp.gmail.com:587 (STARTTLS)...")
            with smtplib.SMTP("smtp.gmail.com", 587, timeout=25) as server:
                server.ehlo()
                server.starttls(context=ssl.create_default_context())
                server.ehlo()
                server.login(self.gmail_email, self.app_password)
                server.send_message(msg, from_addr=self.gmail_email, to_addrs=recipients)
                logger.info("Email dispatched successfully via port 587.")
                return
        except Exception as e_starttls:
            logger.warning("STARTTLS (587) attempt failed: %s. Trying SSL (465)...", e_starttls)

        # Fallback to Port 465 (SSL)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=25) as server:
            server.login(self.gmail_email, self.app_password)
            server.send_message(msg, from_addr=self.gmail_email, to_addrs=recipients)
            logger.info("Email dispatched successfully via port 465 (SSL fallback).")

    def send_outreach_email(
        self,
        candidate: CandidateProfile,
        recruiter_name: str,
        recruiter_email: str,
        role: str,
        post_url: str,
        job_description: str,
        pdf_path: Optional[Path | str] = None,
    ) -> tuple[bool, str]:
        """Send outreach email with de-duplication, suppression check, and history logging.

        Returns:
            (True, message_id) on success,
            (False, error_reason) on failure or skip.
        """
        clean_email = recruiter_email.strip().lower()

        # 1. Suppression check
        if self.csv_store.is_suppressed(clean_email):
            logger.info("Skipping email: %s is in suppression list.", clean_email)
            return False, "recruiter_suppressed"

        # 2. De-duplication check against history
        if self.csv_store.is_already_contacted(candidate.name, clean_email):
            logger.info("Skipping email: %s already contacted by %s", clean_email, candidate.name)
            return False, "already_contacted"

        # 3. Daily limit check
        if self.sent_today_count >= self.global_daily_limit:
            logger.warning("Daily outreach limit (%d) reached.", self.global_daily_limit)
            return False, "daily_limit_reached"

        # Generate subject and body
        subject, body = build_email_content(recruiter_name, candidate, job_description)

        # Build recipient lists
        actual_recipients: list[str] = []
        cc_list: list[str] = []
        bcc_list: list[str] = []

        if self.test_mode:
            # TEST MODE: Route email exclusively to operator
            target_to = self.operator_email
            subject = f"[TEST MODE - Intended for: {recruiter_email}] {subject}"
            actual_recipients = [self.operator_email]
            logger.info("[TEST MODE] Redirecting email to operator: %s", self.operator_email)
        else:
            target_to = recruiter_email
            actual_recipients.append(recruiter_email)
            if candidate.email:
                cc_list.append(candidate.email)
            if self.team_lead_email:
                cc_list.append(self.team_lead_email)
            if self.admin_bcc_email:
                bcc_list.append(self.admin_bcc_email)

            actual_recipients.extend(cc_list)
            actual_recipients.extend(bcc_list)

        msg = build_mime_message(
            from_email=self.gmail_email,
            to_email=target_to,
            subject=subject,
            body=body,
            pdf_attachment_path=pdf_path,
            candidate_name=candidate.name,
            cc_emails=cc_list if not self.test_mode else None,
            bcc_emails=bcc_list if not self.test_mode else None,
        )

        message_id = msg["Message-ID"]

        # Send over SMTP
        try:
            self._send_smtp(msg, actual_recipients)
            now_ts = time.strftime("%Y-%m-%d %H:%M:%S")

            # Record in email_sent_history.csv
            self.csv_store.record_sent_email({
                "recruiter_name": recruiter_name,
                "recruiter_email": clean_email,
                "role": role,
                "post_url": post_url,
                "candidate": candidate.name,
                "email_sent_status": "sent",
                "timestamp": now_ts,
                "subject": subject,
                "message_id": message_id,
                "followup_count": "0",
                "last_followup_at": "",
                "replied": "0",
            })

            # Update recruiters.csv status
            self.csv_store.update_recruiter_status(clean_email, post_url, "sent")
            self.sent_today_count += 1

            # Inter-email delay
            time.sleep(self.inter_email_delay)
            return True, message_id

        except Exception as e:
            logger.error("Failed to send email to %s: %s", recruiter_email, e)
            try:
                self.csv_store.update_recruiter_status(clean_email, post_url, "failed")
            except Exception:
                pass
            return False, str(e)
