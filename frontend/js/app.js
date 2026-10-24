/**
 * Main Application Orchestrator for Frontend
 * Initializes state, manages tab routing, polling loop, and event delegation
 */

import { API } from './api.js';
import { store } from './store.js';
import { openSessionRequiredModal, showToast } from './notifications.js';

import { renderDashboard } from './views/dashboardView.js';
import { renderCandidates } from './views/candidatesView.js';
import { renderScraper } from './views/scraperView.js';
import { renderTailoring } from './views/tailoringView.js';
import { renderOutreach } from './views/outreachView.js';
import { renderFollowups } from './views/followupsView.js';
import { renderAnalytics } from './views/analyticsView.js';
import { renderSettings } from './views/settingsView.js';

const viewRenderers = {
  dashboard: renderDashboard,
  candidates: renderCandidates,
  scraper: renderScraper,
  tailoring: renderTailoring,
  outreach: renderOutreach,
  followups: renderFollowups,
  analytics: renderAnalytics,
  settings: renderSettings,
};

let lastRenderedTab = null;
let lastRenderedCandidate = null;

export function refreshCurrentView() {
  renderCurrentView(store.getState().activeTab);
}

async function initApp() {
  console.log('[System] Initializing Recruitment Automation Dashboard...');

  // 1. Initial Data Fetch
  try {
    const [statusData, candidatesData, metricsData, jobsData, logsData] = await Promise.all([
      API.getStatus().catch(() => null),
      API.getCandidates().catch(() => []),
      API.getMetrics().catch(() => null),
      API.getJobs().catch(() => []),
      API.getLogs(60).catch(() => ({ logs: [] })),
    ]);

    const activeCand = candidatesData[0]?.id || '';
    const isTest = statusData?.credentials?.test_mode ?? true;

    store.setState({
      systemStatus: statusData,
      candidates: candidatesData,
      activeCandidateId: activeCand,
      testMode: isTest,
      metrics: metricsData,
      jobs: jobsData,
      logs: logsData.logs || [],
    });
  } catch (e) {
    console.error('Initialization error:', e);
    showToast('Failed to connect to backend API server. Is it running?', 'error');
  }

  // 2. Setup Top Header UI
  setupHeader();

  // 3. Setup Navigation Sidebar
  setupSidebar();

  // 4. Setup Activity Drawer
  setupActivityDrawer();

  // 5. Subscribe to State Changes: only re-render view if tab or candidate changes
  store.subscribe((state) => {
    updateHeaderUI(state);
    updateDrawerUI(state);

    if (state.activeTab !== lastRenderedTab || state.activeCandidateId !== lastRenderedCandidate) {
      lastRenderedTab = state.activeTab;
      lastRenderedCandidate = state.activeCandidateId;
      renderCurrentView(state.activeTab);
    }
  });

  // 6. Initial View Render
  lastRenderedTab = store.getState().activeTab;
  lastRenderedCandidate = store.getState().activeCandidateId;
  renderCurrentView(lastRenderedTab);

  // 7. Start Background Polling Loop (Logs, Jobs & Metrics every 4s)
  startPollingLoop();
}

