"""IMAP recruiter reply detector and opt-out suppression sync.

Connects to Gmail IMAP in read-only mode, queries incoming emails since the oldest
unreplied outreach, marks matching replies in email_sent_history.csv, and automatically
records STOP/unsubscribe requests into suppression_list.csv.
"""

from __future__ import annotations

import datetime
import email
import email.utils
import imaplib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from dotenv import load_dotenv

from csv_store import CSVStore, write_csv, EMAIL_SENT_HISTORY_COLUMNS

logger = logging.getLogger("recruitment_automation.imap_detector")

OPT_OUT_REGEX = re.compile(
    r"\b(?:stop|unsubscribe|remove\s+me|take\s+me\s+off|not\s+interested|cease|opt\s*out)\b",
    re.IGNORECASE,
)


def extract_sender_email(from_header: str) -> str:
    """Extract clean lowercase email address from RFC From header."""
    if not from_header:
        return ""
    name, addr = email.utils.parseaddr(from_header)
    return addr.strip().lower()


def is_opt_out_reply(text_body: str, subject: str = "") -> bool:
    """Detect if the recruiter's email expresses an opt-out or unsubscribe intent."""
    combined = f"{subject}\n{text_body}"
    return bool(OPT_OUT_REGEX.search(combined))


def parse_date_to_datetime(ts_str: str) -> Optional[datetime.datetime]:
    """Parse standard timestamp strings to datetime objects."""
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d-%b-%Y"):
        try:
            return datetime.datetime.strptime(ts_str.strip(), fmt)
        except ValueError:
            pass
    return None


class IMAPReplyDetector:
    """Connects to Gmail IMAP securely to identify recruiter replies."""

    def __init__(
        self,
        csv_store: Optional[CSVStore] = None,
        lookback_days: int = 30,
    ) -> None:
        load_dotenv(override=True)
        self.csv_store = csv_store or CSVStore()
        self.lookback_days = int(os.getenv("IMAP_SYNC_DAYS", str(lookback_days)))
        self.gmail_email = os.getenv("GMAIL_EMAIL", "").strip()
        self.app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()

    def _connect_imap(self) -> imaplib.IMAP4_SSL:
        """Establish SSL connection to Gmail IMAP server."""
        if not self.gmail_email or not self.app_password:
            raise ValueError("GMAIL_EMAIL and GMAIL_APP_PASSWORD are required for IMAP reply detection.")

        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(self.gmail_email, self.app_password)
        # Select INBOX in strictly read-only mode so no user mail is altered
        mail.select("INBOX", readonly=True)
        return mail

    def sync_replies(self) -> dict[str, int]:
        """Scan INBOX for replies to unreplied sent outreach emails.

        Returns:
            dict with 'replied_count' and 'suppressed_count'.
        """
        history_rows = self.csv_store.get_history()
        if not history_rows:
            logger.info("No sent outreach history to check for replies.")
            return {"replied_count": 0, "suppressed_count": 0}

        # Identify all unreplied candidate emails
        unreplied_map: dict[str, list[dict[str, str]]] = {}
        oldest_dt: Optional[datetime.datetime] = None

        for row in history_rows:
            if row.get("email_sent_status") == "sent" and str(row.get("replied", "0")) == "0":
                rec_email = row.get("recruiter_email", "").strip().lower()
                if rec_email:
                    unreplied_map.setdefault(rec_email, []).append(row)
                    row_dt = parse_date_to_datetime(row.get("timestamp", ""))
                    if row_dt:
                        if oldest_dt is None or row_dt < oldest_dt:
                            oldest_dt = row_dt

        if not unreplied_map:
            logger.info("All sent outreach emails have already been marked as replied.")
            return {"replied_count": 0, "suppressed_count": 0}

        # Determine search SINCE date
        now = datetime.datetime.now()
        fallback_dt = now - datetime.timedelta(days=self.lookback_days)
        search_dt = oldest_dt if oldest_dt else fallback_dt
        if search_dt < fallback_dt:
            search_dt = fallback_dt

        imap_date_str = search_dt.strftime("%d-%b-%Y")
        logger.info("Checking IMAP replies for %d recruiters since %s", len(unreplied_map), imap_date_str)

        replied_count = 0
        suppressed_count = 0
        now_ts = time.strftime("%Y-%m-%d %H:%M:%S")

        try:
            mail = self._connect_imap()
        except Exception as e:
            logger.error("Failed to connect to Gmail IMAP: %s", e)
            return {"replied_count": 0, "suppressed_count": 0}

        try:
            status, search_data = mail.search(None, f'(SINCE "{imap_date_str}")')
            if status != "OK" or not search_data or not search_data[0]:
                logger.info("No incoming emails found on IMAP since %s", imap_date_str)
                mail.close()
                mail.logout()
                return {"replied_count": 0, "suppressed_count": 0}

            msg_ids = search_data[0].split()
            logger.info("Found %d total incoming messages since %s. Processing in batches of 100...", len(msg_ids), imap_date_str)

            # Process in batches of 100
            batch_size = 100
            matched_recruiter_emails: set[str] = set()

            for i in range(0, len(msg_ids), batch_size):
                batch = msg_ids[i:i + batch_size]
                id_sequence = b",".join(batch).decode("ascii")

                res, fetch_data = mail.fetch(id_sequence, "(BODY.PEEK[HEADER] BODY.PEEK[TEXT])")
                if res != "OK":
                    continue

                for j in range(0, len(fetch_data), 2):
                    item = fetch_data[j]
                    if not isinstance(item, tuple) or len(item) < 2:
                        continue

                    raw_content = item[1]
                    try:
                        msg = email.message_from_bytes(raw_content)
                        sender = extract_sender_email(msg.get("From", ""))
                        if not sender:
                            continue

                        if sender in unreplied_map:
                            matched_recruiter_emails.add(sender)
                            subject = msg.get("Subject", "")

                            # Extract plain body snippet
                            body_text = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        body_text = part.get_payload(decode=True).decode("utf-8", errors="replace")
                                        break
                            else:
                                body_text = msg.get_payload(decode=True).decode("utf-8", errors="replace")

                            # Check for STOP / Unsubscribe intent
                            if is_opt_out_reply(body_text, subject):
                                if not self.csv_store.is_suppressed(sender):
                                    self.csv_store.add_suppression(
                                        recruiter_email=sender,
                                        reason="STOP/opt-out reply via IMAP",
                                        timestamp=now_ts,
                                    )
                                    suppressed_count += 1
                                    logger.warning("Recruiter %s requested STOP. Added to suppression list.", sender)

                    except Exception as parse_err:
                        logger.debug("Error parsing email message: %s", parse_err)

            # Update email_sent_history.csv with replied=1
            if matched_recruiter_emails:
                for row in history_rows:
                    rec_email = row.get("recruiter_email", "").strip().lower()
                    if rec_email in matched_recruiter_emails:
                        if str(row.get("replied", "0")) == "0":
                            row["replied"] = "1"
                            replied_count += 1

                write_csv(self.csv_store.history_path, history_rows, EMAIL_SENT_HISTORY_COLUMNS)
                logger.info("Updated %d sent history rows to replied=1", replied_count)

            mail.close()
            mail.logout()

        except Exception as e:
            logger.error("Unexpected error during IMAP reply sync: %s", e)

        return {"replied_count": replied_count, "suppressed_count": suppressed_count}
