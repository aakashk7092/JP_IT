"""Unit tests for analytics.py verifying metrics calculation and HTML report generation."""

from pathlib import Path

from analytics import calculate_metrics, generate_dark_html_report
from csv_store import CSVStore


def test_calculate_metrics_empty(tmp_path: Path):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )
    summary = calculate_metrics(store)
    assert summary.total_recruiters == 0
    assert summary.sent_outreach == 0
    assert summary.reply_rate_pct == 0.0
    assert summary.followups_sent == 0


def test_calculate_metrics_with_data(tmp_path: Path):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    # Recruiters
    store.save_recruiter({
        "recruiter_name": "R1",
        "recruiter_email": "r1@test.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/1",
        "job_description": "Java JD",
        "email_sent_status": "sent",
        "timestamp": "2026-10-24 10:00:00",
    })
    store.save_recruiter({
        "recruiter_name": "R2",
        "recruiter_email": "r2@test.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/2",
        "job_description": "Java JD",
        "email_sent_status": "pending",
        "timestamp": "2026-10-24 10:00:00",
    })

    # Sent History (2 sent, 1 replied, 1 followup)
    store.record_sent_email({
        "recruiter_name": "R1",
        "recruiter_email": "r1@test.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/1",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": "2026-10-20 10:00:00",
        "subject": "Java Role",
        "message_id": "<m1@g>",
        "followup_count": "1",
        "last_followup_at": "2026-10-24 10:00:00",
        "replied": "1",
    })
    store.record_sent_email({
        "recruiter_name": "R3",
        "recruiter_email": "r3@test.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/3",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": "2026-10-21 10:00:00",
        "subject": "Java Role 3",
        "message_id": "<m3@g>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })

    # Suppression
    store.add_suppression("stop@test.com", "STOP", "2026-10-24 10:00:00")

    summary = calculate_metrics(store)
    assert summary.total_recruiters == 2
    assert summary.pending_recruiters == 1
    assert summary.sent_outreach == 2
    assert summary.total_replies == 1
    assert summary.reply_rate_pct == 50.0
    assert summary.followups_sent == 1
    assert summary.total_suppressed == 1
    assert "Alex Johnson" in summary.candidate_stats
    assert summary.candidate_stats["Alex Johnson"]["sent"] == 2


def test_generate_dark_html_report(tmp_path: Path):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )
    store.record_sent_email({
        "recruiter_name": "Recruiter One",
        "recruiter_email": "r1@example.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/1",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": "2026-10-24 10:00:00",
        "subject": "Alex Johnson",
        "message_id": "<msg-1@g>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })

    summary = calculate_metrics(store)
    report_file = tmp_path / "report.html"

    out_path = generate_dark_html_report(summary, output_path=report_file)
    assert out_path.exists()

    content = out_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in content
    assert "Recruitment &amp; Outreach Analytics" in content or "Recruitment & Outreach Analytics" in content
    assert "--bg-base: #090d16;" in content
    assert "Alex Johnson" in content
    assert "Java Developer" in content
