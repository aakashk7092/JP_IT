"""Unit tests for csv_store.py verifying schemas, atomic writes, and header migrations."""

import csv
from pathlib import Path

import pytest

from csv_store import (
    CSVStore,
    EMAIL_SENT_HISTORY_COLUMNS,
    RECRUITERS_COLUMNS,
    SUPPRESSION_COLUMNS,
    append_row,
    migrate_headers,
    read_csv,
    upsert_row,
    write_csv,
)


def test_migrate_headers_creates_new_file(tmp_path: Path):
    target = tmp_path / "new.csv"
    headers = ["col1", "col2", "col3"]

    migrated = migrate_headers(target, headers)
    assert migrated is True
    assert target.exists()

    with open(target, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        written_headers = next(reader)
    assert written_headers == headers


def test_migrate_headers_evolves_schema_preserving_data(tmp_path: Path):
    target = tmp_path / "legacy.csv"
    initial_headers = ["name", "email"]
    rows = [
        {"name": "Alice", "email": "alice@example.com"},
        {"name": "Bob", "email": "bob@example.com"},
    ]
    write_csv(target, rows, initial_headers)

    # Now migrate to a schema with extra columns
    expanded_headers = ["name", "email", "role", "status"]
    migrated = migrate_headers(target, expanded_headers)
    assert migrated is True

    # Read back and verify columns and preserved data
    updated_rows = read_csv(target)
    assert len(updated_rows) == 2
    assert updated_rows[0]["name"] == "Alice"
    assert updated_rows[0]["email"] == "alice@example.com"
    assert updated_rows[0]["role"] == ""
    assert updated_rows[0]["status"] == ""

    # Second migration with same headers should do nothing
    second_run = migrate_headers(target, expanded_headers)
    assert second_run is False


def test_atomic_write_integrity(tmp_path: Path):
    target = tmp_path / "atomic.csv"
    headers = ["id", "val"]
    data = [{"id": str(i), "val": f"val_{i}"} for i in range(100)]

    write_csv(target, data, headers)
    read_data = read_csv(target)
    assert len(read_data) == 100
    assert read_data[50]["val"] == "val_50"


def test_upsert_row(tmp_path: Path):
    target = tmp_path / "upsert.csv"
    headers = ["email", "status", "count"]

    # Initial insert
    upsert_row(
        target,
        {"email": "recruiter@tech.com", "status": "pending", "count": "0"},
        key_fields=["email"],
        fieldnames=headers,
    )

    rows = read_csv(target)
    assert len(rows) == 1
    assert rows[0]["status"] == "pending"

    # Upsert with changed status
    upsert_row(
        target,
        {"email": "recruiter@tech.com", "status": "sent", "count": "1"},
        key_fields=["email"],
        fieldnames=headers,
    )

    rows = read_csv(target)
    assert len(rows) == 1
    assert rows[0]["status"] == "sent"
    assert rows[0]["count"] == "1"


def test_csv_store_recruiter_and_history_operations(tmp_path: Path):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    # Save recruiter
    store.save_recruiter({
        "recruiter_name": "Jane Recruiter",
        "recruiter_email": "jane@corp.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/posts/123",
        "job_description": "Looking for Java C2C",
        "email_sent_status": "pending",
        "timestamp": "2026-10-24 10:00:00",
    })

    pending = store.get_pending_recruiters()
    assert len(pending) == 1
    assert pending[0]["recruiter_email"] == "jane@corp.com"

    # Update status
    updated = store.update_recruiter_status(
        recruiter_email="jane@corp.com",
        post_url="https://linkedin.com/posts/123",
        new_status="sent",
    )
    assert updated is True
    assert len(store.get_pending_recruiters()) == 0

    # Invalid status should raise ValueError
    with pytest.raises(ValueError):
        store.update_recruiter_status("jane@corp.com", "https://linkedin.com/posts/123", "invalid_status")

    # Record history
    assert not store.is_already_contacted("Alex Johnson", "jane@corp.com")
    store.record_sent_email({
        "recruiter_name": "Jane Recruiter",
        "recruiter_email": "jane@corp.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/posts/123",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": "2026-10-24 10:05:00",
        "subject": "Alex Johnson - Java Developer",
        "message_id": "<msg-123@gmail.com>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })
    assert store.is_already_contacted("Alex Johnson", "jane@corp.com")


def test_suppression_list_handling(tmp_path: Path):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    assert not store.is_suppressed("optout@agency.com")
    store.add_suppression("optout@agency.com", reason="STOP reply", timestamp="2026-10-24 10:10:00")
    assert store.is_suppressed("optout@agency.com")
    assert store.is_suppressed("OPTOUT@AGENCY.COM")  # Case insensitive
