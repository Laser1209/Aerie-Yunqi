"use strict";
/* App shell: tab switching, window controls, health monitoring */

window.addEventListener("DOMContentLoaded", () => {
  // ── Tab switching ──────────────────────────────
  document.querySelectorAll(".sidebar-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".sidebar-tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.getAttribute("data-tab");
      const panel = document.getElementById("panel-" + tab);
      if (panel) panel.classList.add("active");
    });
  });

  // ── Status health monitoring ──────────────────
  const statusText = document.getElementById("status-text");
  const statusDot = document.getElementById("status-dot");
  const statsBackend = document.getElementById("stats-backend");
  const statsQQ = document.getElementById("stats-qq");
  const statsTokens = document.getElementById("stats-tokens");
  const statsCalls = document.getElementById("stats-calls");

  const updateStatus = (ready) => {
    if (ready) {
      if (statusText) { statusText.textContent = "后端已连接"; statusText.className = "status-text"; }
      if (statusDot) { statusDot.className = "status-dot status-dot--ok"; }
    } else {
      if (statusText) { statusText.textContent = "后端离线"; statusText.className = "status-text status-text--loading"; }
      if (statusDot) { statusDot.className = "status-dot status-dot--error"; }
    }
  };

  if (window.aerie && window.aerie.electron) {
    window.aerie.electron.onHealth((data) => updateStatus(data.ready));
    window.aerie.electron.getHealth().then((data) => updateStatus(data.ready));
  }

  // Status panel poll
  setInterval(async () => {
    try {
      if (window.aerie) {
        const r = await window.aerie.api.request({ method: "GET", path: "/api/health" });
        if (r.data) {
          if (statsBackend) statsBackend.textContent = r.data.status === "ok" ? "运行中" : "异常";
          if (statsQQ) statsQQ.textContent = r.data.qq_connected ? "已连接" : "未连接";
        }
        const t = await window.aerie.api.request({ method: "GET", path: "/api/stats/tokens" });
        if (t.data) {
          if (statsTokens) statsTokens.textContent = (t.data.total_tokens || 0).toLocaleString();
          if (statsCalls) statsCalls.textContent = t.data.total_calls || 0;
        }
      }
    } catch (_) {}
  }, 5000);
});
