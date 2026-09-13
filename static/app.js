// ReviewMate AI — Frontend Client Logic

// API Base URL configuration:
// - Default '' uses same-origin relative paths (ideal when FastAPI serves frontend).
// - If frontend is hosted separately (Vercel/Netlify), set window.API_BASE_URL = 'https://<your-render-app>.onrender.com'
const API_BASE = (window.API_BASE_URL || '').replace(/\/+$/, '');

let currentReview = null;
let activeSeverityFilter = 'ALL';
let activeAgentFilter = 'ALL';

document.addEventListener('DOMContentLoaded', () => {
  initElements();
  loadRecentHistory();
});

function initElements() {
  const form = document.getElementById('analyzeForm');
  const analyzeBtn = document.getElementById('analyzeBtn');
  const alertCloseBtn = document.getElementById('alertCloseBtn');
  const postReviewBtn = document.getElementById('postReviewBtn');
  const copyMarkdownBtn = document.getElementById('copyMarkdownBtn');
  const clearReviewBtn = document.getElementById('clearReviewBtn');
  const historyToggleBtn = document.getElementById('historyToggleBtn');
  const closeHistoryBtn = document.getElementById('closeHistoryBtn');
  const drawerOverlay = document.getElementById('drawerOverlay');
  const agentFilterSelect = document.getElementById('agentFilterSelect');

  // Form submission
  form.addEventListener('submit', handleAnalyzeSubmit);

  // Alert close
  alertCloseBtn.addEventListener('click', hideAlert);

  // Quick example chips
  document.querySelectorAll('.example-chip').forEach(chip => {
    chip.addEventListener('click', (e) => {
      const url = e.target.getAttribute('data-url');
      const input = document.getElementById('prUrlInput');
      input.value = url;
      input.focus();
    });
  });

  // Severity filters
  document.querySelectorAll('.filter-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
      e.target.classList.add('active');
      activeSeverityFilter = e.target.getAttribute('data-val');
      renderFindings();
    });
  });

  // Agent filter
  agentFilterSelect.addEventListener('change', (e) => {
    activeAgentFilter = e.target.value;
    renderFindings();
  });

  // Post Review to GitHub
  postReviewBtn.addEventListener('click', handlePostReview);

  // Copy Markdown
  copyMarkdownBtn.addEventListener('click', handleCopyMarkdown);

  // Clear Review
  clearReviewBtn.addEventListener('click', handleClearReview);

  // History drawer
  historyToggleBtn.addEventListener('click', openHistoryDrawer);
  closeHistoryBtn.addEventListener('click', closeHistoryDrawer);
  drawerOverlay.addEventListener('click', closeHistoryDrawer);
}

// Alert banner display
function showAlert(message, type = 'error') {
  const banner = document.getElementById('alertBanner');
  const msgEl = document.getElementById('alertMessage');
  const iconEl = document.getElementById('alertIcon');

  banner.className = `alert-banner ${type}`;
  msgEl.textContent = message;
  iconEl.textContent = type === 'error' ? '⚠️' : '✓';
  banner.classList.remove('hidden');

  if (type === 'success') {
    setTimeout(hideAlert, 6000);
  }
}

function hideAlert() {
  const banner = document.getElementById('alertBanner');
  banner.classList.add('hidden');
}

