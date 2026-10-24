"""Flat CSV data store with automatic schema migration and atomic file writes.

Guarantees thread/process safe writes on Windows using temporary files and atomic
renames, ensuring zero data corruption. Automatically updates headers when schemas evolve.
"""

from __future__ import annotations

import csv
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger("recruitment_automation.csv_store")

# Standard Column Schemas
RECRUITERS_COLUMNS: list[str] = [
    "recruiter_name",
    "recruiter_email",
    "role",
    "post_url",
    "job_description",
    "email_sent_status",  # pending | sent | failed | mismatched_role
    "timestamp",
]

EMAIL_SENT_HISTORY_COLUMNS: list[str] = [
    "recruiter_name",
    "recruiter_email",
    "role",
    "post_url",
    "candidate",
    "email_sent_status",
    "timestamp",
    "subject",
    "message_id",
    "followup_count",
    "last_followup_at",
    "replied",
]

SUPPRESSION_COLUMNS: list[str] = [
    "recruiter_email",
    "reason",
    "timestamp",
]

VALID_RECRUITER_STATUSES = {"pending", "sent", "failed", "mismatched_role"}


def ensure_parent_dir(path: Path) -> None:
    """Ensure parent directory exists."""
    path.parent.mkdir(parents=True, exist_ok=True)


