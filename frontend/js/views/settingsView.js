/**
 * Settings View - Environment Credentials, LLM Models & Safety Thresholds Editor
 */

import { API } from '../api.js';
import { store } from '../store.js';
import { showToast } from '../notifications.js';

export async function renderSettings(container) {
  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>System Settings & Credentials</h2>
        <p>Configure LLM provider chains, Gmail SMTP credentials, and safety limits</p>
      </div>
      <button id="save-settings-btn" class="btn btn-primary">
        <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>
        Save Settings to .env
      </button>
    </div>

    <div id="settings-form-container">
      <div style="text-align:center; padding:36px; color:var(--text-dim);">Loading configuration...</div>
    </div>
  `;

  await loadSettings(container);
}

async function loadSettings(container) {
  const content = container.querySelector('#settings-form-container');
  if (!content) return;

  try {
    const s = await API.getSettings();

    content.innerHTML = `
      <div class="settings-grid">
        <!-- LLM Configuration Card -->
        <div class="settings-card">
          <h3>
            <svg width="18" height="18" fill="none" stroke="var(--cyan-primary)" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path></svg>
            LLM Provider Chain
          </h3>

          <div class="form-group">
            <label>Google Gemini API Key ${s.gemini_api_key_configured ? '<span style="color:var(--color-success);">(Configured)</span>' : '<span style="color:var(--color-danger);">(Missing)</span>'}</label>
            <input type="password" id="cfg-gemini-key" class="form-control" placeholder="${s.gemini_api_key_masked || 'Enter GEMINI_API_KEY'}" />
          </div>

          <div class="form-group">
            <label>Gemini Model</label>
            <input type="text" id="cfg-gemini-model" class="form-control" value="${escapeHtml(s.gemini_model || 'gemini-3.8-flash')}" />
          </div>

          <div class="form-group">
            <label>Groq API Key ${s.groq_api_key_configured ? '<span style="color:var(--color-success);">(Configured)</span>' : '<span style="color:var(--text-dim);">(Optional)</span>'}</label>
            <input type="password" id="cfg-groq-key" class="form-control" placeholder="${s.groq_api_key_masked || 'Enter GROQ_API_KEY'}" />
          </div>

          <div class="form-group">
            <label>Groq Model</label>
            <input type="text" id="cfg-groq-model" class="form-control" value="${escapeHtml(s.groq_model || 'llama-3.3-70b-versatile')}" />
          </div>

          <div class="form-group">
            <label>OpenRouter API Key ${s.openrouter_api_key_configured ? '<span style="color:var(--color-success);">(Configured)</span>' : '<span style="color:var(--text-dim);">(Optional)</span>'}</label>
            <input type="password" id="cfg-openrouter-key" class="form-control" placeholder="${s.openrouter_api_key_masked || 'Enter OPENROUTER_API_KEY'}" />
          </div>

          <div class="form-group">
            <label>OpenRouter Model</label>
            <input type="text" id="cfg-openrouter-model" class="form-control" value="${escapeHtml(s.openrouter_model || 'meta-llama/llama-3.1-8b-instruct:free')}" />
          </div>
        </div>

        <!-- Gmail Credentials & Distribution Card -->
        <div class="settings-card">
          <h3>
            <svg width="18" height="18" fill="none" stroke="var(--cyan-primary)" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"></path></svg>
            Gmail SMTP & Distribution
          </h3>

          <div class="form-group">
            <label>Sender Gmail Address</label>
            <input type="email" id="cfg-gmail-email" class="form-control" value="${escapeHtml(s.gmail_email || '')}" placeholder="your.company@gmail.com" />
          </div>

          <div class="form-group">
            <label>Google App Password (16 characters) ${s.gmail_password_configured ? '<span style="color:var(--color-success);">(Configured)</span>' : '<span style="color:var(--color-danger);">(Missing)</span>'}</label>
            <input type="password" id="cfg-gmail-pass" class="form-control" placeholder="••••••••••••••••" />
          </div>

          <div class="form-group">
            <label>Operator Email (Receives redirected test mode emails)</label>
            <input type="email" id="cfg-operator-email" class="form-control" value="${escapeHtml(s.operator_email || '')}" />
          </div>

          <div class="form-group">
            <label>Team Lead Email (CC on all dispatches)</label>
            <input type="email" id="cfg-lead-email" class="form-control" value="${escapeHtml(s.team_lead_email || '')}" />
          </div>

          <div class="form-group">
            <label>Admin BCC Email (Audit archive)</label>
            <input type="email" id="cfg-bcc-email" class="form-control" value="${escapeHtml(s.admin_bcc_email || '')}" />
          </div>
        </div>

        <!-- Campaign Safeguards & Rate Limits Card -->
        <div class="settings-card">
          <h3>
            <svg width="18" height="18" fill="none" stroke="var(--cyan-primary)" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"></path></svg>
            Outreach Safeguards & Rate Limits
          </h3>

          <div class="form-group">
            <label>Default Test Mode (Safe Redirection)</label>
            <select id="cfg-test-mode" class="form-control">
              <option value="true" ${s.test_mode ? 'selected' : ''}>Enabled (Safe Test Mode - Redirect to Operator)</option>
              <option value="false" ${!s.test_mode ? 'selected' : ''}>Disabled (Live Outreach to Real Recruiters)</option>
            </select>
          </div>

          <div class="form-group">
            <label>Global Daily Email Limit</label>
            <input type="number" id="cfg-daily-limit" class="form-control" value="${s.global_daily_limit || 50}" min="5" max="250" />
          </div>

          <div class="form-group">
            <label>Follow-up Days Threshold (Default: 7 Days)</label>
            <input type="number" id="cfg-followup-days" class="form-control" value="${s.followup_days || 7}" min="1" max="30" />
          </div>
        </div>
      </div>
    `;

    container.querySelector('#save-settings-btn')?.addEventListener('click', async () => {
      const payload = {};

      const gKey = container.querySelector('#cfg-gemini-key')?.value.trim();
      if (gKey) payload.gemini_api_key = gKey;
      payload.gemini_model = container.querySelector('#cfg-gemini-model')?.value.trim();

      const groqKey = container.querySelector('#cfg-groq-key')?.value.trim();
      if (groqKey) payload.groq_api_key = groqKey;
      payload.groq_model = container.querySelector('#cfg-groq-model')?.value.trim();

      const orKey = container.querySelector('#cfg-openrouter-key')?.value.trim();
      if (orKey) payload.openrouter_api_key = orKey;
      payload.openrouter_model = container.querySelector('#cfg-openrouter-model')?.value.trim();

      payload.gmail_email = container.querySelector('#cfg-gmail-email')?.value.trim();
      const gPass = container.querySelector('#cfg-gmail-pass')?.value.trim();
      if (gPass) payload.gmail_app_password = gPass;

      payload.operator_email = container.querySelector('#cfg-operator-email')?.value.trim();
      payload.team_lead_email = container.querySelector('#cfg-lead-email')?.value.trim();
      payload.admin_bcc_email = container.querySelector('#cfg-bcc-email')?.value.trim();
      payload.test_mode = container.querySelector('#cfg-test-mode')?.value === 'true';
      payload.global_daily_limit = parseInt(container.querySelector('#cfg-daily-limit')?.value || '50', 10);
      payload.followup_days = parseInt(container.querySelector('#cfg-followup-days')?.value || '7', 10);

      try {
        const res = await API.updateSettings(payload);
        showToast(`Settings saved (${res.updated_keys.length} keys updated)`, 'success');
        store.setState({ testMode: payload.test_mode });
      } catch (e) {
        showToast(e.message, 'error');
      }
    });

  } catch (e) {
    content.innerHTML = `<div style="color:var(--color-danger); padding:24px;">Failed loading settings: ${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
