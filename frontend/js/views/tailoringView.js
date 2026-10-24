/**
 * Resume Customizer & Truthfulness Guard Diff Viewer
 */

import { API } from '../api.js';
import { store } from '../store.js';
import { showToast } from '../notifications.js';

let activeDiffFile = null;

export async function renderTailoring(container) {
  const cand = store.getActiveCandidate();

  container.innerHTML = `
    <div class="view-header">
      <div>
        <h2>Phase 3: Resume Tailoring & Truthfulness Guard</h2>
        <p>Grounds LLM customization strictly in original resume facts; rejects hallucinations</p>
      </div>
      <button id="trigger-tailor-btn" class="btn btn-primary">
        <svg width="16" height="16" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z"></path></svg>
        Tailor Resumes for Pending Posts
      </button>
    </div>

    <!-- Truthfulness Guard Summary Banner -->
    <div class="glass-panel" style="padding:16px 20px; margin-bottom:20px; display:flex; align-items:center; justify-content:space-between;">
      <div style="display:flex; align-items:center; gap:14px;">
        <div style="width:36px; height:36px; border-radius:8px; background:rgba(16,185,129,0.15); border:1px solid var(--color-success); display:flex; align-items:center; justify-content:center; color:var(--color-success); font-weight:700;">
          🛡️
        </div>
        <div>
          <div style="font-weight:600; color:#ffffff; font-size:13px;">Mandatory Truthfulness Guard Active</div>
          <div style="font-size:12px; color:var(--text-muted);">
            Diffs skills against ground-truth. If ungrounded skills (e.g. Solidity, Rust) appear, changes are rejected and original resume is used.
          </div>
        </div>
      </div>
      <span class="badge badge-sent">STRICT GROUNDING</span>
    </div>

    <!-- Diff Viewer Container -->
    <div class="diff-viewer-container">
      <div class="diff-file-list" id="diff-file-list-box">
        <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--text-dim); margin-bottom:8px; padding-left:4px;">
          Generated Diff Reports
        </div>
        <div style="color:var(--text-dim); font-size:12px; padding:12px;">Loading diffs...</div>
      </div>

      <div class="diff-code-panel" id="diff-code-display">
        <div style="text-align:center; padding:60px; color:var(--text-dim);">
          Select a diff report from the left panel to inspect original vs tailored changes.
        </div>
      </div>
    </div>
  `;

  // Attach tailor trigger
  container.querySelector('#trigger-tailor-btn')?.addEventListener('click', async () => {
    if (!cand) return showToast('No active candidate selected', 'error');
    try {
      const res = await API.tailorResume(cand.id);
      showToast(res.message, 'info');
      store.setState({ isDrawerExpanded: true });
      loadDiffs(container);
    } catch (e) {
      showToast(e.message, 'error');
    }
  });

  await loadDiffs(container);
}

async function loadDiffs(container) {
  const listBox = container.querySelector('#diff-file-list-box');
  const codeBox = container.querySelector('#diff-code-display');
  if (!listBox) return;

  try {
    const diffs = await API.getDiffs();
    if (diffs.length === 0) {
      listBox.innerHTML = `
        <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--text-dim); margin-bottom:8px; padding-left:4px;">
          Generated Diff Reports
        </div>
        <div style="color:var(--text-dim); font-size:12px; padding:12px;">
          No diff reports generated yet. Run tailoring on pending posts to view comparisons.
        </div>
      `;
      return;
    }

    listBox.innerHTML = `
      <div style="font-size:11px; font-weight:600; text-transform:uppercase; color:var(--text-dim); margin-bottom:8px; padding-left:4px;">
        Generated Diff Reports (${diffs.length})
      </div>
      ${diffs.map((d, idx) => `
        <div class="diff-item ${idx === 0 && !activeDiffFile ? 'active' : (activeDiffFile === d.filename ? 'active' : '')}" data-filename="${escapeHtml(d.filename)}">
          <div class="diff-title">${escapeHtml(d.filename)}</div>
          <div class="diff-meta">${d.modified_at} • ${(d.size / 1024).toFixed(1)} KB</div>
        </div>
      `).join('')}
    `;

    // Attach click listeners to items
    listBox.querySelectorAll('.diff-item').forEach(item => {
      item.addEventListener('click', async (e) => {
        listBox.querySelectorAll('.diff-item').forEach(i => i.classList.remove('active'));
        item.classList.add('active');
        const filename = item.getAttribute('data-filename');
        activeDiffFile = filename;
        await displayDiffContent(codeBox, filename);
      });
    });

    // Default select first item
    const firstToLoad = activeDiffFile || diffs[0].filename;
    activeDiffFile = firstToLoad;
    await displayDiffContent(codeBox, firstToLoad);

  } catch (e) {
    listBox.innerHTML = `<div style="color:var(--color-danger); font-size:12px;">Failed to load diffs: ${escapeHtml(e.message)}</div>`;
  }
}

async function displayDiffContent(codeBox, filename) {
  if (!codeBox || !filename) return;
  codeBox.innerHTML = '<div style="color:var(--text-dim);">Fetching diff content...</div>';

  try {
    const data = await API.getDiffContent(filename);
    const lines = data.content.split('\n');

    codeBox.innerHTML = lines.map(line => {
      const escaped = escapeHtml(line);
      if (line.startsWith('+') && !line.startsWith('+++')) {
        return `<div class="diff-line-add">${escaped}</div>`;
      }
      if (line.startsWith('-') && !line.startsWith('---')) {
        return `<div class="diff-line-del">${escaped}</div>`;
      }
      return `<div>${escaped}</div>`;
    }).join('');
  } catch (e) {
    codeBox.innerHTML = `<div style="color:var(--color-danger);">Failed reading diff: ${escapeHtml(e.message)}</div>`;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = String(str);
  return div.innerHTML;
}
