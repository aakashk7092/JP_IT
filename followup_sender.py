"""Threaded follow-up engine for unreplied candidate outreach emails.

Maintains email conversation threading with In-Reply-To and References headers,
generates a concise AI value proposition, re-attaches candidate resume,
and enforces prerequisite IMAP reply synchronization.
"""

from __future__ import annotations

import datetime
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dotenv import load_dotenv

from client_config import CLIENTS, CandidateProfile, get_candidate_by_id
from csv_store import CSVStore, write_csv, EMAIL_SENT_HISTORY_COLUMNS
from gmail_sender import GmailSender, build_mime_message
from imap_reply_detector import IMAPReplyDetector, parse_date_to_datetime
from llm_client import LLMClient

logger = logging.getLogger("recruitment_automation.followup_sender")


def generate_followup_value_prop(
    candidate: CandidateProfile,
    role: str,
    llm_client: Optional[LLMClient] = None,
) -> str:
    """Generate a crisp 1-2 sentence value proposition for follow-up email."""
    client = llm_client or LLMClient()
    prompt = (
        f"Generate a crisp, professional 1-2 sentence follow-up value hook for a recruiter. "
        f"Candidate: {candidate.name}, Role: {candidate.primary_role}, Experience: {candidate.experience_years} years. "
        f"Top Skills: {', '.join(candidate.skills[:5])}. "
        f"Available immediately on C2C in the USA. "
        f"Strict rule: Do not invent any new employers or technologies. Keep it under 40 words."
    )

    followup_sys_prompt = "You are a professional executive recruiter assistant. Write a polite, crisp 1-2 sentence follow-up value hook."
    # Try OpenRouter, Groq, or Gemini
    for provider in ["openrouter", "groq", "gemini"]:
        try:
            if provider == "openrouter" and getattr(client, "openrouter_key", ""):
                val = client.call_openrouter(prompt, system_prompt=followup_sys_prompt, as_json=False).strip()
            elif provider == "groq" and getattr(client, "groq_key", ""):
                val = client.call_groq(prompt, system_prompt=followup_sys_prompt, as_json=False).strip()
            elif provider == "gemini" and getattr(client, "gemini_key", ""):
                val = client.call_gemini(prompt, system_prompt=followup_sys_prompt, as_json=False).strip()
            else:
                continue

            # Strip any quotes or extra whitespace
            clean_val = val.strip('"\n ')
            if len(clean_val) > 20:
                return clean_val
        except Exception as e:
            logger.debug("Provider %s failed for followup hook: %s", provider, e)

    # Fallback value proposition
    return (
        f"I wanted to follow up and see if there are any updates regarding the {candidate.primary_role} opening. "
        f"{candidate.name} has deep hands-on expertise in {', '.join(candidate.skills[:3])} and is available immediately on C2C."
    )


