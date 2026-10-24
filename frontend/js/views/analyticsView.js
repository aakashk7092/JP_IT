/**
 * Analytics View - Visual Funnel Conversion, Candidate Performance & HTML Report Export
 */

import { API } from '../api.js';
import { store } from '../store.js';

export async function renderAnalytics(container) {
  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>Phase 6: Campaign Analytics & Reporting</h2>
        <p>Funnel metrics, reply conversion percentages, and role distribution</p>
      </div>
      <div style="display:flex; gap:10px;">
        <a href="/api/analytics/report" target="_blank" class="btn btn-secondary">
          <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"></path></svg>
          Open Standalone Dark Report ↗
        </a>
      </div>
    </div>

    <div id="analytics-content-container">
      <div style="text-align:center; padding:36px; color:var(--text-dim);">Calculating analytics...</div>
    </div>
  `;

  await loadAnalytics(container);
}

async function loadAnalytics(container) {
  const content = container.querySelector('#analytics-content-container');
  if (!content) return;

  try {
    const data = await API.getMetrics();
    const candStats = data.candidate_stats || {};
    const roleStats = data.role_stats || {};

    const scraped = data.total_recruiters || 0;
    const sent = data.sent_outreach || 0;
    const replies = data.total_replies || 0;
    const followups = data.followups_sent || 0;

    const sentPct = scraped > 0 ? Math.min(100, Math.round((sent / scraped) * 100)) : 0;
    const replyPct = data.reply_rate_pct || 0.0;

    content.innerHTML = `
      <!-- Funnel Progress Visualization -->
      <div class="glass-panel" style="padding:24px; margin-bottom:24px;">
        <h3 style="font-size:15px; font-weight:600; color:#fff; margin-bottom:16px;">
          Outreach Conversion Funnel
        </h3>
        
        <div style="display:flex; flex-direction:column; gap:16px;">
          <div>
            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:6px;">
              <span>1. Harvested C2C Leads (${scraped})</span>
              <span style="color:var(--cyan-primary);">100% Base</span>
            </div>
            <div style="height:8px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden;">
              <div style="width:100%; height:100%; background:var(--cyan-primary);"></div>
            </div>
          </div>

          <div>
            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:6px;">
              <span>2. Dispatched Cold Outreach (${sent})</span>
              <span style="color:#34d399;">${sentPct}% of Leads</span>
            </div>
            <div style="height:8px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden;">
              <div style="width:${sentPct}%; height:100%; background:#10b981;"></div>
            </div>
          </div>

          <div>
            <div style="display:flex; justify-content:space-between; font-size:12px; margin-bottom:6px;">
              <span>3. Recruiter Responses Detected (${replies})</span>
              <span style="color:#60a5fa;">${replyPct}% Reply Rate</span>
            </div>
            <div style="height:8px; background:rgba(255,255,255,0.06); border-radius:4px; overflow:hidden;">
              <div style="width:${Math.min(100, replyPct * 2)}%; height:100%; background:#3b82f6;"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Candidate & Role Breakdown Grids -->
      <div style="display:grid; grid-template-columns: repeat(auto-fit, minmax(360px, 1fr)); gap:20px;">
        <!-- Candidate Breakdown -->
        <div class="table-container">
          <div class="table-toolbar">
            <h4 style="font-size:13px; font-weight:600; color:#fff;">Candidate Performance</h4>
          </div>
          <table class="custom-table">
            <thead>
              <tr>
                <th>Candidate</th>
                <th>Sent</th>
                <th>Replies</th>
                <th>Reply Rate</th>
              </tr>
            </thead>
            <tbody>
              ${Object.keys(candStats).length > 0 ? Object.entries(candStats).map(([candName, stat]) => {
                const cSent = stat.sent || 0;
                const cReplies = stat.replied || 0;
                const cRate = cSent > 0 ? ((cReplies / cSent) * 100).toFixed(1) : '0.0';
                return `
                  <tr>
                    <td style="font-weight:600; color:#fff;">${escapeHtml(candName)}</td>
                    <td>${cSent}</td>
                    <td><span style="color:#60a5fa; font-weight:600;">${cReplies}</span></td>
                    <td><span class="badge ${parseFloat(cRate) > 0 ? 'badge-replied' : 'badge-mismatched'}">${cRate}%</span></td>
                  </tr>
                `;
              }).join('') : `
                <tr><td colspan="4" style="text-align:center; padding:20px; color:var(--text-dim);">No candidate data yet.</td></tr>
              `}
            </tbody>
          </table>
        </div>

        <!-- Role Breakdown -->
        <div class="table-container">
          <div class="table-toolbar">
            <h4 style="font-size:13px; font-weight:600; color:#fff;">Target Role Distribution</h4>
          </div>
          <table class="custom-table">
            <thead>
              <tr>
                <th>Role</th>
                <th>Volume</th>
              </tr>
            </thead>
            <tbody>
              ${Object.keys(roleStats).length > 0 ? Object.entries(roleStats).map(([role, count]) => `
                <tr>
                  <td style="font-weight:600; color:#fff;">${escapeHtml(role)}</td>
                  <td><span class="badge badge-sent">${count} posts</span></td>
                </tr>
              `).join('') : `
                <tr><td colspan="2" style="text-align:center; padding:20px; color:var(--text-dim);">No role data yet.</td></tr>
              `}
            </tbody>
          </table>
        </div>
      </div>
    `;
  } catch (e) {
    content.innerHTML = `<div style="color:var(--color-danger); padding:24px;">Failed loading metrics: ${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
