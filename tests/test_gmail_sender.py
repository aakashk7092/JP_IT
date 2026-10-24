"""Unit tests for gmail_sender.py verifying tech hook synthesis, MIME creation,
suppression list enforcement, de-duplication, and mocked SMTP delivery.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from client_config import CandidateProfile
from csv_store import CSVStore
from gmail_sender import (
    JD_KEYWORDS,
    GmailSender,
    build_custom_hook,
    build_email_content,
    build_mime_message,
    find_top_matching_keywords,
    sanitize_filename,
)


@pytest.fixture
def sample_candidate() -> CandidateProfile:
    return CandidateProfile(
        id="alex_test",
        name="Alex Johnson",
        email="alex.johnson@example.com",
        primary_role="Java Full Stack Developer",
        experience_years=8,
        resume_path="clients/resumes/dummy_alex_johnson.docx",
        skills=["Java", "Spring Boot", "PostgreSQL", "Docker", "AWS", "Kafka", "Hibernate"],
        phone="+1-555-019-2831",
    )


def test_jd_keywords_count():
    assert len(JD_KEYWORDS) >= 60
    assert "Java" in JD_KEYWORDS
    assert "Spring Boot" in JD_KEYWORDS
    assert "PostgreSQL" in JD_KEYWORDS


def test_find_top_matching_keywords(sample_candidate: CandidateProfile):
    jd = (
        "We are looking for a Senior Java Developer with strong Spring Boot, "
        "PostgreSQL, and Kafka skills for a high-priority C2C contract role."
    )
    matches = find_top_matching_keywords(jd, sample_candidate.skills, max_keywords=3)
    assert len(matches) == 3
    assert "Java" in matches
    assert "Spring Boot" in matches
    assert "PostgreSQL" in matches


def test_build_custom_hook(sample_candidate: CandidateProfile):
    # 3 matches
    jd_3 = "Requires Java, Spring Boot, and PostgreSQL."
    hook_3 = build_custom_hook(jd_3, sample_candidate.skills, sample_candidate.primary_role)
    assert "Java, Spring Boot, and PostgreSQL" in hook_3

    # Fallback when no direct overlap
    jd_none = "Looking for an expert with Cobol and Mainframe."
    hook_fallback = build_custom_hook(jd_none, ["React"], "Java Developer")
    assert "Java Developer" in hook_fallback


def test_build_email_content_and_opt_out(sample_candidate: CandidateProfile):
    jd = "Java with AWS and Docker required."
    subject, body = build_email_content(
        recruiter_name="Sarah Miller",
        candidate=sample_candidate,
        job_description=jd,
    )
    assert "Alex Johnson" in subject
    assert "Hi Sarah," in body
    assert "Reply STOP to opt out" in body
    assert "+1-555-019-2831" in body


def test_sanitize_filename():
    assert sanitize_filename("Alex Johnson Resume (v2).pdf") == "Alex_Johnson_Resume__v2_.pdf"
    assert sanitize_filename("Candidate_123.pdf") == "Candidate_123.pdf"


def test_build_mime_message(tmp_path: Path):
    dummy_pdf = tmp_path / "resume.pdf"
    dummy_pdf.write_bytes(b"%PDF-1.4 test")

    msg = build_mime_message(
        from_email="sender@gmail.com",
        to_email="recruiter@agency.com",
        subject="Java Candidate",
        body="Email body content",
        pdf_attachment_path=dummy_pdf,
        candidate_name="Alex Johnson",
        cc_emails=["candidate@test.com", "lead@test.com"],
        bcc_emails=["admin@test.com"],
    )

    assert msg["Subject"] == "Java Candidate"
    assert msg["From"] == "sender@gmail.com"
    assert msg["To"] == "recruiter@agency.com"
    assert "candidate@test.com" in msg["Cc"]
    assert "admin@test.com" in msg["Bcc"]
    assert "Message-ID" in msg

    # Verify attachment
    payload = msg.get_payload()
    assert len(payload) == 2  # text + application/pdf
    assert payload[1].get_content_type() == "application/pdf"


def test_gmail_sender_dedup_and_suppression(tmp_path: Path, sample_candidate: CandidateProfile):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    sender = GmailSender(csv_store=store, inter_email_delay=0.0)
    sender.gmail_email = "test@gmail.com"
    sender.app_password = "test_password"
    sender.test_mode = False

    # 1. Add recruiter to suppression list
    store.add_suppression("optout@agency.com", reason="STOP", timestamp="2026-10-24 10:00:00")
    success, reason = sender.send_outreach_email(
        candidate=sample_candidate,
        recruiter_name="Opt Out",
        recruiter_email="optout@agency.com",
        role="Java Developer",
        post_url="https://linkedin.com/1",
        job_description="Java job",
    )
    assert success is False
    assert reason == "recruiter_suppressed"

    # 2. Add recruiter to sent history (de-dup test)
    store.record_sent_email({
        "recruiter_name": "Contacted",
        "recruiter_email": "already@agency.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/2",
        "candidate": sample_candidate.name,
        "email_sent_status": "sent",
        "timestamp": "2026-10-24 10:00:00",
        "subject": "Sub",
        "message_id": "<1@g>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })

    success_dedup, reason_dedup = sender.send_outreach_email(
        candidate=sample_candidate,
        recruiter_name="Contacted",
        recruiter_email="already@agency.com",
        role="Java Developer",
        post_url="https://linkedin.com/2",
        job_description="Java job",
    )
    assert success_dedup is False
    assert reason_dedup == "already_contacted"


@patch.object(GmailSender, "_send_smtp")
def test_gmail_sender_test_mode_redirection(
    mock_send, tmp_path: Path, sample_candidate: CandidateProfile
):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    store.save_recruiter({
        "recruiter_name": "Recruiter One",
        "recruiter_email": "target@agency.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/post/999",
        "job_description": "Need Java developer with AWS",
        "email_sent_status": "pending",
        "timestamp": "2026-10-24 10:00:00",
    })

    sender = GmailSender(csv_store=store, inter_email_delay=0.0)
    sender.gmail_email = "mybot@gmail.com"
    sender.app_password = "secret_password"
    sender.operator_email = "operator@corp.com"
    sender.test_mode = True  # Enable test mode

    success, msg_id = sender.send_outreach_email(
        candidate=sample_candidate,
        recruiter_name="Recruiter One",
        recruiter_email="target@agency.com",
        role="Java Developer",
        post_url="https://linkedin.com/post/999",
        job_description="Need Java developer with AWS",
    )

    assert success is True
    assert msg_id.startswith("<")
    assert mock_send.called

    sent_msg, actual_recipients = mock_send.call_args[0]
    # Verify redirected exclusively to operator in Test mode
    assert actual_recipients == ["operator@corp.com"]
    assert "[TEST MODE - Intended for: target@agency.com]" in sent_msg["Subject"]

    # Verify history recorded and recruiter status updated to 'sent'
    history = store.get_history()
    assert len(history) == 1
    assert history[0]["candidate"] == sample_candidate.name
    assert history[0]["recruiter_email"] == "target@agency.com"
    assert history[0]["email_sent_status"] == "sent"

    # Status updated in recruiters.csv
    recs = store.get_all_recruiters()
    assert recs[0]["email_sent_status"] == "sent"
