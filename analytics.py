"""Analytics and metrics engine for the Recruitment & Outreach Automation System.

Computes outreach statistics, reply rates, conversion funnels, and exports
a premium, self-contained dark-themed HTML report (zero external dependencies).
"""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from csv_store import CSVStore

logger = logging.getLogger("recruitment_automation.analytics")


@dataclass
class AnalyticsSummary:
    """Consolidated outreach metrics and funnel statistics."""
    total_recruiters: int
    pending_recruiters: int
    sent_outreach: int
    failed_outreach: int
    mismatched_roles: int
    total_replies: int
    reply_rate_pct: float
    followups_sent: int
    total_suppressed: int
    candidate_stats: dict[str, dict[str, int]]
    role_stats: dict[str, int]


def calculate_metrics(csv_store: Optional[CSVStore] = None) -> AnalyticsSummary:
    """Compute aggregated analytics from recruiters, history, and suppression CSVs."""
    store = csv_store or CSVStore()

    recruiters = store.get_all_recruiters()
    history = store.get_history()
    suppression_list = store.get_suppression_list()

    total_recruiters = len(recruiters)
    pending_count = sum(1 for r in recruiters if r.get("email_sent_status") == "pending")
    mismatched_count = sum(1 for r in recruiters if r.get("email_sent_status") == "mismatched_role")

    sent_count = 0
    failed_count = 0
    replied_count = 0
    followup_count = 0
    candidate_stats: dict[str, dict[str, int]] = {}
    role_stats: dict[str, int] = {}

    for h in history:
        cand = h.get("candidate", "Unknown Candidate").strip()
        role = h.get("role", "General Role").strip()
        status = h.get("email_sent_status", "").lower()
        replied = str(h.get("replied", "0")) == "1"
        is_followup = int(h.get("followup_count", "0") or "0") > 0

        # Update candidate breakdown
        if cand not in candidate_stats:
            candidate_stats[cand] = {"sent": 0, "replied": 0, "followups": 0}

        if status == "sent":
            sent_count += 1
            candidate_stats[cand]["sent"] += 1
        elif status == "failed":
            failed_count += 1

        if replied:
            replied_count += 1
            candidate_stats[cand]["replied"] += 1

        if is_followup:
            followup_count += 1
            candidate_stats[cand]["followups"] += 1

        role_stats[role] = role_stats.get(role, 0) + 1

    reply_rate = (replied_count / sent_count * 100) if sent_count > 0 else 0.0

    return AnalyticsSummary(
        total_recruiters=total_recruiters,
        pending_recruiters=pending_count,
        sent_outreach=sent_count,
        failed_outreach=failed_count,
        mismatched_roles=mismatched_count,
        total_replies=replied_count,
        reply_rate_pct=round(reply_rate, 1),
        followups_sent=followup_count,
        total_suppressed=len(suppression_list),
        candidate_stats=candidate_stats,
        role_stats=role_stats,
    )