// Handle PR analysis
async function handleAnalyzeSubmit(e) {
  e.preventDefault();
  hideAlert();

  const prUrlInput = document.getElementById('prUrlInput');
  const customTokenInput = document.getElementById('customTokenInput');
  const analyzeBtn = document.getElementById('analyzeBtn');
  const btnText = analyzeBtn.querySelector('.btn-text');
  const spinner = analyzeBtn.querySelector('.spinner');
  const progressSection = document.getElementById('progressSection');
  const progressBar = document.getElementById('progressBar');
  const progressMessage = document.getElementById('progressMessage');
  const resultsSection = document.getElementById('resultsSection');

  const prUrl = prUrlInput.value.trim();
  const customToken = customTokenInput ? customTokenInput.value.trim() : '';

  if (!prUrl) {
    showAlert('Please enter a valid GitHub pull request URL.');
    return;
  }

  // Set loading state
  analyzeBtn.disabled = true;
  btnText.textContent = 'Analyzing PR...';
  spinner.classList.remove('hidden');
  progressSection.classList.remove('hidden');
  resultsSection.classList.add('hidden');

  progressBar.style.width = '25%';
  progressMessage.textContent = 'Fetching PR metadata and diffs from GitHub API...';

  const progressInterval = setInterval(() => {
    const curWidth = parseInt(progressBar.style.width) || 25;
    if (curWidth < 85) {
      progressBar.style.width = (curWidth + 15) + '%';
      if (curWidth >= 40 && curWidth < 65) {
        progressMessage.textContent = 'Building bounded context & scanning for secrets...';
      } else if (curWidth >= 65) {
        progressMessage.textContent = 'Running Bug, Security, Quality & Performance LLM agents...';
      }
    }
  }, 1200);

  try {
    const payload = { pr_url: prUrl };
    if (customToken) {
      payload.github_token = customToken;
    }

    const response = await fetch(`${API_BASE}/api/analyze`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    clearInterval(progressInterval);
    progressBar.style.width = '100%';
    progressMessage.textContent = 'Review synthesis complete!';

    const data = await response.json();

    if (!response.ok) {
      const errorMsg = data.detail || 'Failed to analyze pull request.';
      showAlert(errorMsg, 'error');
      return;
    }

    currentReview = data;
    renderFullReview(data);
    loadRecentHistory();

  } catch (err) {
    clearInterval(progressInterval);
    showAlert(`Network or server connection error: ${err.message}`, 'error');
  } finally {
    setTimeout(() => {
      progressSection.classList.add('hidden');
      analyzeBtn.disabled = false;
      btnText.textContent = 'Analyze PR';
      spinner.classList.add('hidden');
    }, 400);
  }
}

// Render complete review
function renderFullReview(review) {
  const resultsSection = document.getElementById('resultsSection');
  resultsSection.classList.remove('hidden');

  // 1. PR Overview Card
  document.getElementById('prTitleText').textContent = review.pr_title || 'Untitled Pull Request';
  document.getElementById('prRepoBadge').textContent = review.repo;
  document.getElementById('prNumberText').textContent = `#${review.pr_number}`;
  document.getElementById('prAuthorText').textContent = review.pr_author || 'unknown';

  const diffSummary = (review.context_summary && review.context_summary.diff_summary) || {};
  document.getElementById('statFilesChanged').textContent = diffSummary.files_changed || review.context_summary.files_included?.length || 0;
  document.getElementById('statAdditions').textContent = `+${diffSummary.total_additions || 0}`;
  document.getElementById('statDeletions').textContent = `-${diffSummary.total_deletions || 0}`;

  // 2. Bounded Context Card
  const tokens = review.context_summary.estimated_tokens || 0;
  const limit = review.context_summary.context_limit || 6000;
  const pct = Math.min(100, Math.round((tokens / limit) * 100));

  document.getElementById('contextTokensText').textContent = tokens.toLocaleString();
  document.getElementById('contextLimitText').textContent = limit.toLocaleString();
  document.getElementById('tokenPercentText').textContent = `${pct}%`;

  const meterBar = document.getElementById('tokenMeterBar');
  meterBar.style.width = `${pct}%`;
  meterBar.style.backgroundColor = pct > 85 ? '#dc2626' : (pct > 60 ? '#f59e0b' : 'var(--accent)');

  const truncatedBadge = document.getElementById('contextTruncatedBadge');
  if (review.context_summary.is_truncated) {
    truncatedBadge.classList.remove('hidden');
  } else {
    truncatedBadge.classList.add('hidden');
  }

  // Files included
  const filesListEl = document.getElementById('contextFilesList');
  filesListEl.innerHTML = '';
  const files = review.context_summary.files_included || [];
  if (files.length === 0) {
    filesListEl.innerHTML = '<span class="text-muted text-sm">No files modified.</span>';
  } else {
    files.forEach(fn => {
      const span = document.createElement('span');
      span.className = 'file-tag';
      span.textContent = fn;
      filesListEl.appendChild(span);
    });
  }

  // Badges row for detected imports / configs / tests
  const detectedRow = document.getElementById('detectedBadgesRow');
  detectedRow.innerHTML = '';
  const imports = review.context_summary.imports_detected || [];
  const configs = review.context_summary.configs_detected || [];
  const tests = review.context_summary.tests_detected || [];

  if (imports.length > 0) {
    const span = document.createElement('span');
    span.className = 'tag-pill';
    span.textContent = `Imports: ${imports.slice(0, 5).join(', ')}${imports.length > 5 ? '...' : ''}`;
    detectedRow.appendChild(span);
  }
  if (configs.length > 0) {
    const span = document.createElement('span');
    span.className = 'tag-pill';
    span.textContent = `Configs: ${configs.join(', ')}`;
    detectedRow.appendChild(span);
  }
  if (tests.length > 0) {
    const span = document.createElement('span');
    span.className = 'tag-pill';
    span.textContent = `Tests: ${tests.length} file(s)`;
    detectedRow.appendChild(span);
  }

  // 3. Agent Status Cards
  const agents = ['bug', 'security', 'quality', 'performance'];
  agents.forEach(agentName => {
    const statusObj = (review.agent_statuses && review.agent_statuses[agentName]) || { status: 'completed', findings_count: 0 };
    const badgeEl = document.getElementById(`agentStatus-${agentName}`);
    const countEl = document.getElementById(`agentCount-${agentName}`);

    badgeEl.className = `agent-status-badge status-${statusObj.status}`;
    badgeEl.textContent = statusObj.status.toUpperCase();

    const count = statusObj.findings_count || 0;
    countEl.textContent = `${count} finding${count === 1 ? '' : 's'}`;
  });

  // 4. Final Recommendation Banner
  const banner = document.getElementById('recommendationBanner');
  const iconEl = document.getElementById('recIconBox');
  const titleEl = document.getElementById('recTitle');
  const descEl = document.getElementById('recDescription');

  const rec = review.recommendation || 'COMMENT';
  titleEl.textContent = rec;

  if (rec === 'APPROVE') {
    banner.className = 'recommendation-banner rec-approve';
    iconEl.textContent = '✅';
    descEl.textContent = 'No critical defects or blocking security flaws were found. Ready to merge.';
  } else if (rec === 'REQUEST_CHANGES') {
    banner.className = 'recommendation-banner rec-changes';
    iconEl.textContent = '🛑';
    descEl.textContent = 'High or Critical security/bug findings detected. Changes requested before merging.';
  } else {
    banner.className = 'recommendation-banner rec-comment';
    iconEl.textContent = '💬';
    descEl.textContent = 'Advisory suggestions or moderate improvements recommended for reviewer discussion.';
  }

  // Reset post area
  const postResultArea = document.getElementById('postResultArea');
  if (review.github_comment_url) {
    postResultArea.classList.remove('hidden');
    document.getElementById('commentLink').href = review.github_comment_url;
  } else {
    postResultArea.classList.add('hidden');
  }

  // 5. Findings
  renderFindings();

  // Smooth scroll into results
  resultsSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

// Filter and render findings
function renderFindings() {
  if (!currentReview) return;

  const container = document.getElementById('findingsContainer');
  const totalBadge = document.getElementById('totalFindingsBadge');
  container.innerHTML = '';

  const allFindings = currentReview.findings || [];
  totalBadge.textContent = `${allFindings.length} total`;

  const filtered = allFindings.filter(f => {
    // Severity filter
    if (activeSeverityFilter !== 'ALL') {
      if (activeSeverityFilter === 'CRITICAL' && f.severity !== 'CRITICAL') return false;
      if (activeSeverityFilter === 'HIGH' && f.severity !== 'HIGH') return false;
      if (activeSeverityFilter === 'MEDIUM' && f.severity !== 'MEDIUM') return false;
      if (activeSeverityFilter === 'LOW' && f.severity !== 'LOW') return false;
    }
    // Agent filter
    if (activeAgentFilter !== 'ALL') {
      if (!f.agent.toLowerCase().includes(activeAgentFilter.toLowerCase())) {
        return false;
      }
    }
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `
      <div style="text-align: center; padding: 36px 20px; color: var(--text-muted);">
        <p style="font-size: 1.1rem; font-weight: 600; margin-bottom: 4px;">No matching findings</p>
        <p style="font-size: 0.85rem;">Try adjusting the severity or agent filters above.</p>
      </div>
    `;
    return;
  }

  filtered.forEach(f => {
    const card = document.createElement('div');
    card.className = 'finding-card';

    const sevClass = (f.severity === 'CRITICAL' || f.severity === 'HIGH')
      ? 'badge-high'
      : (f.severity === 'MEDIUM' ? 'badge-medium' : 'badge-low');

    const lineText = f.line !== null && f.line !== undefined ? `:${f.line}` : '';

    card.innerHTML = `
      <div class="finding-header-row">
        <div class="finding-title-group">
          <span class="badge ${sevClass}">${f.severity}</span>
          <h3 class="finding-title">${escapeHtml(f.title)}</h3>
        </div>
        <span class="badge badge-subtle confidence-tag">${f.confidence} Conf.</span>
      </div>
      <div class="finding-meta-row">
        <span class="code-loc">${escapeHtml(f.file)}${lineText}</span>
        <span>•</span>
        <span>Agent: <strong>${escapeHtml(f.agent)}</strong></span>
        <span>•</span>
        <span>Category: ${escapeHtml(f.category)}</span>
      </div>
      <p class="finding-desc">${escapeHtml(f.description)}</p>
      <div class="finding-rec-box">
        <div class="finding-rec-label">Recommendation:</div>
        <div>${escapeHtml(f.recommendation)}</div>
      </div>
    `;

    container.appendChild(card);
  });
}

// Post review comment to GitHub
async function handlePostReview() {
  if (!currentReview) return;
  hideAlert();

  const postBtn = document.getElementById('postReviewBtn');
  const postResultArea = document.getElementById('postResultArea');
  const commentLink = document.getElementById('commentLink');
  const customTokenInput = document.getElementById('customTokenInput');
  const customToken = customTokenInput ? customTokenInput.value.trim() : '';

  const owner = currentReview.repo.split('/')[0];
  const repo = currentReview.repo.split('/')[1] || currentReview.repo;

  postBtn.disabled = true;
  postBtn.textContent = 'Posting to GitHub...';

  try {
    const payload = {
      review_id: currentReview.id,
      owner: owner,
      repo: repo,
      pr_number: currentReview.pr_number,
      summary_markdown: currentReview.summary_markdown,
    };
    if (customToken) {
      payload.github_token = customToken;
    }

    const response = await fetch(`${API_BASE}/api/post-review`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const data = await response.json();

    if (!response.ok) {
      showAlert(data.detail || 'Failed to post review comment to GitHub.', 'error');
      return;
    }

    // Success
    showAlert('Review posted successfully to GitHub.', 'success');
    postResultArea.classList.remove('hidden');
    commentLink.href = data.comment_url;
    commentLink.textContent = 'View on GitHub ↗';

    if (currentReview) {
      currentReview.github_comment_url = data.comment_url;
    }

  } catch (err) {
    showAlert(`Error communicating with server: ${err.message}`, 'error');
  } finally {
    postBtn.disabled = false;
    postBtn.innerHTML = `
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
        <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
      </svg>
      Post Review to GitHub
    `;
  }
}

// Copy markdown to clipboard
function handleCopyMarkdown() {
  if (!currentReview || !currentReview.summary_markdown) return;

  navigator.clipboard.writeText(currentReview.summary_markdown)
    .then(() => {
      showAlert('Review markdown copied to clipboard!', 'success');
    })
    .catch(() => {
      showAlert('Failed to copy to clipboard.', 'error');
    });
}

// Clear review view
function handleClearReview() {
  currentReview = null;
  document.getElementById('resultsSection').classList.add('hidden');
  document.getElementById('prUrlInput').value = '';
  document.getElementById('postResultArea').classList.add('hidden');
  hideAlert();
}

// History drawer
function openHistoryDrawer() {
  document.getElementById('historyDrawer').classList.add('open');
  document.getElementById('drawerOverlay').classList.add('active');
  loadRecentHistory();
}

function closeHistoryDrawer() {
  document.getElementById('historyDrawer').classList.remove('open');
  document.getElementById('drawerOverlay').classList.remove('active');
}

// Fetch and render review history
async function loadRecentHistory() {
  const historyList = document.getElementById('historyList');

  try {
    const resp = await fetch(`${API_BASE}/api/history?limit=15`);
    if (!resp.ok) return;

    const items = await resp.json();
    if (!items || items.length === 0) {
      historyList.innerHTML = '<div class="empty-state" style="padding: 24px; text-align: center; color: var(--text-muted);">No reviews stored yet.</div>';
      return;
    }

    historyList.innerHTML = '';
    items.forEach(item => {
      const el = document.createElement('div');
      el.className = 'history-item';

      const sevClass = item.recommendation === 'APPROVE'
        ? 'color: #059669;'
        : (item.recommendation === 'REQUEST_CHANGES' ? 'color: #dc2626;' : 'color: #d97706;');

      const dateStr = item.created_at ? new Date(item.created_at).toLocaleString() : '';

      el.innerHTML = `
        <div class="history-item-top">
          <span style="font-family: var(--font-mono); font-size: 0.8rem; font-weight: 600;">${escapeHtml(item.repo)}#${item.pr_number}</span>
          <span style="font-size: 0.75rem; font-weight: 700; ${sevClass}">${item.recommendation}</span>
        </div>
        <div class="history-item-title">${escapeHtml(item.pr_title || 'Untitled')}</div>
        <div class="history-item-meta">${dateStr} • ${item.findings ? item.findings.length : 0} finding(s)</div>
      `;

      el.addEventListener('click', () => {
        currentReview = item;
        renderFullReview(item);
        closeHistoryDrawer();
      });

      historyList.appendChild(el);
    });

  } catch (e) {
    console.error('Error fetching history:', e);
  }
}

// Utility: escape HTML
function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}
