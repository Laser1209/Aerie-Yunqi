/* Aerie · 云栖 v9.0 — Sidebar (5 tabs) */

'use strict';

(function () {
  document.addEventListener('DOMContentLoaded', () => {
    const tabs = document.querySelectorAll('.tab');
    const panes = document.querySelectorAll('.tab-pane');
    tabs.forEach((btn) => {
      btn.addEventListener('click', () => {
        tabs.forEach((b) => b.classList.remove('active'));
        panes.forEach((p) => p.classList.remove('active'));
        btn.classList.add('active');
        const target = btn.dataset.tab;
        const pane = document.querySelector(`.tab-pane[data-pane="${target}"]`);
        if (pane) pane.classList.add('active');
        if (target === 'emotion') refreshEmotion();
        if (target === 'data') refreshData();
      });
    });

    // Theme selector
    const themeSel = document.getElementById('theme-select');
    if (themeSel) {
      themeSel.value = window.AerieTheme.current();
      themeSel.addEventListener('change', (e) => {
        window.AerieTheme.apply(e.target.value);
      });
    }

    // Auto-start
    const autoStart = document.getElementById('auto-start');
    if (autoStart) {
      window.aerie.config.get().then((cfg) => {
        autoStart.checked = !!cfg.auto_start;
      });
      autoStart.addEventListener('change', (e) => {
        window.aerie.config.set({ auto_start: e.target.checked });
      });
    }

    // Push pause/resume
    const pauseBtn = document.getElementById('pause-push');
    const resumeBtn = document.getElementById('resume-push');
    if (pauseBtn) pauseBtn.addEventListener('click', () => window.AerieAPI.post('/api/proactive/pause', { minutes: 60 }).then(() => alert('已暂停推送 1 小时')));
    if (resumeBtn) resumeBtn.addEventListener('click', () => window.AerieAPI.post('/api/proactive/resume', {}).then(() => alert('已恢复推送')));

    // Data tab — toggle JSON / chart view
    const toggleBtn = document.getElementById('data-toggle');
    if (toggleBtn) {
      toggleBtn.addEventListener('click', () => {
        const chart = document.getElementById('data-chart');
        const pre = document.getElementById('data-stats');
        if (!chart || !pre) return;
        if (pre.classList.contains('hidden')) {
          pre.classList.remove('hidden');
          chart.classList.add('hidden');
          toggleBtn.textContent = '查看图表';
        } else {
          pre.classList.add('hidden');
          chart.classList.remove('hidden');
          toggleBtn.textContent = '查看原始 JSON';
        }
      });
    }

    refreshEmotion();
    refreshData();
    setInterval(refreshEmotion, 10000);
    setInterval(refreshData, 30000);
  });

  // ---------- helpers ----------
  function _humanNumber(n) {
    if (typeof n !== 'number') return String(n);
    if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (Math.abs(n) >= 1e4) return (n / 1e3).toFixed(1) + 'k';
    return String(n);
  }

  function _pickMetric(data) {
    // Pull a handful of numeric metric candidates out of the data.
    const items = [];
    function walk(obj, prefix) {
      if (obj == null) return;
      if (typeof obj === 'number') {
        items.push({ key: prefix, value: obj });
      } else if (Array.isArray(obj)) {
        items.push({ key: prefix + ' (条目)', value: obj.length });
      } else if (typeof obj === 'object') {
        for (const k of Object.keys(obj)) walk(obj[k], prefix ? `${prefix}.${k}` : k);
      }
    }
    walk(data, '');
    return items;
  }

  // ---------- emotion ----------
  async function refreshEmotion() {
    try {
      const data = await window.AerieAPI.get('/api/emotion/current?user_id=0');
      const readout = document.getElementById('emotion-readout');
      if (readout) readout.textContent = `mood: ${data.label} | P=${data.pleasure} A=${data.arousal} D=${data.dominance}`;
      const panel = await window.AerieAPI.get('/api/emotion/panel?user_id=0');
      const pe = document.getElementById('emotion-panel');
      if (pe) pe.textContent = panel.panel || '';
    } catch (e) { /* offline */ }
  }

  // ---------- data ----------
  let _lastDataItems = null;

  async function refreshData() {
    let data;
    try {
      data = await window.AerieAPI.get('/api/data/stats');
    } catch (e) {
      data = { error: String(e), backend: 'unavailable' };
    }
    const pre = document.getElementById('data-stats');
    if (pre) pre.textContent = JSON.stringify(data, null, 2);
    const chartEl = document.getElementById('data-chart');
    if (!chartEl) return;
    const metrics = _pickMetric(data).slice(0, 12);
    _lastDataItems = metrics;
    if (!metrics.length) {
      chartEl.innerHTML = '<div class="bar-empty">暂无数据指标</div>';
      return;
    }
    const max = Math.max(...metrics.map((m) => Math.abs(m.value)), 1);
    chartEl.innerHTML = metrics
      .map((m) => {
        const w = Math.max(8, Math.round((Math.abs(m.value) / max) * 100));
        return `<div class="bar-item" data-key="${m.key}" data-value="${m.value}">
          <div class="bar-label">${m.key}</div>
          <div class="bar-track"><div class="bar-fill" style="width:${w}%"></div></div>
          <div class="bar-value">${_humanNumber(m.value)}</div>
        </div>`;
      })
      .join('');
    // Wire click handler
    chartEl.querySelectorAll('.bar-item').forEach((el) => {
      el.addEventListener('click', () => {
        const key = el.dataset.key;
        const value = Number(el.dataset.value);
        _showDataDetail(key, value, data);
      });
    });
  }

  // ---------- data detail modal ----------
  function _showDataDetail(key, value, full) {
    // Build path-walk on data
    const sub = _lookupPath(full, key);
    document.querySelectorAll('.aerie-modal').forEach((m) => m.remove());
    const wrap = document.createElement('div');
    wrap.className = 'aerie-modal';
    wrap.innerHTML = `
      <div class="aerie-modal-content">
        <header>
          <h3>${key}</h3>
          <button class="aerie-modal-close" aria-label="close">×</button>
        </header>
        <div class="aerie-modal-body">
          <div class="kpi-big">${typeof value === 'number' ? _humanNumber(value) : String(value)}</div>
          <pre>${typeof sub === 'string' || typeof sub === 'number' ? String(sub) : JSON.stringify(sub, null, 2)}</pre>
        </div>
      </div>
    `;
    document.body.appendChild(wrap);
    wrap.querySelector('.aerie-modal-close').addEventListener('click', () => wrap.remove());
    wrap.addEventListener('click', (e) => { if (e.target === wrap) wrap.remove(); });
  }

  function _lookupPath(obj, path) {
    if (!path) return obj;
    const parts = path.split('.');
    let cur = obj;
    for (const p of parts) {
      if (cur == null) return null;
      cur = cur[p];
    }
    return cur;
  }

  // Expose for tests
  window.AerieSidebar = { refreshData, refreshEmotion };
})();
