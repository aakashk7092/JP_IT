import { API } from '../api.js';
import { store } from '../store.js';
import { openSessionRequiredModal, showToast } from '../notifications.js';

let currentFilter = '';
let currentSearch = '';
let currentPage = 1;

export async function renderScraper(container) {
  const { systemStatus } = store.getState();
  const cand = store.getActiveCandidate();
  const hasSession = systemStatus?.credentials?.session_active;

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>Phase 2: LinkedIn Hiring Post Scraper</h2>
        <p>Captures USA C2C hiring posts, parses recruiter emails, and enforces anti-bench spam filters</p>
      </div>
      <div style="display:flex; gap:10px;">
        <button id="scraper-demo-btn" class="btn btn-secondary" title="Load sample verified US C2C postings without live LinkedIn login">
          ⚡ Load Sandbox Leads
        </button>
        <button id="scraper-login-btn" class="btn btn-secondary">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 16l-4-4m0 0l4-4m-4 4h14m-5 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h7a3 3 0 013 3v1"></path></svg>
          ${hasSession ? 'Re-Authenticate Session' : 'Setup LinkedIn Login'}
        </button>
        <button id="scraper-run-btn" class="btn btn-primary">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z"></path></svg>
          Run Scraper
        </button>
      </div>
    </div>

    <!-- Scraper Setup Box -->
    <div class="scraper-control-box">
      <div style="display:flex; justify-content:space-between; align-items:center;">
        <div style="display:flex; align-items:center; gap:10px;">
          <span class="badge ${hasSession ? 'badge-sent' : 'badge-failed'}">
            ${hasSession ? '● LinkedIn Session Ready' : '○ Missing session.json'}
          </span>
          <span style="font-size:12px; color:var(--text-dim);">
            Target Candidate: <strong style="color:#ffffff;">${cand ? cand.name : 'None'}</strong> (${cand ? cand.primary_role : ''})
          </span>
        </div>
        <div style="display:flex; gap:12px; align-items:center;">
          <label style="font-size:12px; color:var(--text-dim); display:flex; align-items:center; gap:6px;">
            <input type="checkbox" id="scrape-headless" checked /> Headless Browser
          </label>
          <label style="font-size:12px; color:var(--text-dim); display:flex; align-items:center; gap:6px;">
            Max Posts:
            <input type="number" id="scrape-limit" value="20" min="5" max="100" style="width:55px; background:rgba(0,0,0,0.3); border:1px solid var(--border-card); color:#fff; border-radius:4px; padding:2px 6px;" />
          </label>
        </div>
      </div>

      <div>
        <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--text-dim); margin-bottom:4px;">
          Constructed LinkedIn Boolean Search Query (Past 24h, geoUrn=103644278):
        </div>
        <div class="scraper-query-preview">
          "${cand ? cand.primary_role : 'Software Engineer'} + C2C -hotlist -fulltime -\\"available consultants\\" -Bench"
        </div>
      </div>
    </div>

    <!-- Recruiter Leads Table -->
    <div class="table-container">
      <div class="table-toolbar">
        <div style="display:flex; gap:8px;">
          <button class="btn btn-sm filter-btn ${currentFilter === '' ? 'btn-primary' : 'btn-secondary'}" data-filter="">All</button>
          <button class="btn btn-sm filter-btn ${currentFilter === 'pending' ? 'btn-primary' : 'btn-secondary'}" data-filter="pending">Pending</button>
          <button class="btn btn-sm filter-btn ${currentFilter === 'sent' ? 'btn-primary' : 'btn-secondary'}" data-filter="sent">Sent</button>
          <button class="btn btn-sm filter-btn ${currentFilter === 'mismatched_role' ? 'btn-primary' : 'btn-secondary'}" data-filter="mismatched_role">Mismatched</button>
          <button class="btn btn-sm filter-btn ${currentFilter === 'failed' ? 'btn-primary' : 'btn-secondary'}" data-filter="failed">Failed</button>
        </div>
        <input type="text" id="leads-search-input" class="search-input" placeholder="Search recruiter, email, or role..." value="${escapeHtml(currentSearch)}" />
      </div>

      <div id="leads-table-body-container">
        <div style="text-align:center; padding:30px; color:var(--text-dim);">Loading recruiter data...</div>
      </div>
    </div>
  `;

  // Attach controls
  container.querySelector('#scraper-demo-btn')?.addEventListener('click', async () => {
    try {
      const res = await API.createDemoSession();
      showToast(res.message, 'success');
      const newStatus = await API.getStatus();
      store.setState({ systemStatus: newStatus });
      renderScraper(container);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  container.querySelector('#scraper-login-btn')?.addEventListener('click', async () => {
    try {
      const res = await API.loginLinkedIn(300);
      showToast(res.message, 'info');
      store.setState({ isDrawerExpanded: true });
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  container.querySelector('#scraper-run-btn')?.addEventListener('click', async () => {
    const headless = container.querySelector('#scrape-headless')?.checked ?? true;
    const limit = parseInt(container.querySelector('#scrape-limit')?.value || '20', 10);

    const executeScrape = async () => {
      try {
        const res = await API.runScraper(cand ? cand.id : null, headless, limit);
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
            executeScrape();
          } catch (e) {
            showToast(e.message, 'error');
          }
        },
      });
    } else {
      executeScrape();
    }
  });

  container.querySelectorAll('.filter-btn').forEach(b => {
    b.addEventListener('click', (e) => {
      currentFilter = e.currentTarget.getAttribute('data-filter') || '';
      currentPage = 1;
      renderScraper(container);
    });
  });

  const searchInp = container.querySelector('#leads-search-input');
  searchInp?.addEventListener('input', (e) => {
    currentSearch = e.target.value;
    currentPage = 1;
    loadTableData(container);
  });

  await loadTableData(container);
}

async function loadTableData(container) {
  const tableContainer = container.querySelector('#leads-table-body-container');
  if (!tableContainer) return;

  try {
    const res = await API.getRecruiters(currentFilter, currentSearch, currentPage, 25);
    const rows = res.recruiters || [];

    if (rows.length === 0) {
      tableContainer.innerHTML = `
        <div style="text-align:center; padding:36px; color:var(--text-dim);">
          No recruiters found matching the criteria. Click "Run Scraper" to harvest fresh leads.
        </div>
      `;
      return;
    }

    tableContainer.innerHTML = `
      <table class="custom-table">
        <thead>
          <tr>
            <th>Recruiter</th>
            <th>Email</th>
            <th>Role</th>
            <th>Post URL</th>
            <th>Status</th>
            <th>Scraped Date</th>
          </tr>
        </thead>
        <tbody>
          ${rows.map(r => `
            <tr>
              <td style="font-weight:600; color:#ffffff;">${escapeHtml(r.recruiter_name || 'Hiring Manager')}</td>
              <td><span style="color:#38bdf8;">${escapeHtml(r.recruiter_email || '-')}</span></td>
              <td><span style="color:var(--text-highlight);">${escapeHtml(r.role || '-')}</span></td>
              <td>
                ${r.post_url ? `<a href="${escapeHtml(r.post_url)}" target="_blank" rel="noopener noreferrer" style="color:var(--cyan-primary); text-decoration:none; font-size:12px;">View Post ↗</a>` : '-'}
              </td>
              <td>
                <span class="badge ${r.email_sent_status === 'sent' ? 'badge-sent' : r.email_sent_status === 'pending' ? 'badge-pending' : r.email_sent_status === 'mismatched_role' ? 'badge-mismatched' : 'badge-failed'}">
                  ${escapeHtml(r.email_sent_status)}
                </span>
              </td>
              <td style="color:var(--text-dim); font-size:11px;">${escapeHtml(r.timestamp || '-')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
      <div style="padding:12px 18px; display:flex; justify-content:space-between; align-items:center; font-size:12px; color:var(--text-dim);">
        <span>Showing ${rows.length} of ${res.total} recruiters</span>
        <div style="display:flex; gap:6px;">
          <button class="btn btn-secondary btn-sm" id="prev-page-btn" ${currentPage <= 1 ? 'disabled' : ''}>Previous</button>
          <span style="padding:4px 8px;">Page ${currentPage}</span>
          <button class="btn btn-secondary btn-sm" id="next-page-btn" ${rows.length < 25 ? 'disabled' : ''}>Next</button>
        </div>
      </div>
    `;

    container.querySelector('#prev-page-btn')?.addEventListener('click', () => {
      if (currentPage > 1) {
        currentPage--;
        loadTableData(container);
      }
    });

    container.querySelector('#next-page-btn')?.addEventListener('click', () => {
      currentPage++;
      loadTableData(container);
    });

  } catch (e) {
    tableContainer.innerHTML = `<div style="text-align:center; padding:24px; color:var(--color-danger);">Failed to load leads: ${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
