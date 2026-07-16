"use strict";
/* App shell: tab switching, window controls, health monitoring, emotion dashboard */

window.addEventListener("DOMContentLoaded", () => {
  // ── Theme switcher ──────────────────────────────
  if (window.themeSwitcher) {
    window.themeSwitcher.init();
  }

  // ── Emotion dashboard ──────────────────────────
  const emotionDashboard = new EmotionDashboard();
  emotionDashboard.init();

  // ── Emotion history curves (Phase 9 Batch 5) ───
  if (window.emotionHistory) {
    window.emotionHistory.init();
  }

  // ── Memorial panel ──────────────────────────────
  if (window.memorialPanel) {
    window.memorialPanel.init();
  }

  // ── Settings panel ──────────────────────────────
  if (window.settingsPanel) {
    window.settingsPanel.init();
  }

  // ── Data viewer ─────────────────────────────────
  if (window.dataViewer) {
    window.dataViewer.init();
  }

  // ── Cognition panel (Phase 9 Batch 4: brain center) ─
  if (window.cognitionPanel) {
    window.cognitionPanel.init();
  }

  // ── Tab switching ──────────────────────────────
  document.querySelectorAll(".sidebar-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".sidebar-tab").forEach((b) => b.classList.remove("active"));
      document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.getAttribute("data-tab");
      const panel = document.getElementById("panel-" + tab);
      if (panel) panel.classList.add("active");

      // Notify panels of visibility
      emotionDashboard.setVisible(tab === "emotion");
      if (window.emotionHistory) window.emotionHistory.setVisible(tab === "emotion");
      if (window.cognitionPanel) {
        window.cognitionPanel.setVisible(tab === "cognition");
      }
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

  // ── Window controls (min / max / close) ─────────
  const winApi = (window.aerie && window.aerie.electron && window.aerie.electron.window) || null;
  const btnMin = document.getElementById("btn-minimize");
  const btnMax = document.getElementById("btn-maximize");
  const btnClose = document.getElementById("btn-close");

  if (btnMin && winApi) {
    btnMin.addEventListener("click", (e) => {
      e.stopPropagation();
      winApi.minimize();
    });
  }
  if (btnMax && winApi) {
    btnMax.addEventListener("click", (e) => {
      e.stopPropagation();
      winApi.toggleMaximize().then((isMax) => {
        btnMax.classList.toggle("titlebar-btn--maximized", !!isMax);
        btnMax.title = isMax ? "还原" : "最大化";
      });
    });
    if (winApi.onMaximize) {
      winApi.onMaximize((isMax) => {
        btnMax.classList.toggle("titlebar-btn--maximized", !!isMax);
        btnMax.title = isMax ? "还原" : "最大化";
      });
    }
  }
  if (btnClose && winApi) {
    btnClose.addEventListener("click", (e) => {
      e.stopPropagation();
      winApi.close();
    });
  }

  // Double-click titlebar to toggle maximize (Windows convention)
  const titlebar = document.getElementById("titlebar");
  if (titlebar && winApi) {
    titlebar.addEventListener("dblclick", (e) => {
      // Ignore double-clicks on the buttons themselves
      if (e.target.closest(".titlebar-btn")) return;
      winApi.toggleMaximize().then((isMax) => {
        if (btnMax) {
          btnMax.classList.toggle("titlebar-btn--maximized", !!isMax);
          btnMax.title = isMax ? "还原" : "最大化";
        }
      });
    });
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
        if (t.data && !t.data.error) {
          const today = t.data.today || {};
          if (statsTokens) statsTokens.textContent = (today.total || 0).toLocaleString();
          if (statsCalls) statsCalls.textContent = today.calls || 0;
        }
      }
    } catch (_) {}
  }, 5000);

  // ── Block-4A R1.6: daily brief iframe toggle ─────────
  const briefFrame = document.getElementById("brief-frame");
  if (briefFrame && window.aerie && window.aerie.electron && window.aerie.electron.onBriefShow) {
    window.aerie.electron.onBriefShow((_data) => {
      // Re-load the iframe to refresh today's content, then reveal with fade-in.
      try {
        const src = briefFrame.getAttribute("src") || "daily-brief.html";
        briefFrame.setAttribute("src", src + (src.indexOf("?") >= 0 ? "&" : "?") + "t=" + Date.now());
      } catch (_) {}
      briefFrame.hidden = false;
    });
    // Click on the iframe backdrop area (very top 4px strip) to close.
    briefFrame.addEventListener("click", (ev) => {
      // The iframe inner page has its own close button; here we close on
      // Escape key as a safety net.
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !briefFrame.hidden) {
        briefFrame.hidden = true;
      }
    });
  }
});
