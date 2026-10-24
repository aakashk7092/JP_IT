/**
 * API Client for Recruitment & Outreach Automation System
 * Wraps all backend endpoints with structured error handling
 */

const API_BASE = '/api';

async function request(endpoint, options = {}) {
  const url = `${API_BASE}${endpoint}`;
  const headers = {
    'Content-Type': 'application/json',
    ...(options.headers || {}),
  };

  try {
    const response = await fetch(url, { ...options, headers });
    if (!response.ok) {
      let errorMsg = `HTTP ${response.status} ${response.statusText}`;
      try {
        const errData = await response.json();
        if (errData.detail) {
          errorMsg = typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail);
        }
      } catch (_) {}
      throw new Error(errorMsg);
    }
    return await response.json();
  } catch (error) {
    console.error(`API Error [${endpoint}]:`, error);
    throw error;
  }
}

export const API = {
  // System & Foundation
  getHealth: () => request('/health'),
  getStatus: () => request('/status'),
  getCandidates: () => request('/candidates'),
  getRecruiters: (filter = '', search = '', page = 1, pageSize = 50) => {
    const params = new URLSearchParams({ page, page_size: pageSize });
    if (filter) params.append('status_filter', filter);
    if (search) params.append('search', search);
    return request(`/recruiters?${params.toString()}`);
  },
  getHistory: (search = '', repliedOnly = false, page = 1, pageSize = 50) => {
    const params = new URLSearchParams({ page, page_size: pageSize, replied_only: repliedOnly });
    if (search) params.append('search', search);
    return request(`/history?${params.toString()}`);
  },
  getSuppressionList: () => request('/suppression'),
  addSuppression: (email, reason) => request('/suppression/add', {
    method: 'POST',
    body: JSON.stringify({ email, reason }),
  }),
  removeSuppression: (email) => request(`/suppression/remove?email=${encodeURIComponent(email)}`, {
    method: 'DELETE',
  }),
  getLogs: (lines = 80) => request(`/logs?lines=${lines}`),

  // LinkedIn
  getLinkedInStatus: () => request('/linkedin/status'),
  loginLinkedIn: (timeoutSeconds = 300) => request(`/linkedin/login?timeout_seconds=${timeoutSeconds}`, {
    method: 'POST',
  }),
  createDemoSession: () => request('/linkedin/demo-session', {
    method: 'POST',
  }),
  runScraper: (candidateId = null, headless = true, limit = 20) => request('/scraper/run', {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId, headless, limit }),
  }),

  // Resume Customizer
  getDiffs: () => request('/customizer/diffs'),
  getDiffContent: (filename) => request(`/customizer/diff/${encodeURIComponent(filename)}`),
  tailorResume: (candidateId, recruiterEmail = null) => request('/customizer/tailor', {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId, recruiter_email: recruiterEmail }),
  }),

  // Gmail Outreach & Safety
  getPendingOutreach: (candidateId = null) => {
    const q = candidateId ? `?candidate_id=${encodeURIComponent(candidateId)}` : '';
    return request(`/outreach/pending${q}`);
  },
  sendOutreach: (candidateId, confirmToken = null, recruiterEmails = null) => request('/outreach/send', {
    method: 'POST',
    body: JSON.stringify({
      candidate_id: candidateId,
      confirm_token: confirmToken,
      recruiter_emails: recruiterEmails,
    }),
  }),
  setTestMode: (testMode) => request('/settings/test-mode', {
    method: 'POST',
    body: JSON.stringify({ test_mode: testMode }),
  }),

  // IMAP & Follow-ups
  syncIMAP: () => request('/imap/sync', { method: 'POST' }),
  getEligibleFollowups: (days = 7) => request(`/followup/eligible?days=${days}`),
  sendFollowups: (days = 7) => request(`/followup/send?days=${days}`, { method: 'POST' }),

  // Batch Pipeline & Analytics
  runBatchPipeline: (testMode = true, dailyLimit = 50) => request(`/pipeline/batch?test_mode=${testMode}&daily_limit=${dailyLimit}`, {
    method: 'POST',
  }),
  getJobs: () => request('/pipeline/jobs'),
  getJob: (jobId) => request(`/pipeline/job/${jobId}`),
  getMetrics: () => request('/analytics/metrics'),
  getSettings: () => request('/settings'),
  updateSettings: (data) => request('/settings', {
    method: 'POST',
    body: JSON.stringify(data),
  }),
};
