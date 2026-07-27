document.addEventListener('DOMContentLoaded', () => {
  // Elements
  const dropzone = document.getElementById('file-dropzone');
  const fileInput = document.getElementById('file-input');
  const browseBtn = document.getElementById('browse-btn');
  const fileList = document.getElementById('file-list');
  const configEditor = document.getElementById('config-editor');
  const jsonValidBadge = document.getElementById('json-valid-badge');

  const btnRunPipeline = document.getElementById('btn-run-pipeline');
  const btnSampleData = document.getElementById('btn-sample-data');
  const btnReproject = document.getElementById('btn-reproject');
  const btnResetConfig = document.getElementById('btn-reset-config');
  const btnExportJson = document.getElementById('btn-export-json');
  const btnExportCsv = document.getElementById('btn-export-csv');

  const statRaw = document.getElementById('stat-raw');
  const statMerged = document.getElementById('stat-merged');
  const statProjected = document.getElementById('stat-projected');

  const tabBtns = document.querySelectorAll('.tab-btn');
  const tabPanels = document.querySelectorAll('.tab-panel');

  const emptyState = document.getElementById('empty-state');
  const candidateCardsContainer = document.getElementById('candidate-cards-container');
  const jsonCanonicalView = document.getElementById('json-canonical-view');
  const jsonProjectedView = document.getElementById('json-projected-view');
  const serverStatus = document.getElementById('server-status');

  // App State
  let selectedFiles = [];
  let currentResult = null;
  let defaultConfig = null;

  // API Base URL (configured for Vercel -> Render cross-origin deployment)
  const API_BASE = window.API_BASE_URL || '';

  // Initialize
  init();

  async function init() {
    setupEventListeners();
    await fetchDefaultConfig();
  }

  async function fetchDefaultConfig() {
    try {
      const res = await fetch(`${API_BASE}/api/config/default`);
      if (res.ok) {
        defaultConfig = await res.json();
        configEditor.value = JSON.stringify(defaultConfig, null, 2);
        validateConfigJson();
      }
    } catch (err) {
      console.error('Failed to load default config:', err);
    }
  }

  function setupEventListeners() {
    // Browse & Dropzone
    browseBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      fileInput.click();
    });

    dropzone.addEventListener('click', () => fileInput.click());

    fileInput.addEventListener('change', (e) => {
      handleFilesSelected(Array.from(e.target.files));
    });

    dropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropzone.classList.add('dragover');
    });

    dropzone.addEventListener('dragleave', () => {
      dropzone.classList.remove('dragover');
    });

    dropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropzone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        handleFilesSelected(Array.from(e.dataTransfer.files));
      }
    });

    // Config Editor Validation
    configEditor.addEventListener('input', validateConfigJson);

    btnResetConfig.addEventListener('click', () => {
      if (defaultConfig) {
        configEditor.value = JSON.stringify(defaultConfig, null, 2);
        validateConfigJson();
      }
    });

    // Pipeline Actions
    btnRunPipeline.addEventListener('click', runPipeline);
    btnSampleData.addEventListener('click', runSamplePipeline);
    btnReproject.addEventListener('click', reprojectPipeline);

    // Export Actions
    btnExportJson.addEventListener('click', exportJson);
    btnExportCsv.addEventListener('click', exportCsv);

    // Tabs
    tabBtns.forEach((btn) => {
      btn.addEventListener('click', () => {
        const targetTab = btn.getAttribute('data-tab');
        tabBtns.forEach((b) => b.classList.remove('active'));
        tabPanels.forEach((p) => p.classList.remove('active'));

        btn.classList.add('active');
        document.getElementById(`tab-${targetTab}`).classList.add('active');
      });
    });
  }

  function handleFilesSelected(files) {
    const validExtensions = ['.json', '.csv', '.pdf', '.docx', '.txt'];
    const filtered = files.filter((file) => {
      const ext = '.' + file.name.split('.').pop().toLowerCase();
      return validExtensions.includes(ext);
    });

    selectedFiles = [...selectedFiles, ...filtered];
    renderFileList();
    updateButtonStates();
  }

  function renderFileList() {
    fileList.innerHTML = '';
    selectedFiles.forEach((file, index) => {
      const item = document.createElement('div');
      item.className = 'file-item';
      item.innerHTML = `
        <div class="file-info">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><polyline points="13 2 13 9 20 9"/></svg>
          <span>${escapeHtml(file.name)}</span>
          <span class="pill-badge">(${formatBytes(file.size)})</span>
        </div>
        <button class="file-remove" data-index="${index}">&times;</button>
      `;
      fileList.appendChild(item);
    });

    // Remove buttons
    fileList.querySelectorAll('.file-remove').forEach((btn) => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.getAttribute('data-index'), 10);
        selectedFiles.splice(idx, 1);
        renderFileList();
        updateButtonStates();
      });
    });
  }

  function validateConfigJson() {
    try {
      JSON.parse(configEditor.value);
      jsonValidBadge.className = 'badge badge-success';
      jsonValidBadge.textContent = 'Valid JSON';
      updateButtonStates();
      return true;
    } catch (e) {
      jsonValidBadge.className = 'badge badge-danger';
      jsonValidBadge.textContent = 'Invalid JSON';
      btnRunPipeline.disabled = true;
      btnReproject.disabled = true;
      return false;
    }
  }

  function updateButtonStates() {
    const isConfigValid = validateConfigJson();
    btnRunPipeline.disabled = !isConfigValid || selectedFiles.length === 0;
    btnReproject.disabled = !isConfigValid || !currentResult || !currentResult.canonical_profiles.length;
  }

  async function runPipeline() {
    if (selectedFiles.length === 0) return;

    setBusyState(true, 'Processing Files...');

    const formData = new FormData();
    selectedFiles.forEach((file) => formData.append('files', file));

    if (configEditor.value.trim()) {
      formData.append('config', configEditor.value.trim());
    }

    try {
      const res = await fetch(`${API_BASE}/api/process`, {
        method: 'POST',
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Pipeline execution failed.');
      }

      currentResult = await res.json();
      renderResults(currentResult);
    } catch (err) {
      alert('Pipeline Error: ' + err.message);
    } finally {
      setBusyState(false, 'Pipeline Ready');
    }
  }

  async function runSamplePipeline() {
    setBusyState(true, 'Running Demo Pipeline...');
    try {
      const res = await fetch(`${API_BASE}/api/process-samples`);
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to process sample dataset.');
      }

      currentResult = await res.json();
      renderResults(currentResult);
    } catch (err) {
      alert('Sample Processing Error: ' + err.message);
    } finally {
      setBusyState(false, 'Pipeline Ready');
    }
  }

  async function reprojectPipeline() {
    if (!currentResult || !currentResult.canonical_profiles) return;

    let configObj;
    try {
      configObj = JSON.parse(configEditor.value);
    } catch (e) {
      alert('Invalid JSON in projection config editor.');
      return;
    }

    setBusyState(true, 'Re-projecting Output...');

    try {
      const res = await fetch(`${API_BASE}/api/project`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          canonical_profiles: currentResult.canonical_profiles,
          config: configObj,
        }),
      });

      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Re-projection failed.');
      }

      const reprojectData = await res.json();
      currentResult.projected_profiles = reprojectData.projected_profiles;
      currentResult.config_used = reprojectData.config_used;

      // Update UI
      statProjected.textContent = currentResult.projected_profiles.length;
      jsonProjectedView.textContent = JSON.stringify(currentResult.projected_profiles, null, 2);
    } catch (err) {
      alert('Re-projection Error: ' + err.message);
    } finally {
      setBusyState(false, 'Pipeline Ready');
    }
  }

  function renderResults(data) {
    // Update Stats
    statRaw.textContent = data.summary.raw_records || 0;
    statMerged.textContent = data.summary.canonical_profiles || 0;
    statProjected.textContent = data.summary.projected_profiles || 0;

    // Code views
    jsonCanonicalView.textContent = JSON.stringify(data.canonical_profiles, null, 2);
    jsonProjectedView.textContent = JSON.stringify(data.projected_profiles, null, 2);

    // Cards
    candidateCardsContainer.innerHTML = '';
    if (!data.canonical_profiles || data.canonical_profiles.length === 0) {
      emptyState.style.display = 'block';
      btnExportJson.disabled = true;
      btnExportCsv.disabled = true;
    } else {
      emptyState.style.display = 'none';
      btnExportJson.disabled = false;
      btnExportCsv.disabled = false;

      data.canonical_profiles.forEach((profile) => {
        const card = createCandidateCard(profile);
        candidateCardsContainer.appendChild(card);
      });
    }

    updateButtonStates();
  }

  function createCandidateCard(p) {
    const card = document.createElement('div');
    card.className = 'candidate-card';

    const initials = p.full_name
      ? p.full_name.split(' ').map((n) => n[0]).join('').substring(0, 2).toUpperCase()
      : 'C';

    const emails = (p.emails || []).join(', ') || 'N/A';
    const phones = (p.phones || []).join(', ') || 'N/A';
    const location = p.location
      ? [p.location.city, p.location.state, p.location.country].filter(Boolean).join(', ')
      : 'N/A';

    const sourcesHtml = (p.sources || [])
      .map((s) => `<span class="badge badge-source">${escapeHtml(s.type || s.source_name || 'Source')} (auth: ${s.authority || '0.5'})</span>`)
      .join(' ');

    const skillsHtml = (p.skills || [])
      .map((sk) => `<span class="chip">${escapeHtml(typeof sk === 'string' ? sk : sk.name || sk)}</span>`)
      .join(' ');

    const workHtml = (p.work_history || [])
      .map(
        (w) => `
        <div class="timeline-item">
          <div>
            <div class="role-company">${escapeHtml(w.title || 'Role')} @ ${escapeHtml(w.company || 'Company')}</div>
          </div>
          <div class="dates">${escapeHtml(w.start_date || '')} - ${escapeHtml(w.end_date || 'Present')}</div>
        </div>
      `
      )
      .join('');

    card.innerHTML = `
      <div class="candidate-header">
        <div class="candidate-avatar-name">
          <div class="avatar">${initials}</div>
          <div>
            <div class="candidate-name">${escapeHtml(p.full_name || 'Unnamed Candidate')}</div>
            <div class="candidate-id">ID: ${escapeHtml(p.candidate_id || '')}</div>
          </div>
        </div>
        <div class="source-badges">${sourcesHtml}</div>
      </div>

      <div class="candidate-meta-grid">
        <div class="meta-item">
          <div class="meta-label">Email Address</div>
          <div class="meta-val">${escapeHtml(emails)}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">Phone (E.164)</div>
          <div class="meta-val">${escapeHtml(phones)}</div>
        </div>
        <div class="meta-item">
          <div class="meta-label">Location (ISO)</div>
          <div class="meta-val">${escapeHtml(location)}</div>
        </div>
      </div>

      ${skillsHtml ? `<div style="margin-bottom:0.75rem;"><div class="meta-label">Normalized Skills</div><div class="skill-chips">${skillsHtml}</div></div>` : ''}
      ${workHtml ? `<div><div class="meta-label">Work Experience Timeline</div><div class="work-timeline">${workHtml}</div></div>` : ''}
    `;

    return card;
  }

  function setBusyState(isBusy, message) {
    if (isBusy) {
      serverStatus.className = 'status-badge status-busy';
      serverStatus.querySelector('.status-text').textContent = message;
    } else {
      serverStatus.className = 'status-badge';
      serverStatus.querySelector('.status-text').textContent = message;
    }
  }

  function exportJson() {
    if (!currentResult || !currentResult.projected_profiles) return;
    const blob = new Blob([JSON.stringify(currentResult.projected_profiles, null, 2)], {
      type: 'application/json',
    });
    downloadFile(blob, 'projected_candidates.json');
  }

  function exportCsv() {
    if (!currentResult || !currentResult.projected_profiles || !currentResult.projected_profiles.length) return;
    const data = currentResult.projected_profiles;
    const headers = Object.keys(data[0]);
    
    let csv = headers.join(',') + '\n';
    data.forEach(row => {
      csv += headers.map(h => {
        let val = row[h];
        if (typeof val === 'object' && val !== null) val = JSON.stringify(val);
        return `"${String(val ?? '').replace(/"/g, '""')}"`;
      }).join(',') + '\n';
    });

    const blob = new Blob([csv], { type: 'text/csv' });
    downloadFile(blob, 'projected_candidates.csv');
  }

  function downloadFile(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  function formatBytes(bytes) {
    if (bytes === 0) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
  }

  function escapeHtml(str) {
    if (typeof str !== 'string') return str;
    return str.replace(/[&<>"']/g, (m) => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;',
    }[m]));
  }
});
