/**
 * Notifications and Modal Management (Toast Alerts, Safety Barrier & Session Prompts)
 */

export function showToast(message, type = 'info', duration = 3500) {
  let container = document.getElementById('toast-container');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast ${type}`;

  const iconSvg = type === 'success'
    ? '<svg width="18" height="18" fill="none" stroke="#10b981" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M5 13l4 4L19 7"></path></svg>'
    : type === 'error'
    ? '<svg width="18" height="18" fill="none" stroke="#ef4444" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>'
    : '<svg width="18" height="18" fill="none" stroke="#06b6d4" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>';

  toast.innerHTML = `${iconSvg}<span>${escapeHtml(message)}</span>`;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(10px)';
    toast.style.transition = 'all 0.3s ease';
    setTimeout(() => toast.remove(), 300);
  }, duration);
}

export function openSafetyBarrierModal({ title, message, targetCount, requiredToken = 'SEND', onConfirm }) {
  const modalOverlay = document.getElementById('safety-modal');
  const modalTitle = document.getElementById('safety-modal-title');
  const modalDesc = document.getElementById('safety-modal-desc');
  const modalInput = document.getElementById('safety-token-input');
  const modalConfirmBtn = document.getElementById('safety-confirm-btn');
  const modalCancelBtn = document.getElementById('safety-cancel-btn');

  if (!modalOverlay) return;

  modalTitle.textContent = title || 'LIVE OUTREACH DISPATCH PROTECTION';
  modalDesc.innerHTML = message || `You are about to dispatch real emails to <strong>${targetCount}</strong> recruiters. Type <code>${requiredToken}</code> to confirm.`;
  modalInput.value = '';
  modalConfirmBtn.disabled = true;

  const validateInput = () => {
    modalConfirmBtn.disabled = modalInput.value.trim() !== requiredToken;
  };

  modalInput.oninput = validateInput;

  const closeModal = () => {
    modalOverlay.classList.remove('open');
    modalInput.oninput = null;
  };

  modalCancelBtn.onclick = closeModal;

  modalConfirmBtn.onclick = () => {
    if (modalInput.value.trim() === requiredToken) {
      closeModal();
      if (onConfirm) onConfirm();
    }
  };

  modalOverlay.classList.add('open');
  modalInput.focus();
}

export function openSessionRequiredModal({ onLaunchLogin, onDemoSession }) {
  let modalOverlay = document.getElementById('session-required-modal');
  if (!modalOverlay) {
    modalOverlay = document.createElement('div');
    modalOverlay.id = 'session-required-modal';
    modalOverlay.className = 'modal-overlay';
    modalOverlay.innerHTML = `
      <div class="modal-content glass-panel" style="max-width: 480px;">
        <div style="display:flex; align-items:center; gap:12px; margin-bottom:16px;">
          <div style="width:40px; height:40px; border-radius:10px; background:rgba(6,182,212,0.15); display:flex; align-items:center; justify-content:center; font-size:20px;">
            🔑
          </div>
          <div>
            <h3 style="font-family:var(--font-display); font-size:16px; font-weight:700; color:#ffffff;">
              LinkedIn Session Required
            </h3>
            <span style="font-size:11px; color:var(--text-dim); text-transform:uppercase;">Authentication Setup</span>
          </div>
        </div>

        <p style="font-size:13px; color:var(--text-muted); line-height:1.6; margin-bottom:20px;">
          Live LinkedIn post scraping requires an authenticated session (<code>session.json</code>). You can launch headful login to capture your cookies, or immediately load verified US C2C postings in sandbox mode to test tailoring, Gmail outreach, and analytics.
        </p>

        <div style="display:flex; flex-direction:column; gap:10px;">
          <button id="modal-demo-session-btn" class="btn btn-primary" style="width:100%; justify-content:center;">
            ⚡ Load Sandbox Leads & Session (Instant Test)
          </button>
          <button id="modal-live-login-btn" class="btn btn-secondary" style="width:100%; justify-content:center;">
            🌐 Launch LinkedIn Login Window (Manual 2FA)
          </button>
          <button id="modal-session-cancel-btn" class="btn btn-secondary btn-sm" style="margin-top:4px; width:100%; justify-content:center; color:var(--text-dim);">
            Cancel
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(modalOverlay);
  }

  const demoBtn = modalOverlay.querySelector('#modal-demo-session-btn');
  const loginBtn = modalOverlay.querySelector('#modal-live-login-btn');
  const cancelBtn = modalOverlay.querySelector('#modal-session-cancel-btn');

  const close = () => modalOverlay.classList.remove('open');

  demoBtn.onclick = () => {
    close();
    if (onDemoSession) onDemoSession();
  };

  loginBtn.onclick = () => {
    close();
    if (onLaunchLogin) onLaunchLogin();
  };

  cancelBtn.onclick = close;
  modalOverlay.classList.add('open');
}

function escapeHtml(str) {
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}
