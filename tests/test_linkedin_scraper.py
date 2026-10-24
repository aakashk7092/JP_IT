"""Unit tests for linkedin_scraper.py verifying URL sanitization, filters, and offline HTML parsing."""

import pytest

from client_config import RoleDefinition
from linkedin_scraper import (
    build_search_query,
    build_search_url,
    check_domain_match,
    clean_post_url,
    extract_all_emails,
    extract_emails_from_text,
    extract_mailto_emails,
    is_usa_job,
    matches_strict_filter,
    parse_post_card,
)

# Sample HTML fixture representing a typical LinkedIn feed card
SAMPLE_POST_CARD_HTML = """
<div class="feed-shared-update-v2" data-urn="urn:li:activity:7123456789012345678">
    <div class="update-components-actor">
        <span class="update-components-actor__name">Sarah Connor</span>
        <span class="update-components-actor__description">Senior Technical Recruiter at Apex Systems</span>
    </div>
    <div class="feed-shared-update-v2__description">
        <p>
            🚀 Urgent C2C Requirement!
            Looking for a Senior Java Full Stack Developer with AWS and Microservices experience.
            Location: Remote - US (Candidates located in Dallas, TX or anywhere in USA welcome).
            Rate: Open on C2C.
            Please share resume directly to: <a href="mailto:sarah.connor@apexsystems.com?subject=Java%20Role">sarah.connor@apexsystems.com</a>
            or email sarah.backup@apexsystems.com!
        </p>
    </div>
    <a href="https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678/?trackingId=xyz123&utm_source=share">Permalink</a>
</div>
"""

BENCH_POST_CARD_HTML = """
<div class="feed-shared-update-v2">
    <div class="update-components-actor">
        <span class="update-components-actor__name">Raj Patel</span>
    </div>
    <div class="feed-shared-update-v2__description">
        <p>
            Hotlist: We have excellent consultants available on our bench for immediate C2C projects!
            1. Java Developer - 9 yrs
            2. DevOps Engineer - 8 yrs
            Contact: bench@consulting.com
        </p>
    </div>
</div>
"""


def test_clean_post_url():
    raw_url = "https://www.linkedin.com/feed/update/urn:li:activity:7123456789/?trackingId=abc%3D%3D&context=feed&utm_source=li"
    cleaned = clean_post_url(raw_url)
    assert cleaned == "https://www.linkedin.com/feed/update/urn:li:activity:7123456789"

    # Handle trailing slashes and empty string
    assert clean_post_url("") == ""
    assert clean_post_url("https://www.linkedin.com/posts/xyz/") == "https://www.linkedin.com/posts/xyz"


def test_extract_emails_from_text():
    text = (
        "Drop resumes to john.doe@techstaffing.com or reach out to "
        "jane_smith123@agency.org. Ignore image banner@2x.png and test@example.com."
    )
    emails = extract_emails_from_text(text)
    assert "john.doe@techstaffing.com" in emails
    assert "jane_smith123@agency.org" in emails
    assert "banner@2x.png" not in emails
    assert "test@example.com" not in emails


def test_extract_mailto_emails():
    html = """
    <div>
        Contact me: <a href="mailto:recruiter1@agency.com?subject=Job">Click here</a>
        and <a href="MAILTO:recruiter2@agency.com">Email 2</a>
        <a href="https://google.com">Google</a>
    </div>
    """
    emails = extract_mailto_emails(html)
    assert emails == ["recruiter1@agency.com", "recruiter2@agency.com"]


def test_extract_all_emails_priority():
    text = "Send to regex@corp.com and mailto@corp.com"
    html = '<a href="mailto:mailto@corp.com">Mail</a>'
    emails = extract_all_emails(text, html)
    # Mailto email should be first in order
    assert emails[0] == "mailto@corp.com"
    assert emails[1] == "regex@corp.com"
    assert len(emails) == 2