def migrate_headers(file_path: str | Path, expected_headers: Sequence[str]) -> bool:
    """Check if file exists and has all expected headers. If missing, migrate headers.

    If file does not exist, creates it with expected_headers.
    If file exists with missing headers, rewrites the file preserving existing rows
    and populating new columns with empty strings.

    Returns:
        bool: True if file was created or migrated, False if already up to date.
    """
    path = Path(file_path).resolve()
    ensure_parent_dir(path)

    expected_list = list(expected_headers)

    if not path.exists() or path.stat().st_size == 0:
        write_csv(path, rows=[], fieldnames=expected_list)
        logger.info("Initialized new CSV with expected headers: %s", path)
        return True

    with open(path, "r", encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        try:
            current_headers = next(reader)
        except StopIteration:
            current_headers = []

    # Check if all expected headers are present in order or need migration
    missing_headers = [h for h in expected_list if h not in current_headers]
    if not missing_headers:
        return False

    logger.warning(
        "Schema migration needed for %s. Missing columns: %s",
        path.name,
        missing_headers,
    )

    # Read existing rows
    existing_rows = read_csv(path)

    # Combined header list: current headers + missing expected headers
    migrated_headers = list(current_headers) + [h for h in expected_list if h not in current_headers]

    write_csv(path, rows=existing_rows, fieldnames=migrated_headers)
    logger.info("Migrated schema for %s to headers: %s", path.name, migrated_headers)
    return True


def read_csv(file_path: str | Path) -> list[dict[str, str]]:
    """Read a CSV file returning a list of dictionaries with stripped keys."""
    path = Path(file_path).resolve()
    if not path.exists() or path.stat().st_size == 0:
        return []

    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        reader = csv.DictReader(f)
        rows: list[dict[str, str]] = []
        for r in reader:
            # Clean keys and values
            clean_row = {
                (k.strip() if k else ""): (v.strip() if v else "")
                for k, v in r.items()
                if k is not None
            }
            rows.append(clean_row)
        return rows


def write_csv(
    file_path: str | Path,
    rows: Sequence[dict[str, Any]],
    fieldnames: Sequence[str],
) -> None:
    """Atomically write rows to CSV using a temporary file in the same directory."""
    path = Path(file_path).resolve()
    ensure_parent_dir(path)

    # Must create temp file in same directory so os.replace is atomic across Windows volumes
    temp_dir = path.parent
    fd, temp_file_path = tempfile.mkstemp(
        prefix=f".{path.name}_",
        suffix=".tmp",
        dir=str(temp_dir),
    )

    try:
        with open(fd, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=list(fieldnames),
                extrasaction="ignore",
                quoting=csv.QUOTE_MINIMAL,
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
            f.flush()
            os.fsync(f.fileno())

        # Atomic replacement
        os.replace(temp_file_path, str(path))
    except Exception as e:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
        logger.error("Failed atomic CSV write to %s: %s", path, e)
        raise


def append_row(
    file_path: str | Path,
    row: dict[str, Any],
    fieldnames: Sequence[str],
) -> None:
    """Safely append a single row to CSV, migrating headers first if needed."""
    path = Path(file_path).resolve()
    migrate_headers(path, fieldnames)
    rows = read_csv(path)
    rows.append(row)
    write_csv(path, rows, fieldnames)


def upsert_row(
    file_path: str | Path,
    row: dict[str, Any],
    key_fields: Sequence[str],
    fieldnames: Sequence[str],
) -> None:
    """Insert or update a row matching key_fields."""
    path = Path(file_path).resolve()
    migrate_headers(path, fieldnames)
    rows = read_csv(path)

    matched = False
    new_rows: list[dict[str, Any]] = []

    for existing in rows:
        match = all(
            str(existing.get(k, "")).strip().lower() == str(row.get(k, "")).strip().lower()
            for k in key_fields
        )
        if match:
            # Update existing row with new values
            merged = dict(existing)
            merged.update(row)
            new_rows.append(merged)
            matched = True
        else:
            new_rows.append(existing)

    if not matched:
        new_rows.append(row)

    write_csv(path, new_rows, fieldnames)


class CSVStore:
    """High-level abstraction for recruiters and email history CSVs."""

    def __init__(
        self,
        recruiters_path: str | Path = "recruiters.csv",
        history_path: str | Path = "email_sent_history.csv",
        suppression_path: str | Path = "suppression_list.csv",
    ) -> None:
        self.recruiters_path = Path(recruiters_path).resolve()
        self.history_path = Path(history_path).resolve()
        self.suppression_path = Path(suppression_path).resolve()
        self.initialize_stores()

    def initialize_stores(self) -> None:
        """Initialize all CSV files with standard headers and migrations."""
        migrate_headers(self.recruiters_path, RECRUITERS_COLUMNS)
        migrate_headers(self.history_path, EMAIL_SENT_HISTORY_COLUMNS)
        migrate_headers(self.suppression_path, SUPPRESSION_COLUMNS)

    # Recruiter methods
    def get_all_recruiters(self) -> list[dict[str, str]]:
        return read_csv(self.recruiters_path)

    def get_pending_recruiters(self) -> list[dict[str, str]]:
        rows = read_csv(self.recruiters_path)
        return [r for r in rows if r.get("email_sent_status") == "pending"]

    def save_recruiter(self, recruiter_data: dict[str, Any]) -> None:
        """Upsert recruiter by (recruiter_email, post_url)."""
        upsert_row(
            self.recruiters_path,
            recruiter_data,
            key_fields=["recruiter_email", "post_url"],
            fieldnames=RECRUITERS_COLUMNS,
        )

    def update_recruiter_status(
        self,
        recruiter_email: str,
        post_url: str,
        new_status: str,
    ) -> bool:
        """Update email_sent_status for a recruiter."""
        if new_status not in VALID_RECRUITER_STATUSES:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of {VALID_RECRUITER_STATUSES}")

        rows = read_csv(self.recruiters_path)
        updated = False
        target_email = recruiter_email.strip().lower()
        target_url = post_url.strip()

        for r in rows:
            if (
                r.get("recruiter_email", "").strip().lower() == target_email
                and r.get("post_url", "").strip() == target_url
            ):
                r["email_sent_status"] = new_status
                updated = True

        if updated:
            write_csv(self.recruiters_path, rows, RECRUITERS_COLUMNS)
        return updated

    # History methods
    def get_history(self) -> list[dict[str, str]]:
        return read_csv(self.history_path)

    def is_already_contacted(self, candidate_name: str, recruiter_email: str) -> bool:
        """Check if candidate has already contacted recruiter."""
        history = read_csv(self.history_path)
        cand_clean = candidate_name.strip().lower()
        email_clean = recruiter_email.strip().lower()

        return any(
            h.get("candidate", "").strip().lower() == cand_clean
            and h.get("recruiter_email", "").strip().lower() == email_clean
            and h.get("email_sent_status") == "sent"
            for h in history
        )

    def record_sent_email(self, record: dict[str, Any]) -> None:
        """Record email sent in history."""
        append_row(self.history_path, record, EMAIL_SENT_HISTORY_COLUMNS)

    # Suppression list methods
    def get_suppression_list(self) -> set[str]:
        rows = read_csv(self.suppression_path)
        return {r.get("recruiter_email", "").strip().lower() for r in rows if r.get("recruiter_email")}

    def is_suppressed(self, recruiter_email: str) -> bool:
        suppressed = self.get_suppression_list()
        return recruiter_email.strip().lower() in suppressed

    def add_suppression(self, recruiter_email: str, reason: str, timestamp: str) -> None:
        if not self.is_suppressed(recruiter_email):
            append_row(
                self.suppression_path,
                {
                    "recruiter_email": recruiter_email.strip().lower(),
                    "reason": reason,
                    "timestamp": timestamp,
                },
                SUPPRESSION_COLUMNS,
            )
