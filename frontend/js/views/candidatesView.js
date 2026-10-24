/**
 * Candidates View - Profile Inspection, Skill Highlights & Resume Verifier
 */

import { store } from '../store.js';
import { showToast } from '../notifications.js';

export function renderCandidates(container) {
  const { candidates, activeCandidateId } = store.getState();

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>Registered Consultant Candidates</h2>
        <p>Configured client profiles eligible for automated LinkedIn C2C marketing</p>
      </div>
    </div>

    <div class="candidate-cards-grid">
      ${candidates.map(c => {
        const isActive = c.id === activeCandidateId;
        const initials = c.name.split(' ').map(n => n[0]).join('').substring(0, 2).toUpperCase();

        return `
          <div class="candidate-profile-card ${isActive ? 'active-border' : ''}">
            <div class="candidate-header-row">
              <div style="display:flex; align-items:center; gap:12px;">
                <div class="candidate-avatar">${initials}</div>
                <div class="candidate-info">
                  <h3>${escapeHtml(c.name)}</h3>
                  <p>${escapeHtml(c.primary_role)} • ${c.experience_years} yrs exp</p>
                </div>
              </div>
              <span class="badge ${c.resume_exists ? 'badge-sent' : 'badge-failed'}">
                ${c.resume_exists ? 'RESUME OK' : 'MISSING'}
              </span>
            </div>

            <div style="font-size:12px; color:var(--text-dim); display:flex; flex-direction:column; gap:4px;">
              <div>📧 <strong>Email:</strong> ${escapeHtml(c.email)}</div>
              ${c.phone ? `<div>📞 <strong>Phone:</strong> ${escapeHtml(c.phone)}</div>` : ''}
              <div>📄 <strong>Source File:</strong> <code style="font-size:11px; color:#38bdf8;">${escapeHtml(c.resume_path)}</code></div>
            </div>

            <div>
              <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--text-dim); margin-bottom:6px;">
                Verified Skills (Ground Truth for Tailoring Guard):
              </div>
              <div>
                ${c.skills.map(s => `<span class="skill-tag">${escapeHtml(s)}</span>`).join('')}
              </div>
            </div>

            <div style="margin-top:auto; display:flex; gap:10px; padding-top:10px; border-top:1px solid var(--border-subtle);">
              <button class="btn btn-secondary btn-sm select-cand-btn" data-id="${c.id}" style="flex:1;">
                ${isActive ? '✓ Active Candidate' : 'Set as Active'}
              </button>
            </div>
          </div>
        `;
      }).join('')}
    </div>
  `;

  // Attach button click listeners
  container.querySelectorAll('.select-cand-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      const candId = e.currentTarget.getAttribute('data-id');
      store.setState({ activeCandidateId: candId });
      showToast('Active candidate updated', 'info');
    });
  });
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
