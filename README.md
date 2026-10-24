# Recruitment & Outreach Automation System

An enterprise-grade Python CLI pipeline designed to automate C2C recruitment outreach for registered client candidates across the United States.

---

## 🎯 Core Capabilities
1. **LinkedIn Hiring Scraper**: Queries C2C hiring posts (`past-24h`, US `geoUrn=103644278`, anti-bench and spam exclusion booleans), expands post content, captures clean canonical post links, and extracts recruiter emails (`mailto:` first, regex fallback).
2. **Strict Spam & Geo Filters**: Filters non-USA postings (Pune, Noida, India, Canada, etc.), eliminates bench-marketing and consultant availability hotlists, and flags domain mismatches (DevOps, QA, Salesforce, etc.) as `mismatched_role`.
3. **Resume Tailoring with Truthfulness Guard**:
   - Converts PDF/DOCX resumes.
   - Tailors summary, skills, and project experience to the JD via multi-provider LLM chain: **Gemini (primary) ➔ Groq (fallback 1) ➔ OpenRouter (fallback 2)**.
   - **Mandatory Truthfulness Guard**: Enforces strict grounding—never hallucinating employers, dates, or non-existent technologies. Automatically diffs output against the original resume and falls back to original resume if ungrounded skills are detected. Saves visual diffs to `scratch/`.
   - Preserves run-by-run Word DOCX formatting (fonts, sizes, bold, italic, colors).
   - Pluggable conversion interface with serialized Word COM file-based mutex (`lock_util.py`) and hung `winword.exe` watchdog.
4. **Targeted Gmail SMTP Outreach**:
   - Matches candidate skills against 60+ curated technologies in the JD to craft personalized opening hooks.
   - Dual-strategy SMTP: Port 587 (STARTTLS) with automatic fallback to Port 465 (SSL).
   - De-duplicates by `(candidate, recruiter_email)` against history.
   - Rate-limited with 3-second inter-email delay and global daily quota.
   - **Safe Test Mode**: Redirects all emails to the operator with safe debug headers.
   - Opt-out footer (`"Reply STOP to opt out"`) and suppression list enforcement.
5. **Threaded Follow-ups & IMAP Sync**:
   - Detects recruiter replies via read-only IMAP INBOX scans.
   - Automatically adds recruiters who reply `STOP` or `UNSUBSCRIBE` to `suppression_list.csv`.
   - Dispatches threaded 7-day follow-ups (`In-Reply-To` and `References` headers) with a concise AI value hook and re-attached resume.
6. **Analytics & Dark Theme Dashboard**:
   - Computes funnel metrics (sent, replies, reply rate %, follow-ups, role/candidate breakdown).
   - Generates a standalone, dark-themed HTML report (`analytics_report.html`, zero external dependencies).

---

## 📁 Repository Structure
```text
├── main.py                     # Interactive Rich CLI menu and batch orchestrator
├── client_config.py            # Candidate profiles, target roles, and spam filters
├── csv_store.py                # Flat CSV storage with atomic writes & schema migrations
├── lock_util.py                # File-based mutex with stale-lock watchdog for Word COM
├── linkedin_login.py           # Headful Playwright 2FA/CAPTCHA session authenticator
├── linkedin_scraper.py         # Headless post scraper with strict geo & bench filters
├── llm_client.py               # Multi-provider LLM fallback chain (Gemini/Groq/OpenRouter)
├── resume_customizer.py        # Style-preserving rewriter, Truthfulness Guard, & PDF converter
├── gmail_sender.py             # SMTP outreach engine with tech hooks & MIME generation
├── followup_sender.py          # Threaded follow-up engine with conversation headers
├── imap_reply_detector.py      # IMAP read-only reply scanner and auto-suppression
├── analytics.py                # Metrics calculator and standalone dark HTML dashboard
├── clients/
│   ├── resumes/                # Candidate original resumes (.docx / .pdf)
│   └── customizers/            # Per-client customizer hooks (e.g. stub_customizer.py)
├── tests/                      # 50 unit tests covering all phases (100% offline)
├── .env.example                # Configuration template for credentials and options
└── requirements.txt            # Pinned project dependencies
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites & Virtual Environment
Python 3.10+ on Windows:
```bash
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Environment Configuration
Copy `.env.example` to `.env` and fill in your credentials:
```bash
cp .env.example .env
```

Key variables in `.env`:
- `GEMINI_API_KEY`: Google Gemini API Key (primary LLM).
- `GROQ_API_KEY`: Groq API Key (fallback 1).
- `OPENROUTER_API_KEY`: OpenRouter API Key (fallback 2).
- `GMAIL_EMAIL`: Your Gmail address.
- `GMAIL_APP_PASSWORD`: 16-character Google App Password (with 2FA enabled on Gmail).
- `OPERATOR_EMAIL`: Your email address to receive redirected emails during Test Mode.
- `TEST_MODE`: `true` (safe mode) or `false` (live sending to recruiters).
- `GLOBAL_DAILY_LIMIT`: Maximum emails sent per day (e.g. 50).
- `FOLLOWUP_DAYS`: Minimum days to wait before follow-up (default: 7).

### 3. Setup LinkedIn Session
Run Option 2 in the menu or directly invoke:
```bash
python linkedin_login.py
```
A browser will open. Log in to your LinkedIn account, solve any 2FA/CAPTCHA challenge, and wait until your home feed loads. The cookies and localStorage state will be safely serialized to `session.json`.

---

## 💻 Interactive CLI Menu

Start the application:
```bash
python main.py
```

Menu options:
- `1. Setup & Environment Validation`: Displays a Rich status table verifying API keys, credentials, session state, and candidate profiles.
- `2. Setup/Test LinkedIn Session`: Launches headful browser to capture `session.json`.
- `3. Scrape LinkedIn C2C Jobs`: Scrapes US C2C postings for selected candidate's target roles and saves qualified recruiters to `recruiters.csv`.
- `4. Tailor Resumes for Pending Jobs`: Extracts JD, rewrites summary and experience, validates against Truthfulness Guard, and produces tailored PDF resumes.
- `5. Send Outreach Emails`: Dispatches outreach emails. **Safety check**: In Live mode, requires the operator to review pending recruiters and type `SEND` before any email is dispatched.
- `6. Sync IMAP Recruiter Replies`: Connects to Gmail IMAP in read-only mode to detect responses and auto-suppress `STOP` requests.
- `7. Process Threaded Follow-ups`: Runs reply sync first, then sends threaded follow-ups for emails sent >= 7 days ago.
- `8. Run Full Pipeline for ALL Candidates (Batch Mode)`:
  - Prompts for Test/Live mode and daily email limit.
  - Initializes session once.
  - Loops over each registered candidate in `client_config.py`.
  - Validates resumes, scrapes LinkedIn, filters candidates, tailors resumes with Truthfulness Guard, dispatches emails, syncs replies, and generates an updated analytics dashboard.
- `9. Export Analytics Dashboard`: Calculates metrics and exports `analytics_report.html`.
- `0. Exit`: Exits the application.

---

## 🧪 Testing

All unit tests run completely offline with external services (LinkedIn, Gmail SMTP, Gmail IMAP, LLM providers) fully mocked:
```bash
pytest tests/ -v
```

All 50 unit tests pass in ~4.8 seconds:
```text
============================= 50 passed in 4.79s ==============================
```