def generate_dark_html_report(
    summary: AnalyticsSummary,
    output_path: str | Path = "analytics_report.html",
) -> Path:
    """Generate a self-contained, standalone dark-themed HTML analytics dashboard."""
    out_file = Path(output_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # Generate Candidate rows
    candidate_rows_html = ""
    for cand, stats in summary.candidate_stats.items():
        sent = stats["sent"]
        replies = stats["replied"]
        rate = round((replies / sent * 100), 1) if sent > 0 else 0.0
        candidate_rows_html += f"""
        <tr>
            <td style="font-weight: 600;">{html.escape(cand)}</td>
            <td><span class="badge blue">{sent}</span></td>
            <td><span class="badge emerald">{replies}</span></td>
            <td><span class="badge purple">{stats['followups']}</span></td>
            <td><span class="rate-pill">{rate}%</span></td>
        </tr>
        """

    if not candidate_rows_html:
        candidate_rows_html = '<tr><td colspan="5" style="text-align: center; color: #64748b;">No candidate outreach recorded yet.</td></tr>'

    # Generate Role breakdown list
    role_bars_html = ""
    max_role_val = max(summary.role_stats.values()) if summary.role_stats else 1
    for role_name, count in summary.role_stats.items():
        pct = int((count / max_role_val) * 100)
        role_bars_html += f"""
        <div class="role-bar-item">
            <div class="role-label-row">
                <span>{html.escape(role_name)}</span>
                <span class="badge blue">{count} posts</span>
            </div>
            <div class="progress-track">
                <div class="progress-fill" style="width: {pct}%;"></div>
            </div>
        </div>
        """

    if not role_bars_html:
        role_bars_html = '<div style="color: #64748b; font-size: 0.9rem;">No role statistics recorded yet.</div>'

    html_template = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Recruitment & Outreach Analytics</title>
    <style>
        :root {{
            --bg-base: #090d16;
            --bg-card: #131b2e;
            --bg-card-hover: #1c2742;
            --border: #23304e;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --cyan: #06b6d4;
            --cyan-glow: rgba(6, 182, 212, 0.2);
            --emerald: #10b981;
            --emerald-glow: rgba(16, 185, 129, 0.2);
            --purple: #8b5cf6;
            --amber: #f59e0b;
            --rose: #f43f5e;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        body {{
            background-color: var(--bg-base);
            color: var(--text-primary);
            padding: 32px 24px;
            min-height: 100vh;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 24px;
            margin-bottom: 32px;
        }}
        .brand-title {{
            font-size: 1.75rem;
            font-weight: 700;
            letter-spacing: -0.025em;
            background: linear-gradient(135deg, #38bdf8, #818cf8);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }}
        .brand-subtitle {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-top: 4px;
        }}
        .tag {{
            display: inline-flex;
            align-items: center;
            padding: 4px 12px;
            border-radius: 9999px;
            font-size: 0.8rem;
            font-weight: 500;
            background: rgba(6, 182, 212, 0.1);
            color: var(--cyan);
            border: 1px solid rgba(6, 182, 212, 0.3);
        }}
        .grid-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
            gap: 20px;
            margin-bottom: 36px;
        }}
        .card {{
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 22px;
            transition: transform 0.2s, box-shadow 0.2s;
        }}
        .card:hover {{
            transform: translateY(-2px);
            border-color: #3b82f6;
            box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
        }}
        .card-label {{
            font-size: 0.82rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            margin-bottom: 8px;
        }}
        .card-value {{
            font-size: 2.1rem;
            font-weight: 700;
            line-height: 1.1;
        }}
        .color-cyan {{ color: var(--cyan); }}
        .color-emerald {{ color: var(--emerald); }}
        .color-purple {{ color: var(--purple); }}
        .color-amber {{ color: var(--amber); }}
        .color-rose {{ color: var(--rose); }}

        .layout-two-col {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 24px;
        }}
        @media (max-width: 900px) {{
            .layout-two-col {{
                grid-template-columns: 1fr;
            }}
        }}
        .section-box {{
            background-color: var(--bg-card);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 24px;
        }}
        .section-title {{
            font-size: 1.15rem;
            font-weight: 600;
            margin-bottom: 18px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th {{
            font-size: 0.78rem;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary);
            padding: 12px 14px;
            border-bottom: 1px solid var(--border);
        }}
        td {{
            padding: 14px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.04);
            font-size: 0.9rem;
        }}
        tr:last-child td {{
            border-bottom: none;
        }}
        .badge {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 6px;
            font-size: 0.78rem;
            font-weight: 600;
        }}
        .badge.blue {{ background: rgba(56, 189, 248, 0.15); color: #38bdf8; }}
        .badge.emerald {{ background: rgba(16, 185, 129, 0.15); color: #34d399; }}
        .badge.purple {{ background: rgba(139, 92, 246, 0.15); color: #a78bfa; }}
        .rate-pill {{
            font-weight: 700;
            color: #38bdf8;
        }}
        .role-bar-item {{
            margin-bottom: 18px;
        }}
        .role-label-row {{
            display: flex;
            justify-content: space-between;
            font-size: 0.88rem;
            margin-bottom: 6px;
        }}
        .progress-track {{
            width: 100%;
            height: 8px;
            background: #1e293b;
            border-radius: 9999px;
            overflow: hidden;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #38bdf8, #818cf8);
            border-radius: 9999px;
        }}
        footer {{
            margin-top: 48px;
            text-align: center;
            font-size: 0.8rem;
            color: #475569;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <div>
                <h1 class="brand-title">Recruitment & Outreach Analytics</h1>
                <p class="brand-subtitle">USA C2C Automation & Candidate Pipeline Performance Dashboard</p>
            </div>
            <div class="tag">Live Pipeline Metrics</div>
        </header>

        <!-- Top Metric Cards -->
        <div class="grid-cards">
            <div class="card">
                <div class="card-label">Total Recruiters Scraped</div>
                <div class="card-value color-cyan">{summary.total_recruiters}</div>
            </div>
            <div class="card">
                <div class="card-label">Outreach Emails Sent</div>
                <div class="card-value color-emerald">{summary.sent_outreach}</div>
            </div>
            <div class="card">
                <div class="card-label">Recruiter Replies</div>
                <div class="card-value color-purple">{summary.total_replies}</div>
            </div>
            <div class="card">
                <div class="card-label">Overall Reply Rate</div>
                <div class="card-value color-cyan">{summary.reply_rate_pct}%</div>
            </div>
            <div class="card">
                <div class="card-label">Threaded Follow-ups</div>
                <div class="card-value color-amber">{summary.followups_sent}</div>
            </div>
            <div class="card">
                <div class="card-label">Suppressed / Opt-out</div>
                <div class="card-value color-rose">{summary.total_suppressed}</div>
            </div>
        </div>

        <!-- Two Column Detailed Breakdown -->
        <div class="layout-two-col">
            <!-- Candidate Performance Table -->
            <div class="section-box">
                <div class="section-title">
                    <span>Candidate Outreach Volume</span>
                    <span class="badge blue">By Profile</span>
                </div>
                <table>
                    <thead>
                        <tr>
                            <th>Candidate</th>
                            <th>Sent</th>
                            <th>Replies</th>
                            <th>Follow-ups</th>
                            <th>Reply Rate</th>
                        </tr>
                    </thead>
                    <tbody>
                        {candidate_rows_html}
                    </tbody>
                </table>
            </div>

            <!-- Target Roles & Domain Distribution -->
            <div class="section-box">
                <div class="section-title">
                    <span>Role Distribution</span>
                    <span class="badge purple">Target Roles</span>
                </div>
                <div style="margin-top: 14px;">
                    {role_bars_html}
                </div>
                <div style="margin-top: 24px; padding-top: 18px; border-top: 1px solid var(--border); font-size: 0.85rem; color: var(--text-secondary);">
                    <div>Pending Outreach: <strong style="color: var(--text-primary);">{summary.pending_recruiters}</strong></div>
                    <div style="margin-top: 4px;">Domain Mismatches Filtered: <strong style="color: var(--amber);">{summary.mismatched_roles}</strong></div>
                    <div style="margin-top: 4px;">Failed Dispatches: <strong style="color: var(--rose);">{summary.failed_outreach}</strong></div>
                </div>
            </div>
        </div>

        <footer>
            Recruitment & Outreach Automation System • Standalone Dashboard • Generated Offline
        </footer>
    </div>
</body>
</html>
"""
    out_file.write_text(html_template, encoding="utf-8")
    logger.info("Successfully exported dark analytics report to %s", out_file)
    return out_file