def test_is_usa_job_detection():
    # Valid USA jobs
    assert is_usa_job("Role: Java Developer | Location: Dallas, TX | C2C contract") is True
    assert is_usa_job("Looking for Remote - US Java engineer on C2C") is True
    assert is_usa_job("Client in New York, NY requires AWS Backend Developer") is True
    assert is_usa_job("Remote C2C role for candidates across USA") is True

    # Non-USA rejections
    assert is_usa_job("Looking for Java Lead in Pune, India on C2C basis") is False
    assert is_usa_job("Urgent requirement in Noida / Gurgaon") is False
    assert is_usa_job("Position based in Toronto, Canada") is False
    assert is_usa_job("Location: Bangalore") is False


def test_matches_strict_filter_anti_bench():
    # Legitimate requirement
    valid_text = "Urgent C2C opening for Java Full Stack Developer. Contract role for 12 months."
    is_valid, reason = matches_strict_filter(valid_text)
    assert is_valid is True
    assert reason == "valid"

    # Bench marketing rejected
    bench_text_1 = "I have immediate available consultants on my bench for C2C projects."
    is_valid_1, reason_1 = matches_strict_filter(bench_text_1)
    assert is_valid_1 is False
    assert "bench_marketing" in reason_1

    bench_text_2 = "Hotlist of candidates available. Please share C2C requirements."
    is_valid_2, reason_2 = matches_strict_filter(bench_text_2)
    assert is_valid_2 is False

    # Non-contract / missing C2C
    fulltime_text = "Hiring Fulltime W2 software engineer at Google."
    is_valid_3, reason_3 = matches_strict_filter(fulltime_text)
    assert is_valid_3 is False
    assert reason_3 == "missing_c2c_indicator"


def test_check_domain_match():
    role_def = RoleDefinition(
        primary_role="Java Full Stack Developer",
        search_roles=["Java Developer", "Java Full Stack Developer"],
        exclusion_keywords=["devops", "qa", "salesforce", "ios", "android"],
    )

    # Good match
    assert check_domain_match("Senior Java Developer with Spring Boot and AWS", role_def)[0] is True

    # Domain mismatch (DevOps role with no Java)
    mismatch_devops = check_domain_match("Urgent C2C DevOps Engineer with Kubernetes and Terraform", role_def)
    assert mismatch_devops[0] is False
    assert "mismatched_role" in mismatch_devops[1]

    # Domain mismatch (Salesforce role with no Java)
    mismatch_sf = check_domain_match("Salesforce Developer needed on C2C for CRM migration", role_def)
    assert mismatch_sf[0] is False


def test_build_search_query_and_url():
    query = build_search_query("Java Full Stack Developer")
    assert '"Java Full Stack Developer"' in query
    assert "+ C2C" in query
    assert "-hotlist" in query
    assert '-"available consultants"' in query

    url = build_search_url(query)
    assert "geoUrn=103644278" in url
    assert "datePosted=%22past-24h%22" in url
    assert "sortBy=%22date_posted%22" in url


def test_parse_post_card_offline_fixture():
    parsed = parse_post_card(SAMPLE_POST_CARD_HTML)
    assert parsed is not None
    assert parsed["recruiter_name"] == "Sarah Connor"
    assert parsed["recruiter_email"] == "sarah.connor@apexsystems.com"
    assert "sarah.backup@apexsystems.com" in parsed["all_emails"]
    assert "Senior Java Full Stack Developer" in parsed["job_description"]
    assert parsed["post_url"] == "https://www.linkedin.com/feed/update/urn:li:activity:7123456789012345678"


def test_parse_post_card_bench_fixture():
    parsed = parse_post_card(BENCH_POST_CARD_HTML)
    assert parsed is not None
    assert parsed["recruiter_name"] == "Raj Patel"
    assert parsed["recruiter_email"] == "bench@consulting.com"

    # Feed into strict filter to ensure bench is detected
    is_valid, _ = matches_strict_filter(parsed["job_description"])
    assert is_valid is False