class FollowupSender:
    """Orchestrates threaded follow-up emails for outreach campaigns."""

    def __init__(
        self,
        csv_store: Optional[CSVStore] = None,
        gmail_sender: Optional[GmailSender] = None,
        imap_detector: Optional[IMAPReplyDetector] = None,
        llm_client: Optional[LLMClient] = None,
    ) -> None:
        load_dotenv(override=True)
        self.csv_store = csv_store or CSVStore()
        self.gmail_sender = gmail_sender or GmailSender(csv_store=self.csv_store)
        self.imap_detector = imap_detector or IMAPReplyDetector(csv_store=self.csv_store)
        self.llm_client = llm_client or LLMClient()
        self.followup_days = int(os.getenv("FOLLOWUP_DAYS", "7"))

    def find_eligible_followups(self, days_threshold: Optional[int] = None) -> list[dict[str, str]]:
        """Identify sent emails eligible for a 7-day follow-up.

        Criteria:
        - status == 'sent'
        - followup_count == '0'
        - replied == '0'
        - sent >= days_threshold ago
        - recruiter not in suppression_list
        """
        threshold = days_threshold if days_threshold is not None else self.followup_days
        history_rows = self.csv_store.get_history()
        eligible: list[dict[str, str]] = []
        now = datetime.datetime.now()

        suppressed_emails = self.csv_store.get_suppression_list()

        for r in history_rows:
            if r.get("email_sent_status") != "sent":
                continue
            if str(r.get("followup_count", "0")) != "0":
                continue
            if str(r.get("replied", "0")) != "0":
                continue

            rec_email = r.get("recruiter_email", "").strip().lower()
            if rec_email in suppressed_emails:
                continue

            sent_dt = parse_date_to_datetime(r.get("timestamp", ""))
            if not sent_dt:
                continue

            days_diff = (now - sent_dt).days
            if days_diff >= threshold:
                eligible.append(r)

        return eligible

    def send_followup_for_record(
        self,
        history_record: dict[str, str],
        candidate: CandidateProfile,
    ) -> tuple[bool, str]:
        """Dispatch a threaded follow-up email for a specific history record."""
        recruiter_email = history_record.get("recruiter_email", "").strip()
        recruiter_name = history_record.get("recruiter_name", "").strip()
        orig_subject = history_record.get("subject", "")
        orig_msg_id = history_record.get("message_id", "").strip()

        # Subject threading
        if orig_subject.lower().startswith("re:"):
            subject = orig_subject
        else:
            subject = f"Re: {orig_subject}"

        salutation = f"Hi {recruiter_name.split()[0]}," if recruiter_name and recruiter_name.lower() not in ("hiring manager", "recruiter") else "Hi,"
        value_prop = generate_followup_value_prop(candidate, candidate.primary_role, self.llm_client)

        body = f"""{salutation}

{value_prop}

Please find my resume re-attached for your convenience. Please let me know if you would like to discuss next steps.

Best regards,

{candidate.name}
{candidate.primary_role}
Email: {candidate.email}
{f"Phone: {candidate.phone}" if candidate.phone else ""}

---
Reply STOP to opt out of future communications.
"""
        # Resolve resume path
        resume_path = candidate.get_absolute_resume_path()

        # Build recipient lists
        target_to = recruiter_email
        actual_recipients: list[str] = []
        cc_list: list[str] = []
        bcc_list: list[str] = []

        if self.gmail_sender.test_mode:
            target_to = self.gmail_sender.operator_email
            subject = f"[TEST MODE - Follow-up for: {recruiter_email}] {subject}"
            actual_recipients = [self.gmail_sender.operator_email]
        else:
            actual_recipients.append(recruiter_email)
            if candidate.email:
                cc_list.append(candidate.email)
            if self.gmail_sender.team_lead_email:
                cc_list.append(self.gmail_sender.team_lead_email)
            if self.gmail_sender.admin_bcc_email:
                bcc_list.append(self.gmail_sender.admin_bcc_email)

            actual_recipients.extend(cc_list)
            actual_recipients.extend(bcc_list)

        msg = build_mime_message(
            from_email=self.gmail_sender.gmail_email,
            to_email=target_to,
            subject=subject,
            body=body,
            pdf_attachment_path=resume_path if resume_path.exists() else None,
            candidate_name=candidate.name,
            cc_emails=cc_list if not self.gmail_sender.test_mode else None,
            bcc_emails=bcc_list if not self.gmail_sender.test_mode else None,
            in_reply_to=orig_msg_id if orig_msg_id else None,
            references=orig_msg_id if orig_msg_id else None,
        )

        try:
            self.gmail_sender._send_smtp(msg, actual_recipients)
            now_ts = time.strftime("%Y-%m-%d %H:%M:%S")

            # Update row in email_sent_history.csv
            history = self.csv_store.get_history()
            for h in history:
                if (
                    h.get("recruiter_email", "").strip().lower() == recruiter_email.lower()
                    and h.get("candidate", "").strip().lower() == candidate.name.lower()
                    and h.get("message_id", "").strip() == orig_msg_id
                ):
                    h["followup_count"] = "1"
                    h["last_followup_at"] = now_ts

            write_csv(self.csv_store.history_path, history, EMAIL_SENT_HISTORY_COLUMNS)
            logger.info("Follow-up sent successfully to %s for %s", recruiter_email, candidate.name)

            time.sleep(self.gmail_sender.inter_email_delay)
            return True, msg["Message-ID"]

        except Exception as e:
            logger.error("Failed to send follow-up to %s: %s", recruiter_email, e)
            return False, str(e)

    def process_all_followups(self, days_threshold: Optional[int] = None) -> int:
        """Execute full follow-up workflow: sync replies first, then process eligible records."""
        logger.info("Step 1: Running prerequisite IMAP reply synchronization...")
        sync_result = self.imap_detector.sync_replies()
        logger.info(
            "Reply sync finished. %d new replies detected, %d new recruiters suppressed.",
            sync_result.get("replied_count", 0),
            sync_result.get("suppressed_count", 0),
        )

        logger.info("Step 2: Searching for eligible follow-ups...")
        eligible = self.find_eligible_followups(days_threshold)
        logger.info("Found %d eligible follow-ups to dispatch.", len(eligible))

        # Index candidates by name
        cand_map = {c.name.strip().lower(): c for c in CLIENTS}

        sent_count = 0
        for rec in eligible:
            cand_name = rec.get("candidate", "").strip().lower()
            candidate = cand_map.get(cand_name)
            if not candidate:
                logger.warning("Could not find candidate profile for name: %s", rec.get("candidate"))
                continue

            success, _ = self.send_followup_for_record(rec, candidate)
            if success:
                sent_count += 1

        logger.info("Completed follow-ups processing. Total sent: %d", sent_count)
        return sent_count
