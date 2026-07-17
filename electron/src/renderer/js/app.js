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
        // R7.0: use the IPC get-health so we get the full stale_code
        // shape (the renderer's previous version only saw {ready,port}
        // from the IPC bridge, which made stale_code invisible here).
        const r = await window.aerie.electron.getHealth();
        if (r) {
          if (statsBackend) statsBackend.textContent = r.ready ? "运行中" : "异常";
          // QQ status still comes from the /api/health HTTP endpoint
          try {
            const http = await window.aerie.api.request({ method: "GET", path: "/api/health" });
            if (http && http.data) {
              if (statsQQ) statsQQ.textContent = http.data.qq_connected ? "已连接" : "未连接";
              // Drive the stale-state machine from the authoritative
              // backend value (covers both IPC and HTTP paths).
              if (http.data.stale_code) {
                _setStaleState({
                  stale: !!http.data.stale_code.stale,
                  modified: http.data.stale_code.modified || [],
                  started_at: http.data.stale_code.started_at || http.data.process_started_at || "",
                });
              } else if (r.stale) {
                // Fallback: IPC saw stale, fall through to banner.
                _setStaleState({
                  stale: true,
                  modified: r.modified || [],
                  started_at: r.started_at || "",
                });
              }
            }
          } catch (_) {}
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

// R6.6 → R7.0: stale-code strong prompt.
// Two visual surfaces are kept in sync:
//   1. A persistent top banner under the titlebar (cannot be missed).
//   2. A small toast (kept for backward compatibility).
// Both are idempotent — only one DOM element per kind. The state
// transitions are driven by _setStaleState() which the status poll
// calls whenever the latest /api/health response comes back.
let _staleBannerEl = null;
let _staleToastEl = null;
let _staleActive = false;

function _setStaleState(stale) {
  const isStale = !!(stale && stale.stale);
  if (isStale === _staleActive) {
    // Same state — just refresh the file list in case it changed.
    if (isStale) {
      if (_staleBannerEl) {
        _staleBannerEl.querySelector(".stale-list").textContent =
          (stale.modified || []).slice(0, 3).join(", ");
      }
      if (_staleToastEl) {
        _staleToastEl.querySelector(".stale-list").textContent =
          (stale.modified || []).slice(0, 3).join(", ");
      }
      _updateRestartBtnDot(true, (stale.modified || []).slice(0, 3).join(", "));
    }
    return;
  }
  _staleActive = isStale;
  if (isStale) {
    _showStaleBanner(stale);
    _showStaleCodeToast(stale);
    _updateRestartBtnDot(true, (stale.modified || []).slice(0, 3).join(", "));
  } else {
    _hideStaleBanner();
    _hideStaleCodeToast();
    _updateRestartBtnDot(false, "");
  }
}

function _updateRestartBtnDot(show, tip) {
  const btn = document.getElementById("settings-restart-btn");
  if (!btn) return;
  if (show) {
    btn.classList.add("btn-restart-stale");
    btn.title = (btn.getAttribute("data-original-title") || "重启后端服务 / Restart Python backend")
      + " · 代码已变更，请点击重启 / code changed, click to restart";
  } else {
    btn.classList.remove("btn-restart-stale");
    btn.title = btn.getAttribute("data-original-title") || "重启后端服务 / Restart Python backend";
  }
}

function _showStaleBanner(stale) {
  if (_staleBannerEl) return;
  const el = document.createElement("div");
  el.className = "stale-banner";
  el.innerHTML = (
    '<div class="stale-banner__inner">'
    + '<span class="stale-banner__icon" aria-hidden="true">'
    + '<svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-warning"/></svg>'
    + '</span>'
    + '<span class="stale-banner__text">'
    + '<strong>后端代码已更新</strong> · Backend code updated · 启动于 '
    + (stale.started_at || "?")
    + ' · 变更: <span class="stale-list">'
    + (stale.modified || []).slice(0, 3).join(", ")
    + "</span>"
    + "</span>"
    + '<button class="stale-banner__action" id="stale-banner-restart">立即重启后端 / Restart now</button>'
    + '<button class="stale-banner__close" id="stale-banner-close" title="关闭">×</button>'
    + "</div>"
  );
  Object.assign(el.style, {
    position: "fixed",
    top: "0", left: "0", right: "0",
    zIndex: "10000",
    background: "linear-gradient(180deg, #fff7e6 0%, #ffe8b3 100%)",
    borderBottom: "1px solid #f5b042",
    color: "#7a4a00",
    fontSize: "13px",
    boxShadow: "0 2px 12px rgba(0,0,0,0.08)",
    fontFamily: "system-ui, sans-serif",
  });
  // Inline styles for children
  const inner = el.querySelector(".stale-banner__inner");
  Object.assign(inner.style, {
    display: "flex", alignItems: "center", gap: "10px",
    padding: "8px 14px", maxWidth: "100%",
  });
  const actionBtn = el.querySelector("#stale-banner-restart");
  Object.assign(actionBtn.style, {
    marginLeft: "auto",
    padding: "4px 10px",
    background: "#f5b042", color: "#fff",
    border: "none", borderRadius: "4px",
    cursor: "pointer", fontSize: "12px", fontWeight: "600",
  });
  const closeBtn = el.querySelector("#stale-banner-close");
  Object.assign(closeBtn.style, {
    background: "transparent", border: "none",
    color: "#7a4a00", fontSize: "18px",
    cursor: "pointer", padding: "0 4px", lineHeight: "1",
  });
  // Wire actions
  actionBtn.addEventListener("click", async () => {
    if (!window.aerie || !window.aerie.invoke) {
      // Fall back to opening the settings tab where the user can click restart
      const tab = document.querySelector('.sidebar-tab[data-tab="settings"]');
      if (tab) tab.click();
      return;
    }
    try {
      actionBtn.disabled = true;
      actionBtn.textContent = "重启中… / Restarting…";
      await window.aerie.invoke("system:restart-backend");
    } catch (_) {}
  });
  closeBtn.addEventListener("click", () => _hideStaleBanner());
  document.body.appendChild(el);
  _staleBannerEl = el;
}

function _hideStaleBanner() {
  if (_staleBannerEl && _staleBannerEl.parentNode) {
    _staleBannerEl.parentNode.removeChild(_staleBannerEl);
  }
  _staleBannerEl = null;
}

function _showStaleCodeToast(stale) {
  if (_staleToastEl) {
    const list = (stale.modified || []).slice(0, 3).join(", ");
    _staleToastEl.querySelector(".stale-list").textContent = list;
    return;
  }
  const el = document.createElement("div");
  el.className = "stale-toast";
  el.innerHTML = (
    '<div class="stale-title"><svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-warning"/></svg> 后端代码已更新 · Backend code updated</div>'
    + '<div class="stale-detail">启动于 ' + (stale.started_at || "?") + "，以下文件已变更：</div>"
    + '<div class="stale-list">' + (stale.modified || []).slice(0, 3).join(", ") + "</div>"
    + '<div class="stale-hint">请运行 tools/restart.bat 重启后端。</div>'
  );
  Object.assign(el.style, {
    position: "fixed", bottom: "16px", right: "16px", zIndex: "9999",
    background: "#fff7e6", border: "1px solid #f5b042", borderRadius: "8px",
    padding: "10px 14px", fontSize: "12px", color: "#7a4a00",
    boxShadow: "0 4px 16px rgba(0,0,0,0.1)", maxWidth: "320px",
    lineHeight: "1.5", fontFamily: "system-ui, sans-serif",
  });
  document.body.appendChild(el);
  _staleToastEl = el;
  setTimeout(() => {
    if (_staleToastEl === el) {
      el.style.display = "none";
    }
  }, 20000);
}

function _hideStaleCodeToast() {
  if (_staleToastEl && _staleToastEl.parentNode) {
    _staleToastEl.parentNode.removeChild(_staleToastEl);
  }
  _staleToastEl = null;
}
