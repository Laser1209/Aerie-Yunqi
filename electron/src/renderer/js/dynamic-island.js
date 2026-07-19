"use strict";

(function () {
  const diEl = document.getElementById("dynamic-island");
  const capsuleEl = diEl.querySelector(".di-capsule");
  const capsuleLeft = diEl.querySelector(".di-capsule-left");
  const capsuleCenter = diEl.querySelector(".di-capsule-center");
  const capsuleRight = diEl.querySelector(".di-capsule-right");
  const expandedEl = diEl.querySelector(".di-expanded");
  const expandedBody = diEl.querySelector(".di-expanded-body");
  const closeBtn = document.getElementById("di-close");
  const particlesCanvas = document.getElementById("di-particles");
  const ctx = particlesCanvas.getContext("2d");

  const api = window.aerie?.dynamicIsland;

  let state = "capsule";
  let config = {
    theme: "dark",
    interaction: "click",
    expandType: "panel",
    hoverDelay: 300,
    longPressDuration: 500,
    capsuleComponents: ["companion", "media", "notifications"],
    // v13.9: mediaControl moved up to position 2 so it appears right after
    // the quick actions, no scrolling required on a 500px-tall island.
    expandedComponents: ["quickActions", "mediaControl", "companionDetail", "notifList", "systemStatus"],
  };

  let uiState = {
    companion: { mood: "joy", status: "online" },
    statusText: "云栖在你身边",
    notifications: { count: 0, items: [] },
    system: { cpu: 0, mem: 0, net: 0 },
    media: { playing: false, title: "", artist: "", progress: 0, duration: 0, thumbnail: "" },
    quickActions: ["chat", "brief", "cognition", "settings", "restart"],
    companionStartTime: Date.now(),
  };

  let hoverTimer = null;
  let pressTimer = null;
  let pressStart = 0;
  let particles = [];
  let animFrame = null;

  const ICON = (name, size = 16) => {
    const cls = `icon icon--${size}`;
    return `<svg class="${cls}" aria-hidden="true"><use href="#icon-${name}"/></svg>`;
  };

  const ACTION_ICONS = {
    chat: "ui-chat",
    brief: "ui-file-text",
    cognition: "ui-brain",
    settings: "ui-settings",
    calendar: "ui-calendar",
    files: "ui-folder",
    home: "ui-home",
    restart: "ui-refresh",
  };

  const MOOD_ICONS = {
    joy: "mood-joy",
    neutral: "mood-neutral",
    sad: "mood-sad",
    anger: "mood-anger",
    fear: "mood-fear",
  };

  /* ── Init ───────────────────────────────────── */
  function init() {
    loadConfig();
    applyTheme(config.theme);
    setupCanvas();
    bindEvents();
    renderCapsule();
    renderExpanded();
    startBreathParticles();
    bindIpcListeners();
    fetchInitialData();
  }

  function loadConfig() {
    try {
      const saved = localStorage.getItem("di_config");
      if (!saved) return;
      const parsed = JSON.parse(saved);
      // v13.9: stale localStorage configs from older builds may only
      // contain a subset of components (e.g. ["quickActions", "notifList"]),
      // which would silently overwrite the default expandedComponents and
      // hide mediaControl / systemStatus / companionDetail. Only merge
      // known top-level fields, and skip component arrays that are missing
      // any of the expected keys so the defaults win.
      const safeKeys = ["theme", "interaction", "expandType", "hoverDelay", "longPressDuration"];
      for (const k of safeKeys) {
        if (parsed[k] !== undefined) config[k] = parsed[k];
      }
      const requiredCapsule = ["companion", "media", "notifications"];
      const requiredExpanded = ["quickActions", "mediaControl", "companionDetail", "notifList", "systemStatus"];
      if (Array.isArray(parsed.capsuleComponents) &&
          requiredCapsule.every((k) => parsed.capsuleComponents.includes(k))) {
        config.capsuleComponents = parsed.capsuleComponents;
      }
      if (Array.isArray(parsed.expandedComponents) &&
          requiredExpanded.every((k) => parsed.expandedComponents.includes(k))) {
        config.expandedComponents = parsed.expandedComponents;
      }
    } catch (_) {}
  }

  function saveConfig() {
    try {
      localStorage.setItem("di_config", JSON.stringify(config));
    } catch (_) {}
  }

  function applyTheme(theme) {
    diEl.classList.remove("theme-dark", "theme-pink", "theme-light");
    diEl.classList.add(`theme-${theme}`);
    config.theme = theme;
    saveConfig();
  }

  function setupCanvas() {
    const dpr = window.devicePixelRatio || 1;
    const rect = diEl.getBoundingClientRect();
    particlesCanvas.width = rect.width * dpr;
    particlesCanvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
  }

  function resizeCanvas() {
    const rect = diEl.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    particlesCanvas.width = rect.width * dpr;
    particlesCanvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);
  }

  function fetchInitialData() {
    if (!api) return;
    try {
      api.getSystemStatus?.().then((r) => {
        if (r?.ok && r.data) {
          uiState.system = r.data;
          renderCapsule();
        }
      }).catch(() => {});

      api.mediaGetState?.().then((r) => {
        if (r?.ok && r.data) {
          uiState.media = r.data;
          renderExpanded();
          if (config.capsuleComponents.includes("media")) renderCapsule();
        }
      }).catch(() => {});
    } catch (_) {}
  }

  /* ── Capsule Render ─────────────────────────── */
  function renderCapsule() {
    let leftHtml = "";
    let centerHtml = "";
    let rightHtml = "";

    for (const key of config.capsuleComponents) {
      switch (key) {
        case "companion":
          leftHtml += renderCompanionBadge();
          break;
        case "status":
          centerHtml += renderStatusText();
          break;
        case "notifications":
          rightHtml += renderNotificationBadge();
          break;
        case "quickChat":
          rightHtml += renderQuickChatIcon();
          break;
        case "media":
          centerHtml += renderMediaMini();
          break;
        case "system":
          centerHtml += renderSystemMini();
          break;
      }
    }

    if (!leftHtml && config.capsuleComponents.includes("companion")) {
      leftHtml = renderCompanionBadge();
    }
    if (!centerHtml) {
      centerHtml = renderStatusText();
    }
    if (!rightHtml && config.capsuleComponents.includes("notifications")) {
      rightHtml = renderNotificationBadge();
    }

    capsuleLeft.innerHTML = leftHtml;
    capsuleCenter.innerHTML = centerHtml;
    capsuleRight.innerHTML = rightHtml;
  }

  function renderCompanionBadge() {
    const statusColor = uiState.companion.status === "online" ? "var(--di-success)" : "var(--di-text-tertiary)";
    return `
      <div class="di-avatar" title="云栖">
        <img class="di-avatar-logo" src="assets/logo.png" alt="云栖">
        <span class="di-avatar-dot" style="background:${statusColor};box-shadow:0 0 6px ${statusColor}"></span>
      </div>
    `;
  }

  function renderStatusText() {
    return `<div class="di-status"><span class="di-status-text">${uiState.statusText}</span></div>`;
  }

  function renderNotificationBadge() {
    const count = uiState.notifications.count;
    if (count <= 0) return `<div class="di-notif-badge"></div>`;
    const display = count > 99 ? "99+" : count;
    return `<div class="di-notif-badge"><span class="di-badge">${display}</span></div>`;
  }

  function renderQuickChatIcon() {
    return `<div class="di-quick-chat-icon">${ICON("ui-chat", 16)}</div>`;
  }

  function renderMediaMini() {
    const m = uiState.media;
    if (m.title) {
      let coverHtml;
      if (m.thumbnail) {
        const thumbUrl = "file:///" + m.thumbnail.replace(/\\/g, "/").replace(/^\/+/, "");
        coverHtml = `<img class="di-media-mini-cover" src="${thumbUrl}" alt="" onerror="this.style.display='none';">`;
      } else {
        coverHtml = ICON("ui-music", 12);
      }
      return `
        <div class="di-media-mini">
          ${coverHtml}
          <span class="di-media-title">${m.title}</span>
        </div>
      `;
    }
    return `<div class="di-status"><span class="di-status-text">${ICON("ui-music", 12)} 未播放</span></div>`;
  }

  function renderSystemMini() {
    return `<div class="di-status"><span class="di-status-text">CPU ${Math.round(uiState.system.cpu)}%</span></div>`;
  }

  /* ── Expanded Render ──────────────────────── */
  function renderExpanded() {
    let html = "";
    for (const key of config.expandedComponents) {
      switch (key) {
        case "quickActions":
          html += renderQuickActions();
          break;
        case "notifList":
          html += renderNotificationList();
          break;
        case "companionDetail":
          html += renderCompanionDetail();
          break;
        case "mediaControl":
          html += renderMediaControl();
          break;
        case "systemStatus":
          html += renderSystemStatus();
          break;
      }
    }
    expandedBody.innerHTML = html;
    bindExpandedEvents();
  }

  function renderQuickActions() {
    const labels = {
      chat: "快捷对话",
      brief: "今日简报",
      cognition: "认知面板",
      settings: "设置",
      calendar: "日程",
      files: "文件",
      restart: "重启后端",
    };
    const items = uiState.quickActions
      .map((k) => ({ key: k, icon: ACTION_ICONS[k], label: labels[k] || k }))
      .filter((x) => x.icon);

    return `
      <div class="di-section">
        <div class="di-section-title">快捷操作</div>
        <div class="di-quick-grid">
          ${items.map((a, i) => `
            <button class="di-quick-item" data-action="${a.key}" style="animation-delay:${i * 30}ms">
              <span class="di-quick-icon">${ICON(a.icon, 20)}</span>
              <span class="di-quick-label">${a.label}</span>
            </button>
          `).join("")}
        </div>
      </div>
    `;
  }

  function renderNotificationList() {
    const items = uiState.notifications.items;
    return `
      <div class="di-section">
        <div class="di-section-title">
          最近消息
          <span class="di-section-count">${items.length}</span>
        </div>
        <div class="di-notif-list">
          ${items.length === 0
            ? `<div class="di-empty">暂无新消息</div>`
            : items.map((n, i) => `
              <div class="di-notif-item" data-index="${i}" style="animation-delay:${i * 40 + 80}ms">
                <span class="di-notif-icon">${n.icon ? ICON(n.icon, 18) : ICON("ui-bell", 18)}</span>
                <div class="di-notif-content">
                  <div class="di-notif-title">${n.title || ""}</div>
                  <div class="di-notif-desc">${n.desc || ""}</div>
                </div>
                <span class="di-notif-time">${n.time || "now"}</span>
              </div>
            `).join("")
          }
        </div>
      </div>
    `;
  }

  function renderCompanionDetail() {
    const moodText = {
      joy: "开心陪伴中",
      neutral: "静静陪着你",
      sad: "有点低落中",
      anger: "气鼓鼓",
      fear: "担心你呢",
    }[uiState.companion.mood] || "陪伴中";

    const together = formatDuration(Date.now() - uiState.companionStartTime);

    return `
      <div class="di-section">
        <div class="di-section-title">云栖状态</div>
        <div class="di-companion-card">
          <div class="di-companion-avatar">
            <img class="di-companion-logo" src="assets/logo.png" alt="云栖">
          </div>
          <div class="di-companion-info">
            <div class="di-companion-name">云栖</div>
            <div class="di-companion-mood">${moodText}</div>
            <div class="di-companion-together">已陪伴 ${together}</div>
          </div>
        </div>
      </div>
    `;
  }

  function renderMediaControl() {
    const m = uiState.media;
    let coverHtml;
    if (m.thumbnail) {
      const thumbUrl = "file:///" + m.thumbnail.replace(/\\/g, "/").replace(/^\/+/, "");
      coverHtml = `
        <div class="di-media-cover-wrap">
          <img class="di-media-cover-img" src="${thumbUrl}" alt=""
               onerror="this.style.display='none';this.nextElementSibling.style.display='flex';">
          <div class="di-media-cover di-media-cover-fallback" style="display:none;">${ICON("ui-music", 22)}</div>
        </div>`;
    } else {
      coverHtml = `<div class="di-media-cover">${ICON("ui-music", 22)}</div>`;
    }
    const progPercent = m.duration > 0 ? Math.min(100, (m.progress / m.duration) * 100) : 0;
    return `
      <div class="di-section">
        <div class="di-section-title">媒体控制</div>
        <div class="di-media-card">
          ${coverHtml}
          <div class="di-media-info">
            <div class="di-media-title">${m.title || "未在播放"}</div>
            <div class="di-media-artist">${m.artist || "—"}</div>
            <div class="di-media-progress">
              <div class="di-media-progress-bar" style="width:${progPercent}%"></div>
            </div>
          </div>
          <div class="di-media-controls">
            <button class="di-media-btn" data-media-action="prev" aria-label="上一首">${ICON("ui-skip-back", 14)}</button>
            <button class="di-media-btn di-media-play" data-media-action="toggle" aria-label="播放/暂停">${m.playing ? ICON("ui-pause", 14) : ICON("ui-play", 14)}</button>
            <button class="di-media-btn" data-media-action="next" aria-label="下一首">${ICON("ui-skip-forward", 14)}</button>
          </div>
        </div>
      </div>
    `;
  }

  function renderSystemStatus() {
    const s = uiState.system;
    return `
      <div class="di-section">
        <div class="di-section-title">系统状态</div>
        <div class="di-system-grid">
          <div class="di-system-card">
            <div class="di-system-icon">${ICON("ui-cpu", 18)}</div>
            <div class="di-system-label">CPU</div>
            <div class="di-system-value">${Math.round(s.cpu)}%</div>
            <div class="di-system-bar"><div class="di-system-bar-fill" style="width:${s.cpu}%"></div></div>
          </div>
          <div class="di-system-card">
            <div class="di-system-icon">${ICON("ui-memory", 18)}</div>
            <div class="di-system-label">内存</div>
            <div class="di-system-value">${Math.round(s.mem)}%</div>
            <div class="di-system-bar"><div class="di-system-bar-fill" style="width:${s.mem}%"></div></div>
          </div>
          <div class="di-system-card">
            <div class="di-system-icon">${ICON("ui-wifi", 18)}</div>
            <div class="di-system-label">网络</div>
            <div class="di-system-value">${Math.round(s.net || 0)} KB/s</div>
            <div class="di-system-bar"><div class="di-system-bar-fill" style="width:${Math.min((s.net || 0) / 5, 100)}%"></div></div>
          </div>
        </div>
      </div>
    `;
  }

  function bindExpandedEvents() {
    expandedBody.querySelectorAll(".di-quick-item").forEach((btn) => {
      btn.addEventListener("click", () => {
        handleQuickAction(btn.dataset.action);
      });
    });

    expandedBody.querySelectorAll(".di-notif-item").forEach((item) => {
      item.addEventListener("click", () => {
        handleNotifClick(item);
      });
    });

    expandedBody.querySelectorAll("[data-media-action]").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        handleMediaAction(btn.dataset.mediaAction);
      });
    });
  }

  /* ── Events ───────────────────────────────── */
  function bindEvents() {
    capsuleEl.addEventListener("click", onCapsuleClick);

    if (config.interaction === "hover" || config.interaction === "both") {
      capsuleEl.addEventListener("mouseenter", onCapsuleMouseEnter);
      capsuleEl.addEventListener("mouseleave", onCapsuleMouseLeave);
    }

    if (config.interaction === "longpress" || config.interaction === "both") {
      capsuleEl.addEventListener("mousedown", onCapsuleMouseDown);
      capsuleEl.addEventListener("mouseup", onCapsuleMouseUp);
      capsuleEl.addEventListener("mouseleave", onCapsuleMouseUp);
    }

    closeBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      collapse();
    });

    window.addEventListener("resize", resizeCanvas);
  }

  function onCapsuleClick(e) {
    if (config.interaction === "hover") return;
    if (state !== "capsule") return;

    const pressDuration = Date.now() - pressStart;
    if (config.interaction === "longpress" && pressDuration < config.longPressDuration) {
      return;
    }

    createRipple(e);
    expand();
    spawnBurstParticles(e.clientX, e.clientY);
  }

  function createRipple(e) {
    const rect = capsuleEl.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const size = Math.max(rect.width, rect.height);
    const ripple = document.createElement("span");
    ripple.className = "di-ripple";
    ripple.style.cssText = `width:${size}px;height:${size}px;left:${x - size / 2}px;top:${y - size / 2}px;`;
    capsuleEl.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
  }

  function onCapsuleMouseEnter() {
    if (config.interaction === "click") return;
    if (state !== "capsule") return;
    hoverTimer = setTimeout(expand, config.hoverDelay);
  }

  function onCapsuleMouseLeave() {
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
  }

  function onCapsuleMouseDown(e) {
    pressStart = Date.now();
    if (config.interaction === "longpress" || config.interaction === "both") {
      pressTimer = setTimeout(() => {
        if (state === "capsule") {
          expand();
          spawnBurstParticles(e.clientX, e.clientY);
        }
      }, config.longPressDuration);
    }
  }

  function onCapsuleMouseUp() {
    if (pressTimer) { clearTimeout(pressTimer); pressTimer = null; }
  }

  /* ── Expand / Collapse ─────────────────────── */
  function expand() {
    if (state !== "capsule") return;
    state = "expanding";
    diEl.classList.add("di--expanding");
    renderExpanded();

    const w = 320;
    const h = estimateExpandedHeight();

    try {
      api?.setState?.(true)?.catch(() => {});
      api?.setSize?.(w, h)?.catch(() => {});
    } catch (_) {}

    setTimeout(() => {
      state = "expanded";
      diEl.classList.remove("di--expanding");
      diEl.classList.add("di--expanded");
      resizeCanvas();
    }, 480);
  }

  function collapse() {
    if (state !== "expanded") return;
    state = "collapsing";
    diEl.classList.add("di--collapsing");
    diEl.classList.remove("di--expanded");

    try { api?.setState?.(false)?.catch(() => {}); } catch (_) {}

    setTimeout(() => {
      state = "capsule";
      diEl.classList.remove("di--collapsing");
      try { api?.setSize?.(200, 36)?.catch(() => {}); } catch (_) {}
      resizeCanvas();
    }, 340);
  }

  function estimateExpandedHeight() {
    const temp = expandedEl.cloneNode(true);
    temp.style.cssText = "position:absolute;visibility:hidden;display:block;width:320px;";
    document.body.appendChild(temp);
    const h = temp.offsetHeight + 12;
    document.body.removeChild(temp);
    // v13.9: lifted cap from 500 -> 580 so the new max-height: 480px body
    // plus ~50px header all fit without clipping the mediaControl row.
    return Math.min(h, 580);
  }

  /* ── Action Handlers ─────────────────────── */
  function handleQuickAction(action) {
    const tabMap = { chat: "chat", brief: "brief", cognition: "cognition", settings: "settings" };
    const tab = tabMap[action];
    if (tab) {
      try { api?.openMain?.(tab)?.catch(() => {}); } catch (_) {}
      collapse();
      return;
    }
    if (action === "restart") {
      if (confirm("确定要重启后端服务吗？\nRestart the backend service?")) {
        try {
          window.aerie?.electron?.system?.restartBackend?.();
        } catch (_) {}
      }
      collapse();
      return;
    }
    collapse();
  }

  function handleNotifClick(item) {
    const idx = parseInt(item.dataset.index, 10);
    item.style.opacity = "0";
    item.style.transform = "translateX(20px)";
    setTimeout(() => {
      if (!isNaN(idx)) {
        uiState.notifications.items.splice(idx, 1);
        uiState.notifications.count = Math.max(0, uiState.notifications.count - 1);
        renderCapsule();
        renderExpanded();
      }
    }, 280);
  }

  function handleMediaAction(action) {
    if (!api) return;
    try {
      if (action === "toggle") {
        api.mediaPlayPause?.().then((r) => {
          if (r?.ok && r.data) {
            uiState.media = r.data;
            renderExpanded();
            renderCapsule();
          }
        }).catch(() => {});
      } else if (action === "next") {
        api.mediaNext?.().catch(() => {});
      } else if (action === "prev") {
        api.mediaPrev?.().catch(() => {});
      }
    } catch (_) {}
  }

  /* ── IPC & SSE ───────────────────────────── */
  function bindIpcListeners() {
    if (!api) return;
    try {
      api.onConfigChange?.((cfg) => {
        if (cfg.theme) applyTheme(cfg.theme);
        if (cfg.interaction) config.interaction = cfg.interaction;
        // v13.9: same defensive guard as loadConfig — only accept arrays
        // that contain every required component, so the default 5-section
        // layout isn't silently replaced by a stale 2-section one.
        const requiredCapsule = ["companion", "media", "notifications"];
        const requiredExpanded = ["quickActions", "mediaControl", "companionDetail", "notifList", "systemStatus"];
        if (Array.isArray(cfg.capsuleComponents) &&
            requiredCapsule.every((k) => cfg.capsuleComponents.includes(k))) {
          config.capsuleComponents = cfg.capsuleComponents;
        }
        if (Array.isArray(cfg.expandedComponents) &&
            requiredExpanded.every((k) => cfg.expandedComponents.includes(k))) {
          config.expandedComponents = cfg.expandedComponents;
        }
        saveConfig();
        renderCapsule();
        renderExpanded();
      });

      api.onNotify?.((data) => {
        if (data.title || data.desc) {
          addNotification(data.title, data.desc, data.icon, data.type);
        }
      });

      api.onSystemStatus?.((data) => {
        if (data) {
          uiState.system = data;
          if (state === "expanded") renderExpanded();
          if (config.capsuleComponents.includes("system")) renderCapsule();
        }
      });

      api.onMediaUpdate?.((data) => {
        if (data) {
          uiState.media = data;
          if (state === "expanded") renderExpanded();
          if (config.capsuleComponents.includes("media")) renderCapsule();
        }
      });

      api.sseSubscribe?.((payload) => {
        handleSseEvent(payload);
      });

      // Calendar reminders may also be forwarded by the main window after it
      // refreshes local calendar events; keep the island in sync with those
      // renderer-originated events as well as SSE events.
      api.onCalendarReminder?.((data) => {
        handleCalendarReminder(data);
      });
      api.onCalendarEventRefresh?.((data) => {
        const reminder = data?.reminder || data?.event || data;
        handleCalendarReminder(reminder);
      });
    } catch (_) {}
  }

  function handleCalendarReminder(data) {
    if (!data) return;
    const title = data.title || data.summary || data.name || "日程提醒";
    const timeText = data.timeText || data.startText || data.time || data.startTime || data.start_time || "";
    const location = data.location ? ` · ${data.location}` : "";
    const desc = data.desc || data.description || (timeText ? `${timeText}${location}` : "你有一个日程即将开始");
    addNotification(title, desc, data.icon || "ui-calendar", "calendar_reminder");
    api?.systemNotify?.({ title: `日程提醒：${title}`, body: desc })?.catch?.(() => {});
  }

  function handleSseEvent(payload) {
    if (!payload?.type) return;
    switch (payload.type) {
      case "proactive_message":
      case "chat_message":
        if (payload.data?.text) {
          addNotification(
            payload.data.title || "云栖",
            payload.data.text,
            payload.data.icon || "ui-bell",
            payload.type
          );
        }
        break;
      case "calendar_reminder":
        handleCalendarReminder(payload.data || payload);
        break;
      case "emotion_update":
      case "mood_change":
        if (payload.data?.mood) {
          uiState.companion.mood = payload.data.mood;
          renderCapsule();
          if (state === "expanded") renderExpanded();
        }
        break;
      case "companion_status":
        if (payload.data) {
          Object.assign(uiState.companion, payload.data);
          renderCapsule();
        }
        break;
      case "status_update":
        if (payload.data?.text) {
          uiState.statusText = payload.data.text;
          renderCapsule();
        }
        break;
    }
  }

  function addNotification(title, desc, icon, type) {
    uiState.notifications.items.unshift({
      icon: icon || "ui-bell",
      title: title || "",
      desc: desc || "",
      time: "刚刚",
      type: type || "",
    });
    if (uiState.notifications.items.length > 20) {
      uiState.notifications.items.pop();
    }
    uiState.notifications.count++;
    renderCapsule();
    if (state === "expanded") renderExpanded();

    if (state === "capsule") {
      diEl.classList.add("di--notif");
      setTimeout(() => diEl.classList.remove("di--notif"), 600);
    }
  }

  /* ── Particle System ─────────────────────── */
  const PARTICLE_TYPES = ["circle", "heart", "star", "sparkle"];

  function spawnBurstParticles(x, y) {
    const rect = diEl.getBoundingClientRect();
    const px = x - rect.left;
    const py = y - rect.top;
    const count = 16;
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.4;
      const speed = 2.5 + Math.random() * 3.5;
      particles.push({
        x: px, y: py,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 1.5,
        size: 3 + Math.random() * 4,
        life: 1,
        decay: 0.015 + Math.random() * 0.02,
        type: PARTICLE_TYPES[Math.floor(Math.random() * PARTICLE_TYPES.length)],
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.1,
      });
    }
    if (!animFrame) animateParticles();
  }

  function startBreathParticles() {
    setInterval(() => {
      if (state !== "capsule") return;
      const rect = capsuleEl.getBoundingClientRect();
      const diRect = diEl.getBoundingClientRect();
      const px = rect.left - diRect.left + rect.width / 2 + (Math.random() - 0.5) * 30;
      const py = rect.top - diRect.top + rect.height / 2;
      particles.push({
        x: px, y: py,
        vx: (Math.random() - 0.5) * 0.6,
        vy: -0.4 - Math.random() * 0.6,
        size: 2 + Math.random() * 2.5,
        life: 1,
        decay: 0.006 + Math.random() * 0.005,
        type: Math.random() > 0.7 ? "heart" : "sparkle",
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.05,
      });
      if (!animFrame) animateParticles();
    }, 600);
  }

  function animateParticles() {
    const dpr = window.devicePixelRatio || 1;
    ctx.clearRect(0, 0, particlesCanvas.width / dpr, particlesCanvas.height / dpr);
    particles = particles.filter((p) => p.life > 0);
    for (const p of particles) {
      p.x += p.vx;
      p.y += p.vy;
      p.vy += 0.04;
      p.vx *= 0.99;
      p.rotation += p.rotationSpeed;
      p.life -= p.decay;
      ctx.save();
      ctx.globalAlpha = p.life;
      ctx.fillStyle = getAccentColor();
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rotation);
      ctx.scale(p.life, p.life);
      drawParticle(p.type, p.size);
      ctx.restore();
    }
    if (particles.length > 0) {
      animFrame = requestAnimationFrame(animateParticles);
    } else {
      animFrame = null;
    }
  }

  function drawParticle(type, size) {
    switch (type) {
      case "heart": drawHeart(size); break;
      case "star": drawStar(size); break;
      case "sparkle": drawSparkle(size); break;
      default:
        ctx.beginPath();
        ctx.arc(0, 0, size, 0, Math.PI * 2);
        ctx.fill();
    }
  }

  function drawHeart(size) {
    const s = size * 0.6;
    ctx.beginPath();
    ctx.moveTo(0, s * 0.3);
    ctx.bezierCurveTo(-s, -s * 0.4, -s * 1.2, s * 0.3, 0, s);
    ctx.bezierCurveTo(s * 1.2, s * 0.3, s, -s * 0.4, 0, s * 0.3);
    ctx.fill();
  }

  function drawStar(size) {
    const outer = size, inner = size * 0.45, spikes = 5;
    let rot = -Math.PI / 2;
    ctx.beginPath();
    for (let i = 0; i < spikes * 2; i++) {
      const r = i % 2 === 0 ? outer : inner;
      const x = Math.cos(rot) * r;
      const y = Math.sin(rot) * r;
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      rot += Math.PI / spikes;
    }
    ctx.closePath();
    ctx.fill();
  }

  function drawSparkle(size) {
    const s = size;
    ctx.beginPath();
    ctx.moveTo(0, -s);
    ctx.lineTo(s * 0.2, -s * 0.2);
    ctx.lineTo(s, 0);
    ctx.lineTo(s * 0.2, s * 0.2);
    ctx.lineTo(0, s);
    ctx.lineTo(-s * 0.2, s * 0.2);
    ctx.lineTo(-s, 0);
    ctx.lineTo(-s * 0.2, -s * 0.2);
    ctx.closePath();
    ctx.fill();
  }

  function getAccentColor() {
    return getComputedStyle(diEl).getPropertyValue("--di-accent").trim() || "#66abff";
  }

  /* ── Utils ────────────────────────────────── */
  function formatDuration(ms) {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}小时${m}分`;
    if (m > 0) return `${m}分${sec}秒`;
    return `${sec}秒`;
  }

  /* ── Public API ───────────────────────────── */
  window.DynamicIsland = {
    expand, collapse, applyTheme,
    notify: addNotification,
    updateStatus(text) { uiState.statusText = text; renderCapsule(); },
    setConfig(cfg) {
      Object.assign(config, cfg);
      saveConfig();
      if (cfg.theme) applyTheme(cfg.theme);
      renderCapsule();
      renderExpanded();
    },
    getState() { return state; },
    getConfig() { return { ...config }; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
