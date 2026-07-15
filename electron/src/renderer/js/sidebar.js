/* Aerie · 云栖 — Sidebar (5 tabs) */
(function () {
  'use strict';
  document.addEventListener('DOMContentLoaded', () => {
    const tabs = document.querySelectorAll('.tab');
    const panes = document.querySelectorAll('.tab-pane');
    tabs.forEach(btn => {
      btn.addEventListener('click', () => {
        tabs.forEach(b => b.classList.remove('active'));
        panes.forEach(p => p.classList.remove('active'));
        btn.classList.add('active');
        const target = btn.dataset.tab;
        const pane = document.querySelector(`.tab-pane[data-pane="${target}"]`);
        if (pane) pane.classList.add('active');
        if (target === 'emotion') refreshEmotion();
        if (target === 'data') refreshData();
      });
    });

    const themeSel = document.getElementById('theme-select');
    if (themeSel) {
      themeSel.value = window.AerieTheme.current();
      themeSel.addEventListener('change', (e) => {
        window.AerieTheme.apply(e.target.value);
      });
    }
    const autoStart = document.getElementById('auto-start');
    if (autoStart) {
      window.aerie.config.get().then(cfg => {
        autoStart.checked = !!cfg.auto_start;
      });
      autoStart.addEventListener('change', (e) => {
        window.aerie.config.set({ auto_start: e.target.checked });
      });
    }
    const pauseBtn = document.getElementById('pause-push');
    const resumeBtn = document.getElementById('resume-push');
    if (pauseBtn) pauseBtn.addEventListener('click', () => window.AerieAPI.post('/api/proactive/pause', { minutes: 60 }).then(() => alert('已暂停推送 1 小时')));
    if (resumeBtn) resumeBtn.addEventListener('click', () => window.AerieAPI.post('/api/proactive/resume', {}).then(() => alert('已恢复推送')));

    refreshEmotion();
    refreshData();
    refreshQQ();
    setInterval(refreshQQ, 5000);
    setInterval(refreshEmotion, 10000);
  });

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

  async function refreshData() {
    try {
      const data = await window.AerieAPI.get('/api/data/stats');
      const el = document.getElementById('data-stats');
      if (el) el.textContent = JSON.stringify(data, null, 2);
    } catch (e) { /* offline */ }
  }

  async function refreshQQ() {
    try {
      const data = await window.AerieAPI.get('/api/qq/status');
      const dot = document.getElementById('qq-dot');
      const txt = document.getElementById('qq-status');
      if (data.connected) {
        dot.classList.add('connected'); dot.classList.remove('disconnected');
        txt.textContent = `已连接 · QQ ${data.self_qq}`;
      } else {
        dot.classList.add('disconnected'); dot.classList.remove('connected');
        txt.textContent = '未连接';
      }
    } catch (e) {
      const dot = document.getElementById('qq-dot');
      const txt = document.getElementById('qq-status');
      dot.classList.add('disconnected');
      txt.textContent = '后端未启动';
    }
  }
})();
