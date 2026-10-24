"""Unit tests for followup_sender.py and imap_reply_detector.py with mocked IMAP and SMTP."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from client_config import CandidateProfile
from csv_store import CSVStore
from followup_sender import FollowupSender, generate_followup_value_prop
from gmail_sender import GmailSender
from imap_reply_detector import IMAPReplyDetector, extract_sender_email, is_opt_out_reply


@pytest.fixture
def test_candidate(tmp_path: Path) -> CandidateProfile:
    resume = tmp_path / "alex_resume.docx"
    resume.write_text("Resume Content", encoding="utf-8")
    return CandidateProfile(
        id="alex_test",
        name="Alex Johnson",
        email="alex@test.com",
        primary_role="Java Full Stack Developer",
        experience_years=8,
        resume_path=str(resume),
        skills=["Java", "Spring Boot", "PostgreSQL", "AWS"],
    )


def test_is_opt_out_reply_detection():
    assert is_opt_out_reply("Please STOP sending me emails.") is True
    assert is_opt_out_reply("Unsubscribe me from your consultant list.") is True
    assert is_opt_out_reply("Take me off your list.") is True
    assert is_opt_out_reply("We are not interested at this time.") is True
    assert is_opt_out_reply("Yes, please share the candidate's hourly rate and availability.") is False


def test_extract_sender_email():
    assert extract_sender_email("Sarah Connor <sarah@apex.com>") == "sarah@apex.com"
    assert extract_sender_email("john.recruiter@agency.org") == "john.recruiter@agency.org"
    assert extract_sender_email("") == ""


def test_followup_eligibility(tmp_path: Path):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    now = datetime.datetime.now()
    old_date = (now - datetime.timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S")
    recent_date = (now - datetime.timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")

    # 1. Eligible record (sent 8 days ago, unreplied, followup 0)
    store.record_sent_email({
        "recruiter_name": "Eligible Recruiter",
        "recruiter_email": "eligible@corp.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/1",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": old_date,
        "subject": "Alex Johnson - Java Developer",
        "message_id": "<orig-123@gmail.com>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })

    # 2. Ineligible: sent only 2 days ago
    store.record_sent_email({
        "recruiter_name": "Too Recent",
        "recruiter_email": "recent@corp.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/2",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": recent_date,
        "subject": "Recent Subject",
        "message_id": "<orig-456@gmail.com>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })

    # 3. Ineligible: already replied
    store.record_sent_email({
        "recruiter_name": "Replied Recruiter",
        "recruiter_email": "replied@corp.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/3",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": old_date,
        "subject": "Replied Subject",
        "message_id": "<orig-789@gmail.com>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "1",
    })

    # 4. Ineligible: already followed up
    store.record_sent_email({
        "recruiter_name": "Followed Up Recruiter",
        "recruiter_email": "followed@corp.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/4",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": old_date,
        "subject": "Followed Subject",
        "message_id": "<orig-101@gmail.com>",
        "followup_count": "1",
        "last_followup_at": old_date,
        "replied": "0",
    })

    sender = FollowupSender(csv_store=store)
    eligible = sender.find_eligible_followups(days_threshold=7)

    assert len(eligible) == 1
    assert eligible[0]["recruiter_email"] == "eligible@corp.com"


@patch.object(GmailSender, "_send_smtp")
def test_send_followup_threading_headers(
    mock_send, tmp_path: Path, test_candidate: CandidateProfile
):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    old_date = (datetime.datetime.now() - datetime.timedelta(days=9)).strftime("%Y-%m-%d %H:%M:%S")
    record = {
        "recruiter_name": "Dave Miller",
        "recruiter_email": "dave@recruitment.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/p/123",
        "candidate": test_candidate.name,
        "email_sent_status": "sent",
        "timestamp": old_date,
        "subject": "Alex Johnson - Java Full Stack Developer",
        "message_id": "<orig-msg-guid-12345@gmail.com>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    }
    store.record_sent_email(record)
    mock_llm = MagicMock()
    mock_llm.openrouter_key = ""
    mock_llm.groq_key = ""
    mock_llm.gemini_key = ""
    sender = FollowupSender(csv_store=store, llm_client=mock_llm)
    sender.gmail_sender.test_mode = False

    success, msg_id = sender.send_followup_for_record(record, test_candidate)
    assert success is True
    assert mock_send.called

    sent_msg, actual_recipients = mock_send.call_args[0]
    # Threading assertions
    assert sent_msg["Subject"] == "Re: Alex Johnson - Java Full Stack Developer"
    assert sent_msg["In-Reply-To"] == "<orig-msg-guid-12345@gmail.com>"
    assert sent_msg["References"] == "<orig-msg-guid-12345@gmail.com>"
    assert "dave@recruitment.com" in actual_recipients

    # Verify history updated
    history = store.get_history()
    assert history[0]["followup_count"] == "1"
    assert history[0]["last_followup_at"] != ""


def test_imap_sync_mock(tmp_path: Path):
    store = CSVStore(
        recruiters_path=tmp_path / "recruiters.csv",
        history_path=tmp_path / "history.csv",
        suppression_path=tmp_path / "suppress.csv",
    )

    # 1. Recruiter who replied normally
    store.record_sent_email({
        "recruiter_name": "Recruiter One",
        "recruiter_email": "r1@agency.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/1",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": "2026-10-15 10:00:00",
        "subject": "Alex Java",
        "message_id": "<m1@g>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })

    # 2. Recruiter who replied STOP
    store.record_sent_email({
        "recruiter_name": "Recruiter Two",
        "recruiter_email": "r2@agency.com",
        "role": "Java Developer",
        "post_url": "https://linkedin.com/2",
        "candidate": "Alex Johnson",
        "email_sent_status": "sent",
        "timestamp": "2026-10-15 10:00:00",
        "subject": "Alex Java",
        "message_id": "<m2@g>",
        "followup_count": "0",
        "last_followup_at": "",
        "replied": "0",
    })

    detector = IMAPReplyDetector(csv_store=store)

    # Construct mock email messages
    msg1_raw = (
        b"From: Recruiter One <r1@agency.com>\r\n"
        b"Subject: Re: Alex Java\r\n"
        b"\r\n"
        b"Hi Alex, send over your rate and right to represent.\r\n"
    )
    msg2_raw = (
        b"From: Recruiter Two <r2@agency.com>\r\n"
        b"Subject: Re: Alex Java\r\n"
        b"\r\n"
        b"STOP. Unsubscribe me please.\r\n"
    )

    mock_mail = MagicMock()
    mock_mail.search.return_value = ("OK", [b"1 2"])
    mock_mail.fetch.return_value = (
        "OK",
        [
            (b"1 (BODY.PEEK[HEADER] {100}", msg1_raw),
            b")",
            (b"2 (BODY.PEEK[HEADER] {100}", msg2_raw),
            b")",
        ],
    )

    with patch.object(detector, "_connect_imap", return_value=mock_mail):
        res = detector.sync_replies()

    assert res["replied_count"] == 2
    assert res["suppressed_count"] == 1

    # Check updated history
    history = store.get_history()
    assert history[0]["replied"] == "1"
    assert history[1]["replied"] == "1"

    # Check suppression list
    assert store.is_suppressed("r2@agency.com")
    assert not store.is_suppressed("r1@agency.com")
