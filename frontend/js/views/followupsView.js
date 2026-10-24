/**
 * Follow-ups & IMAP Sync View - Reply Tracking & Suppression List Manager
 */

import { API } from '../api.js';
import { store } from '../store.js';
import { showToast } from '../notifications.js';

let activeSubTab = 'followups'; // 'followups', 'history', 'suppression'

export async function renderFollowups(container) {
  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>Phase 5: IMAP Reply Detection & Threaded Follow-ups</h2>
        <p>Monitors Gmail INBOX read-only, suppresses STOP replies, and manages RFC-threaded follow-ups</p>
      </div>
      <div style="display:flex; gap:10px;">
        <button id="trigger-imap-sync-btn" class="btn btn-secondary">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"></path></svg>
          Sync IMAP Replies
        </button>
        <button id="trigger-followups-btn" class="btn btn-primary">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
          Process 7-Day Follow-ups
        </button>
      </div>
    </div>

    <!-- Sub-navigation Tabs -->
    <div style="display:flex; gap:8px; margin-bottom:16px;">
      <button class="btn btn-sm sub-tab-btn ${activeSubTab === 'followups' ? 'btn-primary' : 'btn-secondary'}" data-tab="followups">
        Eligible Follow-ups (≥ 7 Days)
      </button>
      <button class="btn btn-sm sub-tab-btn ${activeSubTab === 'history' ? 'btn-primary' : 'btn-secondary'}" data-tab="history">
        Sent Outreach Audit Log
      </button>
      <button class="btn btn-sm sub-tab-btn ${activeSubTab === 'suppression' ? 'btn-primary' : 'btn-secondary'}" data-tab="suppression">
        Suppression Registry (Opt-Outs)
      </button>
    </div>

    <div id="subtab-content-container">
      <div style="text-align:center; padding:36px; color:var(--text-dim);">Loading data...</div>
    </div>
  `;

  // Attach button triggers
  container.querySelector('#trigger-imap-sync-btn')?.addEventListener('click', async () => {
    try {
      const res = await API.syncIMAP();
      showToast(res.message, 'info');
      store.setState({ isDrawerExpanded: true });
      loadSubTabContent(container);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  container.querySelector('#trigger-followups-btn')?.addEventListener('click', async () => {
    try {
      const res = await API.sendFollowups(7);
      showToast(res.message, 'info');
      store.setState({ isDrawerExpanded: true });
      loadSubTabContent(container);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  container.querySelectorAll('.sub-tab-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      activeSubTab = e.currentTarget.getAttribute('data-tab');
      renderFollowups(container);
    });
  });

  await loadSubTabContent(container);
}

async function loadSubTabContent(container) {
  const content = container.querySelector('#subtab-content-container');
  if (!content) return;

  if (activeSubTab === 'followups') {
    try {
      const eligible = await API.getEligibleFollowups(7);
      if (eligible.length === 0) {
        content.innerHTML = `
          <div class="table-container" style="padding:40px; text-align:center; color:var(--text-dim);">
            No outreach emails currently eligible for follow-up (must be unreplied, unsuppressed, and sent ≥ 7 days ago).
          </div>
        `;
        return;
      }

      content.innerHTML = `
        <div class="table-container">
          <div class="table-toolbar">
            <h4 style="font-size:13px; font-weight:600; color:#fff;">Eligible for Threaded Follow-up (${eligible.length})</h4>
          </div>
          <table class="custom-table">
            <thead>
              <tr>
                <th>Recruiter</th>
                <th>Email</th>
                <th>Candidate</th>
                <th>Original Sent Date</th>
                <th>Message-ID</th>
              </tr>
            </thead>
            <tbody>
              ${eligible.map(e => `
                <tr>
                  <td style="font-weight:600; color:#fff;">${escapeHtml(e.recruiter_name)}</td>
                  <td><span style="color:#38bdf8;">${escapeHtml(e.recruiter_email)}</span></td>
                  <td>${escapeHtml(e.candidate)}</td>
                  <td style="color:var(--text-dim); font-size:12px;">${escapeHtml(e.timestamp)}</td>
                  <td style="font-family:var(--font-mono); font-size:11px; color:var(--text-muted);">${escapeHtml(e.message_id)}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    } catch (e) {
      content.innerHTML = `<div style="color:var(--color-danger); padding:24px;">Failed loading follow-ups: ${escapeHtml(e.message)}</div>`;
    }

  } else if (activeSubTab === 'history') {
    try {
      const res = await API.getHistory('', false, 1, 50);
      const rows = res.history || [];

      content.innerHTML = `
        <div class="table-container">
          <div class="table-toolbar">
            <h4 style="font-size:13px; font-weight:600; color:#fff;">Sent History Log (${res.total})</h4>
          </div>
          <table class="custom-table">
            <thead>
              <tr>
                <th>Recruiter</th>
                <th>Email</th>
                <th>Candidate</th>
                <th>Sent Date</th>
                <th>Follow-up #</th>
                <th>Replied?</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(h => `
                <tr>
                  <td style="font-weight:600; color:#fff;">${escapeHtml(h.recruiter_name)}</td>
                  <td><span style="color:#38bdf8;">${escapeHtml(h.recruiter_email)}</span></td>
                  <td>${escapeHtml(h.candidate)}</td>
                  <td style="color:var(--text-dim); font-size:12px;">${escapeHtml(h.timestamp)}</td>
                  <td><span class="badge ${h.followup_count > 0 ? 'badge-sent' : 'badge-mismatched'}">${h.followup_count || 0}</span></td>
                  <td>
                    <span class="badge ${h.replied == '1' ? 'badge-replied' : 'badge-pending'}">
                      ${h.replied == '1' ? '✓ REPLIED' : 'PENDING'}
                    </span>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    } catch (e) {
      content.innerHTML = `<div style="color:var(--color-danger); padding:24px;">Failed loading history: ${escapeHtml(e.message)}</div>`;
    }

  } else if (activeSubTab === 'suppression') {
    try {
      const list = await API.getSuppressionList();

      content.innerHTML = `
        <div class="table-container">
          <div class="table-toolbar">
            <h4 style="font-size:13px; font-weight:600; color:#fff;">Suppressed Email Addresses (${list.length})</h4>
            <div style="display:flex; gap:8px;">
              <input type="email" id="suppress-add-input" class="search-input" placeholder="recruiter@agency.com" style="width:220px;" />
              <button id="suppress-add-btn" class="btn btn-primary btn-sm">Add Opt-Out</button>
            </div>
          </div>
          <table class="custom-table">
            <thead>
              <tr>
                <th>Suppressed Email</th>
                <th>Reason</th>
                <th>Date Added</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              ${list.length > 0 ? list.map(s => `
                <tr>
                  <td style="font-weight:600; color:#f87171;">${escapeHtml(s.recruiter_email || s.email)}</td>
                  <td style="color:var(--text-muted); font-size:12px;">${escapeHtml(s.reason || 'Auto-suppressed via STOP')}</td>
                  <td style="color:var(--text-dim); font-size:11px;">${escapeHtml(s.timestamp || '-')}</td>
                  <td>
                    <button class="btn btn-secondary btn-sm remove-suppress-btn" data-email="${escapeHtml(s.recruiter_email || s.email)}">
                      Remove
                    </button>
                  </td>
                </tr>
              `).join('') : `
                <tr><td colspan="4" style="text-align:center; padding:24px; color:var(--text-dim);">No suppressed contacts in registry.</td></tr>
              `}
            </tbody>
          </table>
        </div>
      `;

      content.querySelector('#suppress-add-btn')?.addEventListener('click', async () => {
        const inp = content.querySelector('#suppress-add-input');
        const email = inp?.value.trim();
        if (!email) return;
        try {
          await API.addSuppression(email, 'Manual operator addition');
          showToast(`Suppressed ${email}`, 'info');
          loadSubTabContent(container);
        } catch (e) {
          showToast(e.message, 'error');
        }
      });

      content.querySelectorAll('.remove-suppress-btn').forEach(btn => {
        btn.addEventListener('click', async (e) => {
          const email = e.currentTarget.getAttribute('data-email');
          try {
            await API.removeSuppression(email);
            showToast(`Removed ${email} from suppression`, 'info');
            loadSubTabContent(container);
          } catch (e) {
            showToast(e.message, 'error');
          }
        });
      });

    } catch (e) {
      content.innerHTML = `<div style="color:var(--color-danger); padding:24px;">Failed loading suppression list: ${escapeHtml(e.message)}</div>`;
    }
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
