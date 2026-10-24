import { API } from '../api.js';
import { store } from '../store.js';
import { openSessionRequiredModal, showToast } from '../notifications.js';

export function renderDashboard(container) {
  const { metrics, systemStatus, testMode, jobs } = store.getState();
  const cand = store.getActiveCandidate();
  const hasSession = systemStatus?.credentials?.session_active;

  const totalRecruiters = metrics?.total_recruiters ?? (systemStatus?.stats?.total_recruiters ?? 0);
  const pendingRecruiters = metrics?.pending_recruiters ?? (systemStatus?.stats?.pending_recruiters ?? 0);
  const sentOutreach = metrics?.sent_outreach ?? (systemStatus?.stats?.sent_outreach ?? 0);
  const totalReplies = metrics?.total_replies ?? 0;
  const replyRate = metrics?.reply_rate_pct ?? 0.0;
  const followupsSent = metrics?.followups_sent ?? 0;

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>Executive Dashboard</h2>
        <p>Real-time C2C recruitment outreach analytics and automated pipeline controls</p>
      </div>
      <div style="display:flex; gap:10px;">
        <button id="dash-quick-batch" class="btn btn-primary">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
          Run Full Pipeline (Batch)
        </button>
      </div>
    </div>

    <!-- KPI Grid -->
    <div class="metrics-grid">
      <div class="kpi-card">
        <div class="kpi-label">Scraped Leads</div>
        <div class="kpi-value">${totalRecruiters}</div>
        <div class="kpi-sub">Total verified C2C postings</div>
      </div>
      <div class="kpi-card amber">
        <div class="kpi-label">Pending Outreach</div>
        <div class="kpi-value">${pendingRecruiters}</div>
        <div class="kpi-sub">Awaiting tailored resume & email</div>
      </div>
      <div class="kpi-card green">
        <div class="kpi-label">Sent Cold Emails</div>
        <div class="kpi-value">${sentOutreach}</div>
        <div class="kpi-sub">Targeted Gmail outreach dispatched</div>
      </div>
      <div class="kpi-card purple">
        <div class="kpi-label">Recruiter Replies</div>
        <div class="kpi-value">${totalReplies}</div>
        <div class="kpi-sub">Detected via Gmail IMAP scan</div>
      </div>
      <div class="kpi-card">
        <div class="kpi-label">Reply Rate</div>
        <div class="kpi-value">${replyRate}%</div>
        <div class="kpi-sub">Conversation conversion rate</div>
      </div>
      <div class="kpi-card green">
        <div class="kpi-label">Threaded Follow-ups</div>
        <div class="kpi-value">${followupsSent}</div>
        <div class="kpi-sub">7-day In-Reply-To dispatches</div>
      </div>
    </div>

    <!-- Pipeline Phase Launcher Cards -->
    <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap:16px; margin-bottom:24px;">
      <div class="glass-panel" style="padding:20px;">
        <h4 style="font-size:14px; color:#ffffff; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
          <span style="color:var(--cyan-primary);">Phase 2:</span> LinkedIn Scraper
        </h4>
        <p style="font-size:12px; color:var(--text-muted); margin-bottom:14px;">
          Scrape US C2C roles for <strong>${cand ? cand.name : 'Candidate'}</strong> with strict geo and anti-bench filters.
        </p>
        <button id="dash-run-scraper" class="btn btn-secondary btn-sm" style="width:100%;">Launch Scraper</button>
      </div>

      <div class="glass-panel" style="padding:20px;">
        <h4 style="font-size:14px; color:#ffffff; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
          <span style="color:var(--cyan-primary);">Phase 3:</span> Resume Tailoring
        </h4>
        <p style="font-size:12px; color:var(--text-muted); margin-bottom:14px;">
          AI customization with the Truthfulness Guard and run-by-run Word style preservation.
        </p>
        <button id="dash-run-tailor" class="btn btn-secondary btn-sm" style="width:100%;">Tailor Pending Resumes</button>
      </div>

      <div class="glass-panel" style="padding:20px;">
        <h4 style="font-size:14px; color:#ffffff; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
          <span style="color:var(--cyan-primary);">Phase 4:</span> Gmail Outreach
        </h4>
        <p style="font-size:12px; color:var(--text-muted); margin-bottom:14px;">
          Personalized tech hooks and tailored PDF attachments (${testMode ? '<span style="color:var(--color-warning);">TEST MODE</span>' : '<span style="color:var(--color-danger);">LIVE MODE</span>'}).
        </p>
        <button id="dash-run-outreach" class="btn btn-secondary btn-sm" style="width:100%;">Review & Send Outreach</button>
      </div>

      <div class="glass-panel" style="padding:20px;">
        <h4 style="font-size:14px; color:#ffffff; margin-bottom:8px; display:flex; align-items:center; gap:8px;">
          <span style="color:var(--cyan-primary);">Phase 5:</span> IMAP Reply Sync
        </h4>
        <p style="font-size:12px; color:var(--text-muted); margin-bottom:14px;">
          Scan Gmail INBOX read-only to flag responses and auto-suppress STOP requests.
        </p>
        <button id="dash-run-imap" class="btn btn-secondary btn-sm" style="width:100%;">Sync IMAP Replies</button>
      </div>
    </div>

    <!-- Active / Recent Jobs Table -->
    <div class="table-container">
      <div class="table-toolbar">
        <h3 style="font-size:14px; font-weight:600; color:#ffffff;">Recent Automation Tasks</h3>
        <span style="font-size:12px; color:var(--text-dim);">${jobs ? jobs.length : 0} tasks tracked</span>
      </div>
      <table class="custom-table">
        <thead>
          <tr>
            <th>Task Name</th>
            <th>Started At</th>
            <th>Status</th>
            <th>Details / Result</th>
          </tr>
        </thead>
        <tbody>
          ${jobs && jobs.length > 0 ? jobs.slice(0, 8).map(j => `
            <tr>
              <td style="font-weight:600; color:#ffffff;">${escapeHtml(j.name)}</td>
              <td style="color:var(--text-dim); font-size:12px;">${j.started_at}</td>
              <td>
                <span class="badge ${j.status === 'completed' ? 'badge-sent' : j.status === 'running' ? 'badge-pending' : 'badge-failed'}">
                  ${j.status}
                </span>
              </td>
              <td style="font-size:12px; color:var(--text-muted);">
                ${j.error ? `<span style="color:var(--color-danger);">${escapeHtml(j.error)}</span>` : (j.result ? JSON.stringify(j.result) : (j.logs && j.logs.length ? escapeHtml(j.logs[j.logs.length - 1]) : '-'))}
              </td>
            </tr>
          `).join('') : `
            <tr>
              <td colspan="4" style="text-align:center; color:var(--text-dim); padding:24px;">No background tasks executed yet.</td>
            </tr>
          `}
        </tbody>
      </table>
    </div>
  `;

  // Attach quick action listeners
  container.querySelector('#dash-quick-batch')?.addEventListener('click', async () => {
    const launch = async () => {
      try {
        const res = await API.runBatchPipeline(testMode, 50);
        showToast(res.message, 'info');
        store.setState({ isDrawerExpanded: true });
      } catch (e) {
        showToast(e.message, 'error');
      }
    };

    if (!hasSession) {
      openSessionRequiredModal({
        onLaunchLogin: async () => {
          try {
            const res = await API.loginLinkedIn(300);
            showToast(res.message, 'info');
            store.setState({ isDrawerExpanded: true });
          } catch (e) {
            showToast(e.message, 'error');
          }
        },
        onDemoSession: async () => {
          try {
            const res = await API.createDemoSession();
            showToast(res.message, 'success');
            const newStatus = await API.getStatus();
            store.setState({ systemStatus: newStatus });
            launch();
          } catch (e) {
            showToast(e.message, 'error');
          }
        },
      });
    } else {
      launch();
    }
  });

  container.querySelector('#dash-run-scraper')?.addEventListener('click', async () => {
    const runScrape = async () => {
      try {
        const res = await API.runScraper(cand ? cand.id : null);
        showToast(res.message, 'info');
        store.setState({ isDrawerExpanded: true });
      } catch (e) {
        showToast(e.message, 'error');
      }
    };

    if (!hasSession) {
      openSessionRequiredModal({
        onLaunchLogin: async () => {
          try {
            const res = await API.loginLinkedIn(300);
            showToast(res.message, 'info');
            store.setState({ isDrawerExpanded: true });
          } catch (e) {
            showToast(e.message, 'error');
          }
        },
        onDemoSession: async () => {
          try {
            const res = await API.createDemoSession();
            showToast(res.message, 'success');
            const newStatus = await API.getStatus();
            store.setState({ systemStatus: newStatus });
            runScrape();
          } catch (e) {
            showToast(e.message, 'error');
          }
        },
      });
    } else {
      runScrape();
    }
  });

  container.querySelector('#dash-run-tailor')?.addEventListener('click', async () => {
    if (!cand) return showToast('No candidate selected', 'error');
    try {
      const res = await API.tailorResume(cand.id);
      showToast(res.message, 'info');
      store.setState({ isDrawerExpanded: true });
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  container.querySelector('#dash-run-outreach')?.addEventListener('click', () => {
    store.setState({ activeTab: 'outreach' });
  });

  container.querySelector('#dash-run-imap')?.addEventListener('click', async () => {
    try {
      const res = await API.syncIMAP();
      showToast(res.message, 'info');
      store.setState({ isDrawerExpanded: true });
    } catch (e) {
      showToast(e.message, 'error');
    }
  });
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
