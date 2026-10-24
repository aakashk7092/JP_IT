You are a senior Python engineer. Build the "Recruitment & Outreach Automation System" in this workspace, exactly as described in README.md (read it fully first; it is the source of truth for architecture, schemas and flows).

## Goal
A CLI pipeline that, for registered client candidates, (1) scrapes LinkedIn hiring posts for C2C roles in the USA, (2) filters spam, (3) tailors the candidate's resume to each job description using an LLM, (4) sends personalized emails via Gmail SMTP, (5) sends threaded follow-ups, (6) syncs replies via IMAP, (7) exports an analytics HTML dashboard.

## Tech stack
Python 3.10+, Windows. playwright, pandas, python-dotenv, beautifulsoup4, rich, pypdf, python-docx, pdf2docx, docx2pdf, requests. Flat CSV storage (recruiters.csv, email_sent_history.csv) with automatic header migration at runtime.

## Working method (follow strictly)
1. First produce an implementation plan and a task list. Wait for my approval before writing code.
2. Build in the phases below. After each phase: run the tests for that phase, show me the results, and stop for my review.
3. Never hardcode secrets. Read everything from .env via python-dotenv. Create .env.example and .gitignore (.env, session.json, *.csv, clients/, scratch/).
4. Use type hints, docstrings, the `logging` module (file + rich console), and clear error handling. No silent exceptions.
5. Every module must be importable without side effects and have unit tests (pytest) with external services mocked.

## Phases

### Phase 1: Foundation
- Project structure: main.py, client_config.py, lock_util.py, csv_store.py (shared read/write + header migration + atomic writes using a temp file and rename), requirements.txt, .env.example, README stub, tests/.
- client_config.py: CLIENTS, CANDIDATE_ROLES (primary_role, search_roles, exclusion_keywords), C2C exclusion lists, resume_candidates paths. Include one dummy example candidate.
- lock_util.py: file-based mutex (context manager) with timeout and stale-lock detection, used to serialize Word COM calls.
- Schemas:
  - recruiters.csv: recruiter_name, recruiter_email, role, post_url, job_description, email_sent_status (pending|sent|failed|mismatched_role), timestamp.
  - email_sent_history.csv: recruiter_name, recruiter_email, role, post_url, candidate, email_sent_status, timestamp, subject, message_id, followup_count, last_followup_at, replied.
- Tests: header migration, atomic write, lock behavior.

### Phase 2: LinkedIn login and scraper
- linkedin_login.py: headful Playwright login, wait for home feed (global nav element), save cookies/localStorage to session.json. Operator completes CAPTCHA/2FA manually.
- linkedin_scraper.py (headless, loads session.json):
  - Query: "<Role> + C2C -hotlist -fulltime -\"available consultants\" -Bench"; filters last 24h, sorted by date, geoUrn=103644278; scroll 6 times; click "See more".
  - Post link capture: scroll card to center, click button[aria-label*='control menu for post'], click "Copy link", read clipboard via navigator.clipboard, strip query params. Put ALL selectors in one SELECTORS dict at the top so they are easy to fix when LinkedIn changes the UI.
  - Email extraction: mailto links first, then regex [a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}.
  - Filters: matches_strict_filter and is_usa_job. Reject NON_USA_INDICATORS (Pune, Noida, India, Canada, etc.), accept US cities/state abbreviations/explicit US terms; reject bench-marketing phrases ("on my bench", "candidate available", "marketing my consultant"); reject domain mismatch (DevOps, QA, Salesforce, etc.) vs the candidate's target roles, recording mismatched_role.
  - Skip recruiters already contacted by this candidate (check history).
  - Add randomized human-like delays and a conservative per-run post cap.
- Tests: filters, email regex, URL cleaning (use saved HTML fixtures, no live LinkedIn calls).