function setupHeader() {
  const candSelect = document.getElementById('header-candidate-select');
  const modePill = document.getElementById('header-mode-pill');
  const batchLaunchBtn = document.getElementById('header-quick-batch-btn');

  // Populate candidate selector
  if (candSelect) {
    const { candidates, activeCandidateId } = store.getState();
    candSelect.innerHTML = candidates.map(c => `
      <option value="${c.id}" ${c.id === activeCandidateId ? 'selected' : ''}>
        ${escapeHtml(c.name)} (${escapeHtml(c.primary_role)})
      </option>
    `).join('');

    candSelect.addEventListener('change', (e) => {
      store.setState({ activeCandidateId: e.target.value });
      showToast(`Active candidate: ${e.target.selectedOptions[0].text}`, 'info');
    });
  }

  // Test mode toggle
  if (modePill) {
    modePill.addEventListener('click', async () => {
      const current = store.getState().testMode;
      const next = !current;
      try {
        await API.setTestMode(next);
        store.setState({ testMode: next });
        showToast(`Outreach mode changed to ${next ? 'TEST MODE (Safe)' : 'LIVE OUTREACH'}`, next ? 'info' : 'error');
      } catch (e) {
        showToast(e.message, 'error');
      }
    });
  }

  // Quick batch run with session verification
  if (batchLaunchBtn) {
    batchLaunchBtn.addEventListener('click', async () => {
      const { testMode, systemStatus } = store.getState();
      const hasSession = systemStatus?.credentials?.session_active;

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
  }
}

function updateHeaderUI(state) {
  const modePill = document.getElementById('header-mode-pill');
  if (modePill) {
    if (state.testMode) {
      modePill.className = 'mode-pill test-mode';
      modePill.innerHTML = '<span class="pulse-dot"></span> TEST MODE (Safe)';
    } else {
      modePill.className = 'mode-pill live-mode';
      modePill.innerHTML = '<span class="pulse-dot"></span> LIVE OUTREACH';
    }
  }

  const candSelect = document.getElementById('header-candidate-select');
  if (candSelect && candSelect.value !== state.activeCandidateId) {
    candSelect.value = state.activeCandidateId;
  }
}

function setupSidebar() {
  const navItems = document.querySelectorAll('.nav-item');
  navItems.forEach(item => {
    item.addEventListener('click', (e) => {
      const tab = e.currentTarget.getAttribute('data-tab');
      if (tab) {
        navItems.forEach(n => n.classList.remove('active'));
        item.classList.add('active');
        store.setState({ activeTab: tab });
      }
    });
  });
}

function renderCurrentView(tab) {
  const container = document.getElementById('content-viewport');
  if (!container) return;

  const renderer = viewRenderers[tab] || viewRenderers.dashboard;
  container.innerHTML = '';
  renderer(container);
}

function setupActivityDrawer() {
  const drawer = document.getElementById('activity-drawer');
  const toggleBtn = document.getElementById('drawer-toggle-btn');
  const clearBtn = document.getElementById('drawer-clear-btn');

  if (toggleBtn && drawer) {
    toggleBtn.addEventListener('click', () => {
      const expanded = drawer.classList.contains('expanded');
      store.setState({ isDrawerExpanded: !expanded });
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      store.setState({ logs: [] });
    });
  }
}

function updateDrawerUI(state) {
  const drawer = document.getElementById('activity-drawer');
  const toggleIcon = document.getElementById('drawer-toggle-icon');
  const logTerminal = document.getElementById('terminal-log-output');

  if (drawer) {
    if (state.isDrawerExpanded) {
      drawer.classList.remove('collapsed');
      drawer.classList.add('expanded');
      if (toggleIcon) toggleIcon.textContent = '▼';
    } else {
      drawer.classList.remove('expanded');
      drawer.classList.add('collapsed');
      if (toggleIcon) toggleIcon.textContent = '▲';
    }
  }

  if (logTerminal && state.logs) {
    logTerminal.textContent = state.logs.join('\n');
    logTerminal.scrollTop = logTerminal.scrollHeight;
  }
}

function startPollingLoop() {
  setInterval(async () => {
    try {
      const [logsData, jobsData, metricsData] = await Promise.all([
        API.getLogs(60).catch(() => ({ logs: [] })),
        API.getJobs().catch(() => []),
        API.getMetrics().catch(() => null),
      ]);

      const updates = {};
      if (logsData.logs) updates.logs = logsData.logs;
      if (jobsData) updates.jobs = jobsData;
      if (metricsData) updates.metrics = metricsData;

      store.setState(updates);
    } catch (_) {}
  }, 4000);
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}

// Bootstrap on DOM load
window.addEventListener('DOMContentLoaded', initApp);
