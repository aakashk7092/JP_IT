/**
 * Central State Store for Frontend Application
 */

class Store {
  constructor() {
    this.state = {
      activeTab: 'dashboard',
      candidates: [],
      activeCandidateId: '',
      systemStatus: null,
      testMode: true,
      metrics: null,
      jobs: [],
      logs: [],
      isDrawerExpanded: false,
    };
    this.listeners = new Set();
  }

  getState() {
    return this.state;
  }

  setState(updates) {
    this.state = { ...this.state, ...updates };
    this.notify();
  }

  subscribe(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  notify() {
    for (const listener of this.listeners) {
      try {
        listener(this.state);
      } catch (e) {
        console.error('Store listener error:', e);
      }
    }
  }

  getActiveCandidate() {
    return this.state.candidates.find(c => c.id === this.state.activeCandidateId) || this.state.candidates[0] || null;
  }
}

export const store = new Store();