### Phase 3: Resume customizer
- resume_customizer.py:
  - If source is PDF, convert to DOCX with pdf2docx.
  - Extract professional summary, project experience (until next section divider like EDUCATION), technical skills (table or bullets).
  - LLM call returns strict JSON: rewritten_summary, rewritten_paragraphs, rewritten_skills. Provider chain: Gemini (primary) -> Groq -> OpenRouter, configurable via .env, with retries and JSON validation.
  - Style-preserving rewrite run by run (keep font, size, bold/italic/underline, color, paragraph styles); normalize alignment, section boundaries, blank lines.
  - Convert DOCX to PDF using docx2pdf inside the lock_util mutex; kill hung winword.exe on timeout. Put the converter behind an interface so a LibreOffice converter can be swapped in later.
- TRUTHFULNESS GUARD (mandatory): the prompt must instruct the LLM to only emphasize technologies and experience already present in the original resume, never invent employers, titles, dates, certifications or technologies. After generation, run a validator that diffs technologies/skills in the output against the original resume and the JD; any technology that is in neither the original resume nor clearly equivalent is flagged. Save the original-vs-tailored diff to scratch/ for review. If the validator fails, fall back to the original resume.
- Per-client customizer hook: dispatcher in gmail_sender.customize_resume() routes to safi_customizer.py / tanuja_customizer.py style modules when they exist (create one template stub showing the interface: takes template path + JD + candidate, returns PDF path).
- Tests: structure extraction on sample DOCX, JSON validation, style preservation, validator.

### Phase 4: Email sender
- gmail_sender.py:
  - JD_KEYWORDS list (60+ technologies); pick top 3 matches in the JD, build a hook like "My hands-on experience with Java, Spring Boot, and PostgreSQL maps directly to what you are looking for..."; only use keywords that are also in the candidate's resume.
  - SMTP: smtp.gmail.com:587 STARTTLS, fallback to 465 SSL, app password from .env.
  - De-duplicate on (candidate, recruiter_email) against history before sending.
  - 3 second delay between emails, global daily limit, and a Test mode that logs/sends only to the operator instead of recruiters.
  - MIME: attach PDF as CandidateName_Resume_<unix_ts>.pdf; sanitize non-ASCII filenames; To recruiter, CC candidate and team lead, BCC admin.
  - Include a plain opt-out line in every email ("Reply STOP to opt out") and honor a suppression_list.csv: any recruiter who replies STOP/unsubscribe or is listed is never emailed or followed up again.
  - Record Message-ID and write history rows; update recruiters.csv status.
- Tests: hook builder, de-dup, MIME building, suppression list (mock smtplib).

### Phase 5: Follow-ups and reply sync
- followup_sender.py: eligible rows = status sent, followup_count 0, replied 0, sent exactly X days ago (default 7, configurable), not suppressed. Headers In-Reply-To and References = original Message-ID, subject "Re: <original>". 1-2 sentence AI value proposition (OpenRouter, fallback Groq), re-attach resume, same CC/BCC, then update followup_count and last_followup_at. Always run reply sync before follow-ups.
- imap_reply_detector.py: imap.gmail.com:993 SSL, INBOX read-only, SINCE DD-Mon-YYYY from the oldest unreplied sent email (default 30 days), fetch headers in batches of 100, parse with email.message_from_bytes, set replied=1 for matching senders, add STOP/unsubscribe replies to suppression_list.csv.
- Tests with mocked imaplib/smtplib.

### Phase 6: Orchestrator and analytics
- main.py: rich-based interactive menu. Option 2 = Setup/Test LinkedIn Login Session. Option 8 = Run Full Pipeline for ALL Candidates (batch mode: ask Test/Live and global daily limit, init LinkedIn session once, loop candidates: validate config and resume, scrape, load DB, filter already contacted, customize, send, log). Add single-candidate run, follow-ups, check replies, analytics and a setup validation screen.
- Before any Live send: show the operator a table of pending recruiters, show the resume diff report path, and require typing SEND.
- analytics.py: statistics (totals by status, reply rate, follow-up counts, volume per candidate/role) and export a premium dark-themed analytics_report.html (self-contained, no external assets).

## Definition of done
- `pytest` passes with no network access.
- `python main.py` runs, validates setup, and every menu option works in Test mode end to end using fixtures.
- README.md updated with real run instructions; .env.example complete.
- No secrets in code or git history.

Start now with the implementation plan and task list only. Do not write code until I approve.
