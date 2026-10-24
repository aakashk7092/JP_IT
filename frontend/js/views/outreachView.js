/**
 * Outreach View - Targeted Gmail SMTP Engine & Mandatory Safety Gate
 */

import { API } from '../api.js';
import { store } from '../store.js';
import { openSafetyBarrierModal, showToast } from '../notifications.js';

let selectedEmails = new Set();

export async function renderOutreach(container) {
  const { testMode } = store.getState();
  const cand = store.getActiveCandidate();

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>Phase 4: Targeted Gmail SMTP Outreach</h2>
        <p>Personalized opening hooks, rate-limited delivery, and strict human safety confirmation</p>
      </div>
      <div style="display:flex; align-items:center; gap:12px;">
        <button id="toggle-mode-btn" class="btn btn-secondary">
          ${testMode ? 'Switch to LIVE OUTREACH' : 'Switch to Safe TEST MODE'}
        </button>
        <button id="dispatch-outreach-btn" class="btn ${testMode ? 'btn-primary' : 'btn-danger'}">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"></path></svg>
          ${testMode ? 'Send in TEST MODE (Safe)' : 'DISPATCH LIVE OUTREACH'}
        </button>
      </div>
    </div>

    <!-- Operating Mode Warning Banner -->
    <div class="glass-panel" style="padding:16px 20px; margin-bottom:20px; display:flex; align-items:center; justify-content:space-between; ${testMode ? 'border-color:var(--color-warning);' : 'border-color:var(--color-danger); box-shadow:0 0 25px rgba(239,68,68,0.2);'}">
      <div style="display:flex; align-items:center; gap:14px;">
        <div style="width:36px; height:36px; border-radius:8px; background:${testMode ? 'var(--color-warning-bg)' : 'var(--color-danger-bg)'}; display:flex; align-items:center; justify-content:center; color:${testMode ? 'var(--color-warning)' : 'var(--color-danger)'}; font-size:18px;">
          ${testMode ? '⚠️' : '🚨'}
        </div>
        <div>
          <div style="font-weight:700; color:#ffffff; font-size:14px;">
            ${testMode ? 'SAFE TEST MODE ACTIVE' : 'LIVE PRODUCTION OUTREACH ACTIVE'}
          </div>
          <div style="font-size:12px; color:var(--text-muted);">
            ${testMode 
              ? 'All outreach emails will be safely redirected to the operator address. Recruiter inboxes will NOT be contacted.' 
              : 'REAL EMAILS will be dispatched to actual recruiter addresses via Gmail SMTP. Requires typing "SEND" to authorize.'}
          </div>
        </div>
      </div>
      <span class="badge ${testMode ? 'badge-pending' : 'badge-failed'}">
        ${testMode ? 'TEST MODE' : 'LIVE PRODUCTION'}
      </span>
    </div>

    <!-- Outreach Queue Table -->
    <div class="table-container">
      <div class="table-toolbar">
        <div style="display:flex; align-items:center; gap:12px;">
          <input type="checkbox" id="select-all-checkbox" checked />
          <span style="font-size:13px; font-weight:600; color:#ffffff;">Pending Outreach Queue</span>
          <span id="selected-count-label" style="font-size:12px; color:var(--text-dim);">(0 selected)</span>
        </div>
        <span style="font-size:12px; color:var(--text-dim);">Candidate: <strong>${cand ? cand.name : '-'}</strong></span>
      </div>

      <div id="outreach-table-body-container">
        <div style="text-align:center; padding:36px; color:var(--text-dim);">Loading pending outreach...</div>
      </div>
    </div>
  `;

  // Attach mode toggle listener
  container.querySelector('#toggle-mode-btn')?.addEventListener('click', async () => {
    const newMode = !testMode;
    try {
      await API.setTestMode(newMode);
      store.setState({ testMode: newMode });
      showToast(`Switched to ${newMode ? 'TEST MODE (Safe)' : 'LIVE OUTREACH'}`, newMode ? 'info' : 'error');
      renderOutreach(container);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  // Attach dispatch button listener
  container.querySelector('#dispatch-outreach-btn')?.addEventListener('click', () => {
    if (!cand) return showToast('No candidate selected', 'error');
    const emailsList = Array.from(selectedEmails);
    if (emailsList.length === 0) return showToast('No recruiters selected for dispatch', 'error');

    if (!testMode) {
      // LIVE OUTREACH - Open Safety Barrier Modal
      openSafetyBarrierModal({
        title: 'LIVE EMAIL DISPATCH AUTHORIZATION',
        message: `You are in <strong>LIVE OUTREACH</strong> mode. Real emails with attached resumes will be sent to <strong>${emailsList.length}</strong> recruiters. Type <code>SEND</code> below to authorize.`,
        targetCount: emailsList.length,
        requiredToken: 'SEND',
        onConfirm: async () => {
          try {
            const res = await API.sendOutreach(cand.id, 'SEND', emailsList);
            showToast(res.message, 'success');
            store.setState({ isDrawerExpanded: true });
            loadOutreachQueue(container);
          } catch (e) {
            showToast(e.message, 'error');
          }
        },
      });
    } else {
      // TEST MODE - Safe dispatch
      (async () => {
        try {
          const res = await API.sendOutreach(cand.id, null, emailsList);
          showToast(res.message, 'info');
          store.setState({ isDrawerExpanded: true });
          loadOutreachQueue(container);
        } catch (e) {
          showToast(e.message, 'error');
        }
      })();
    }
  });

  await loadOutreachQueue(container);
}

async function loadOutreachQueue(container) {
  const tableContainer = container.querySelector('#outreach-table-body-container');
  const countLabel = container.querySelector('#selected-count-label');
  const selectAll = container.querySelector('#select-all-checkbox');
  const cand = store.getActiveCandidate();

  if (!tableContainer) return;

  try {
    const res = await API.getPendingOutreach(cand ? cand.id : null);
    const pending = res.pending || [];
    selectedEmails = new Set(pending.map(p => p.recruiter_email));

    if (countLabel) countLabel.textContent = `(${selectedEmails.size} selected)`;

    if (pending.length === 0) {
      tableContainer.innerHTML = `
        <div style="text-align:center; padding:40px; color:var(--text-dim);">
          No pending recruiters to contact. Scrape fresh postings in Phase 2 or check history.
        </div>
      `;
      return;
    }

    tableContainer.innerHTML = `
      <table class="custom-table">
        <thead>
          <tr>
            <th style="width:36px;"></th>
            <th>Recruiter Name</th>
            <th>Email</th>
            <th>Target Role</th>
            <th>JD Excerpt</th>
            <th>Scraped Date</th>
          </tr>
        </thead>
        <tbody>
          ${pending.map(p => `
            <tr>
              <td>
                <input type="checkbox" class="rec-checkbox" data-email="${escapeHtml(p.recruiter_email)}" checked />
              </td>
              <td style="font-weight:600; color:#ffffff;">${escapeHtml(p.recruiter_name || 'Hiring Manager')}</td>
              <td><span style="color:#38bdf8;">${escapeHtml(p.recruiter_email)}</span></td>
              <td><span style="color:var(--text-highlight);">${escapeHtml(p.role)}</span></td>
              <td style="font-size:11px; color:var(--text-muted); max-width:300px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">
                ${escapeHtml(p.job_description_snippet || '-')}
              </td>
              <td style="color:var(--text-dim); font-size:11px;">${escapeHtml(p.timestamp || '-')}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    `;

    // Row checkbox toggles
    tableContainer.querySelectorAll('.rec-checkbox').forEach(cb => {
      cb.addEventListener('change', (e) => {
        const email = e.target.getAttribute('data-email');
        if (e.target.checked) {
          selectedEmails.add(email);
        } else {
          selectedEmails.delete(email);
        }
        if (countLabel) countLabel.textContent = `(${selectedEmails.size} selected)`;
      });
    });

    // Select all toggle
    selectAll?.addEventListener('change', (e) => {
      const checked = e.target.checked;
      tableContainer.querySelectorAll('.rec-checkbox').forEach(cb => {
        cb.checked = checked;
        const email = cb.getAttribute('data-email');
        if (checked) selectedEmails.add(email);
        else selectedEmails.delete(email);
      });
      if (countLabel) countLabel.textContent = `(${selectedEmails.size} selected)`;
    });

  } catch (e) {
    tableContainer.innerHTML = `<div style="text-align:center; padding:24px; color:var(--color-danger);">Failed loading outreach queue: ${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
