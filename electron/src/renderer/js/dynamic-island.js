"use strict";

(function () {
  const diEl = document.getElementById("dynamic-island");
  const capsuleEl = document.getElementById("di-capsule");
  const statusMain = document.getElementById("di-status-main");
  const statusSub = document.getElementById("di-status-sub");
  const avatarImg = document.getElementById("di-avatar");
  const closeBtn = document.getElementById("di-close");
  const expandedEl = document.getElementById("di-expanded");
  const expandedBody = document.getElementById("di-expanded-body");
  const briefPane = expandedEl.querySelector('[data-pane="brief"]');
  const calendarPane = expandedEl.querySelector('[data-pane="calendar"]');
  const particlesCanvas = document.getElementById("di-particles");
  const ctx = particlesCanvas.getContext("2d");

  const api = window.aerie?.dynamicIsland;
  const fallbackLogo = "assets/logo.png";
  // 窗口已固定为最大尺寸（main.js），宽度不再随状态 resize；hover/展开/宽屏
  // 的宽度动画全在窗口内居中完成，消除瞬时裁切与闪烁。
  // 桌面遮挡由「动态鼠标穿透」解决：鼠标不在交互区 → 窗口穿透；进入交互区 →
  // 窗口接收；按住 ALT → 强制穿透（可点到窗口下方的应用）。

  // ── 动态鼠标穿透 + ALT 强制穿透 ──
  let ignoreNow = null;
  let altDown = false;
  let lastX = 0;
  let lastY = 0;

  function isInInteractiveZone(x, y) {
    const B = 24; // 交互区外扩缓冲
    const cap = capsuleEl.getBoundingClientRect();
    if (x >= cap.left - B && x <= cap.right + B && y >= cap.top - B && y <= cap.bottom + B) return true;
    if (diEl.classList.contains("open")) {
      const r = expandedEl.getBoundingClientRect();
      if (x >= r.left - B && x <= r.right + B && y >= r.top - B && y <= r.bottom + B) return true;
    }
    return false;
  }

  function applyIgnore() {
    const ignore = altDown || !isInInteractiveZone(lastX, lastY);
    if (ignore !== ignoreNow) {
      ignoreNow = ignore;
      try { api?.setIgnoreMouse?.(ignore)?.catch(() => {}); } catch (_) {}
    }
  }

  function bindMousePenetration() {
    document.addEventListener("mousemove", (e) => {
      lastX = e.clientX; lastY = e.clientY;
      applyIgnore();
    }, { passive: true });
    window.addEventListener("keydown", (e) => { if (e.key === "Alt") { altDown = true; applyIgnore(); } });
    window.addEventListener("keyup", (e) => { if (e.key === "Alt") { altDown = false; applyIgnore(); } });
    window.addEventListener("blur", () => { altDown = false; applyIgnore(); });
  }

  /* ── 配置 ── */
  const VALID_CAPSULE = new Set(["companion", "status", "notifications", "quickChat", "media", "system"]);
  const VALID_EXPANDED = new Set(["quickActions", "notifList", "companionDetail", "mediaControl", "systemStatus"]);

  let config = {
    theme: "dark",
    interaction: "click",
    hoverDelay: 300,
    longPressDuration: 500,
    // v2: 胶囊默认 3 组件与设置面板一致；展开默认 5 模块（快捷操作/媒体控制/陪伴详情/通知/系统）
    capsuleComponents: ["companion", "status", "notifications"],
    expandedComponents: ["quickActions", "mediaControl", "companionDetail", "notifList", "systemStatus"],
  };

  let uiState = {
    companion: { mood: "joy", status: "online" },
    statusText: "云栖在你身边",
    statusScene: "",
    notifications: { count: 0, items: [] },
    system: { cpu: 0, mem: 0, net: null },
    media: { playing: false, title: "", artist: "", progress: 0, duration: 0, thumbnail: "" },
    companionStartTime: Date.now(),
  };

  let hoverTimer = null;
  let resizeRaf = null;
  let particles = [];
  let animFrame = null;

  const ICON = (name, size = 16) =>
    `<svg class="icon icon--${size}" aria-hidden="true"><use href="#icon-${name}"/></svg>`;

  const ACTION_ICONS = {
    chat: "ui-chat", brief: "ui-file-text", cognition: "ui-brain",
    settings: "ui-settings", calendar: "ui-calendar", files: "ui-folder",
    home: "ui-home", restart: "ui-refresh",
  };

  const MOOD_HALO = {
    joy: "255, 138, 128",      // 珊瑚粉 = 开心/想你
    neutral: "125, 181, 238",  // 天空蓝 = 平静
    sad: "255, 183, 77",       // 琥珀 = 低落
    anger: "244, 114, 92",     // 火红 = 气鼓鼓
    fear: "176, 133, 255",     // 紫 = 担心
  };

  /* ── Init ── */
  function init() {
    loadConfig();
    applyTheme(config.theme);
    setupCanvas();
    bindEvents();
    bindMousePenetration();
    bindIpcListeners();
    fetchInitialData();
    syncAvatar();
    renderCapsule();
    renderExpanded();
  }

  /* ── 配置加载/保存（v2 修复：改为白名单 + 至少 1 项，允许取消勾选） ── */
  function sanitizeComponents(arr, valid) {
    if (!Array.isArray(arr) || arr.length === 0) return null;
    const filtered = arr.filter((k) => valid.has(k));
    return filtered.length > 0 ? filtered : null;
  }

  function loadConfig() {
    try {
      const saved = localStorage.getItem("di_config");
      if (!saved) return;
      const parsed = JSON.parse(saved);
      const safeKeys = ["theme", "interaction", "hoverDelay", "longPressDuration"];
      for (const k of safeKeys) if (parsed[k] !== undefined) config[k] = parsed[k];
      const cap = sanitizeComponents(parsed.capsuleComponents, VALID_CAPSULE);
      if (cap) config.capsuleComponents = cap;
      const exp = sanitizeComponents(parsed.expandedComponents, VALID_EXPANDED);
      if (exp) config.expandedComponents = exp;
    } catch (_) {}
  }

  function saveConfig() {
    try { localStorage.setItem("di_config", JSON.stringify(config)); } catch (_) {}
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
    // rAF 节流：窗口频繁 setBounds 会触发多次 resize，避免反复重设 canvas 造成闪烁
    if (resizeRaf) return;
    resizeRaf = requestAnimationFrame(() => {
      resizeRaf = null;
      const rect = diEl.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      particlesCanvas.width = rect.width * dpr;
      particlesCanvas.height = rect.height * dpr;
      ctx.scale(dpr, dpr);
    });
  }

  /* ── 头像同步（设置页 AI 头像 → 灵动岛） ── */
  let avatarRetry = 0;
  function syncAvatar() {
    if (!avatarImg) return;
    // 后端可能在 Electron 启动早期尚未就绪 → 加载失败时带重试，避免误回退默认 logo
    avatarImg.onerror = () => {
      if (avatarRetry < 5) {
        avatarRetry++;
        setTimeout(() => {
          try {
            api?.getAvatarUrl?.().then((r) => { if (r?.ok && r.url) avatarImg.src = r.url; }).catch(() => {});
          } catch (_) {}
        }, 1500);
      } else {
        avatarImg.src = fallbackLogo;
      }
    };
    try {
      api?.getAvatarUrl?.().then((r) => {
        if (r?.ok && r.url) avatarImg.src = r.url;
      }).catch(() => {});
    } catch (_) {}
  }

  function fetchInitialData() {
    if (!api) return;
    try {
      api.getSystemStatus?.().then((r) => {
        if (r?.ok && r.data) { uiState.system = r.data; renderCapsule(); }
      }).catch(() => {});
      api.mediaGetState?.().then((r) => {
        if (r?.ok && r.data) { uiState.media = r.data; renderExpanded(); renderCapsule(); syncMediaTick(); }
      }).catch(() => {});
    } catch (_) {}
  }

  /* ── 胶囊渲染 ── */
  function renderCapsule() {
    const leftEl = document.getElementById("di-capsule-left");
    const rightEl = document.getElementById("di-capsule-right");
    let left = "";
    let right = "";
    for (const key of config.capsuleComponents) {
      switch (key) {
        case "companion":
          left += `<span class="avatar" aria-hidden="true"><img class="avatar-logo" src="${avatarImg ? avatarImg.src : fallbackLogo}" alt=""></span>`;
          break;
        case "notifications":
          right += uiState.notifications.count > 0
            ? `<span class="badge">${uiState.notifications.count > 99 ? "99+" : uiState.notifications.count}</span>`
            : "";
          break;
        case "quickChat":
          right += `<span class="cap-quick" data-action="chat" title="快捷对话" role="button" tabindex="0">${ICON("ui-chat", 16)}</span>`;
          break;
      }
    }
    if (leftEl) leftEl.innerHTML = left;
    if (rightEl) rightEl.innerHTML = right;
    // 快捷对话：点击直接唤起主窗口聊天（v2 修复：不再是无响应的死图标）
    rightEl?.querySelector(".cap-quick")?.addEventListener("click", (e) => {
      e.stopPropagation();
      handleQuickAction("chat");
    });

    // 中间区：动态优先级（谁在工作谁优先），与勾选顺序无关：
    //   未读消息 > 播放中的媒体 > 系统状态 > 状态文字 > 兜底
    // 未播放的媒体不参与（不占位），未勾选的组件不参与。
    let center = "";
    const comps = config.capsuleComponents;
    if (comps.includes("notifications") && uiState.notifications.count > 0) {
      center = renderNotifMini();
    } else if (comps.includes("media") && uiState.media.title) {
      center = renderMediaMini();
    } else if (comps.includes("system")) {
      center = renderSystemMini();
    } else if (comps.includes("status")) {
      center = renderStatusText();
    } else {
      center = renderStatusText();
    }
    if (!center) center = renderStatusText();
    const plainCenter = center.replace(/<[^>]*>/g, "");
    if (center.includes("cap-media")) {
      statusMain.textContent = uiState.media.title || "";
      statusSub.textContent = uiState.media.artist ? `正在播放 · ${uiState.media.artist}` : "";
    } else if (center.includes("cap-notif")) {
      statusMain.textContent = plainCenter.trim();
      statusSub.textContent = "";
    } else if (plainCenter.includes("CPU")) {
      statusMain.textContent = plainCenter.trim();
      statusSub.textContent = "";
    } else {
      statusMain.textContent = uiState.statusText;
      statusSub.textContent = uiState.statusScene;
    }
  }

  function renderStatusText() {
    const moodMap = { joy: "开心", neutral: "平静", sad: "低落", anger: "气鼓鼓", fear: "担心" };
    const mood = moodMap[uiState.companion.mood] || "";
    return `<span class="cap-status">${uiState.statusText}${mood ? ` · ${mood}` : ""}</span>`;
  }

  function renderMediaMini() {
    const m = uiState.media;
    if (m.title) return `<span class="cap-media">${ICON("ui-music", 12)}${m.title}</span>`;
    return "";
  }

  function renderNotifMini() {
    const n = uiState.notifications;
    const latest = (n.items && n.items[0] && (n.items[0].title || n.items[0].desc)) || "";
    const text = latest || `${n.count} 条新消息`;
    return `<span class="cap-status cap-notif">${ICON("ui-bell", 12)}${escapeHtml(text)}</span>`;
  }

  function renderSystemMini() {
    return `<span class="cap-status">CPU ${Math.round(uiState.system.cpu)}%</span>`;
  }

  /* ── 展开面板渲染（窄屏 5 模块 + 宽屏简报/日程骨架） ── */
  function renderExpanded() {
    let html = "";
    for (const key of config.expandedComponents) {
      switch (key) {
        case "quickActions": html += renderQuickActions(); break;
        case "notifList": html += renderNotifList(); break;
        case "companionDetail": html += renderCompanionDetail(); break;
        case "mediaControl": html += renderMediaControl(); break;
        case "systemStatus": html += renderSystemStatus(); break;
      }
    }
    expandedBody.innerHTML = html;
    renderWidePane(briefPane, "brief");
    renderWidePane(calendarPane, "calendar");
    bindExpandedEvents();
  }

  function renderQuickActions() {
    const labels = {
      chat: "快捷对话", brief: "今日简报", cognition: "认知面板",
      settings: "设置", calendar: "日程", files: "文件", restart: "重启后端",
    };
    const items = (config.quickActions || ["chat", "brief", "cognition", "calendar"])
      .map((k) => ({ key: k, icon: ACTION_ICONS[k], label: labels[k] || k }))
      .filter((x) => x.icon);
    return `
      <section class="card">
        <h2 class="card-title">快捷操作</h2>
        <div class="quick">
          ${items.map((a, i) => `
            <button type="button" data-action="${a.key}" style="animation-delay:${i * 30}ms">
              <span class="ic">${ICON(a.icon, 20)}</span>
              <span class="lb">${a.label}</span>
            </button>`).join("")}
        </div>
      </section>`;
  }

  function renderCompanionDetail() {
    const moodText = { joy: "开心陪伴中", neutral: "静静陪着你", sad: "有点低落中", anger: "气鼓鼓", fear: "担心你呢" }[uiState.companion.mood] || "陪伴中";
    return `
      <section class="card companion">
        <span class="av"><img src="${avatarImg ? avatarImg.src : fallbackLogo}" alt="云栖头像"></span>
        <div class="info">
          <div class="nm">云栖 <span class="mood">· ${moodText}</span></div>
          <div class="line">${uiState.companion.line || "想和你说说话。"}</div>
          <div class="since">已陪伴 ${formatDuration(Date.now() - uiState.companionStartTime)} · 此刻${uiState.statusScene ? " " + uiState.statusScene : ""}</div>
        </div>
      </section>`;
  }

  function renderMediaControl() {
    const m = uiState.media;
    const prog = m.duration > 0 ? Math.min(100, (m.progress / m.duration) * 100) : 0;
    const cover = m.thumbnail
      ? `<div class="cover"><img src="file:///${m.thumbnail.replace(/\\/g, "/").replace(/^\/+/, "")}" alt="" onerror="this.style.display='none'">${ICON("ui-music", 20)}</div>`
      : `<div class="cover">${ICON("ui-music", 20)}</div>`;
    return `
      <section class="card">
        <h2 class="card-title">正在播放</h2>
        <div class="media">
          ${cover}
          <div class="mi">
            <div class="t">${m.title || "未在播放"}</div>
            <div class="a">${m.artist || "—"}</div>
            <div class="track">
              <span class="now">${fmt(m.progress)}</span>
              <span class="bar" data-media-seek="1" title="拖动/点击定位"><i style="width:${prog}%"></i></span>
              <span class="tot">${fmt(m.duration)}</span>
            </div>
          </div>
          <div class="ctl">
            <button type="button" data-media-action="prev" aria-label="上一首">${ICON("ui-skip-back", 14)}</button>
            <button type="button" class="play" data-media-action="toggle" aria-label="播放/暂停">${m.playing ? ICON("ui-pause", 14) : ICON("ui-play", 14)}</button>
            <button type="button" data-media-action="next" aria-label="下一首">${ICON("ui-skip-forward", 14)}</button>
          </div>
        </div>
      </section>`;
  }

  function renderSystemStatus() {
    const s = uiState.system;
    return `
      <section class="card">
        <h2 class="card-title">此刻系统</h2>
        <div class="sys">
          <div class="cell"><span class="k">${ICON("ui-cpu", 10)} CPU</span><span class="v">${Math.round(s.cpu)}<small>%</small></span><span class="g"><i></i></span></div>
          <div class="cell"><span class="k">${ICON("ui-memory", 10)} 内存</span><span class="v">${Math.round(s.mem)}<small>%</small></span><span class="g"><i></i></span></div>
          <div class="cell"><span class="k">${ICON("ui-wifi", 10)} 网络</span><span class="v">${Number.isFinite(s.net) ? Math.round(s.net) + "<small>KB/s</small>" : "--"}</span><span class="g"><i></i></span></div>
        </div>
      </section>`;
  }

  function renderNotifList() {
    const items = uiState.notifications.items;
    return `
      <section class="card">
        <h2 class="card-title">最近消息 <span class="card-count">${items.length}</span></h2>
        <div class="notifs">
          ${items.length === 0
            ? `<div class="empty">暂无新消息</div>`
            : items.map((n, i) => `
              <div class="item" data-index="${i}">
                <span class="ic">${n.icon ? ICON(n.icon, 12) : ICON("ui-bell", 12)}</span>
                <div class="body"><div class="t">${escapeHtml(n.title || "")}</div><div class="d">${escapeHtml(n.desc || "")}</div></div>
                <span class="tm">${n.time || "now"}</span>
              </div>`).join("")}
        </div>
      </section>`;
  }

  /* 宽屏右栏：简报/日程（G5 接后端数据；失败/未就绪时显示友好占位） */
  function renderWidePane(pane, type) {
    if (!pane) return;
    if (type === "brief") {
      pane.innerHTML = `
        <div class="pane-head">
          <h2 class="pt">${ICON("ui-file-text", 14)}今日简报</h2>
          <button type="button" class="back" data-back>回窄屏</button>
        </div>
        <div class="pane-body" data-pane-body="brief">
          <div class="tx">简报由云栖按今天的世界与日程生成，稍后就在这里出现。</div>
        </div>`;
    } else {
      pane.innerHTML = `
        <div class="pane-head">
          <h2 class="pt">${ICON("ui-calendar", 14)}今日日程</h2>
          <button type="button" class="back" data-back>回窄屏</button>
        </div>
        <div class="pane-body" data-pane-body="calendar">
          <div class="tx">日程与主窗口保持同步。</div>
        </div>`;
    }
    loadWidePaneData(type);
  }

  async function loadWidePaneData(type) {
    if (!api?.api) return;
    try {
      const path = type === "brief" ? "/api/brief/today" : "/api/calendar/events";
      const r = await api.api({ path });
      if (!r?.ok) return;
      const body = paneBody(type);
      if (!body) return;
      if (type === "brief") body.innerHTML = renderBriefData(r.data);
      else body.innerHTML = renderCalendarData(r.data);
    } catch (_) {}
  }

  function paneBody(type) {
    return expandedEl.querySelector(`[data-pane-body="${type}"]`);
  }

  function renderBriefData(data) {
    const b = data?.brief || {};
    const wx = b.weather && (b.weather.temperature !== undefined || b.weather.description)
      ? `<div class="wx">
          <span class="wx-emoji">${b.weather.icon || "☀️"}</span>
          <div>
            <div class="tm">${b.weather.temperature !== undefined ? `${b.weather.temperature}°` : "--"}</div>
            <div class="ds">${escapeHtml(String(b.weather.description || "天气未知"))}${b.weather.city ? ` · ${escapeHtml(b.weather.city)}` : ""}</div>
          </div>
        </div>` : "";
    const greet = b.greeting ? `<div class="tx">${escapeHtml(String(b.greeting))}</div>` : "";
    // ai_news 为 [{title,summary,url,...},...] 数组，取前 3 条标题
    const newsArr = Array.isArray(b.ai_news) ? b.ai_news : (b.ai_news ? [b.ai_news] : []);
    const news = newsArr.length
      ? `<div class="tx">${newsArr.slice(0, 3).map((n) => escapeHtml(String((n && (n.title || n.summary)) || "")).slice(0, 60)).filter(Boolean).join(" · ")}</div>`
      : "";
    const todos = Array.isArray(b.todos) && b.todos.length
      ? `<div class="tx">待办 · ${b.todos.length} 项<br>${b.todos.map((t) => `· ${escapeHtml(String(t.title || t.text || ""))}`).join("<br>")}</div>`
      : "";
    return wx + greet + news + todos || `<div class="tx">今天还没有简报，稍后再来看看。</div>`;
  }

  function renderCalendarData(data) {
    const events = Array.isArray(data?.events) ? data.events : [];
    if (!events.length) return `<div class="tx">今天没有日程安排。</div>`;
    const fmtTime = (v) => {
      const s = String(v || "");
      return s.length >= 5 ? s.slice(0, 5) : s;
    };
    return events.slice(0, 6).map((e) => `
      <div class="ev">
        <span class="ht">${fmtTime(e.start_time || e.start || e.time || "")}</span>
        <span class="ln"></span>
        <div class="dt">
          <div class="n">${escapeHtml(String(e.title || e.summary || "日程"))}</div>
          ${e.location ? `<div class="d">${escapeHtml(String(e.location))}</div>` : ""}
        </div>
      </div>`).join("");
  }

  function bindExpandedEvents() {
    expandedBody.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => handleQuickAction(btn.dataset.action));
    });
    expandedBody.querySelectorAll(".notifs .item").forEach((item) => {
      item.addEventListener("click", () => handleNotifClick(item));
    });
    expandedBody.querySelectorAll("[data-media-action]").forEach((btn) => {
      btn.addEventListener("click", (e) => { e.stopPropagation(); handleMediaAction(btn.dataset.mediaAction); });
    });
    expandedBody.querySelectorAll("[data-media-seek]").forEach((bar) => {
      bar.addEventListener("click", (e) => {
        e.stopPropagation();
        const rect = bar.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        handleMediaSeek(Math.round((uiState.media.duration || 0) * ratio));
      });
    });
    [briefPane, calendarPane].forEach((pane) => {
      if (!pane) return;
      pane.querySelector("[data-back]")?.addEventListener("click", () => leaveWide());
    });
  }

  /* ── 展开/收起 ── */
  function open() {
    capsuleEl.classList.add("open");
    diEl.classList.add("open");
    expandedEl.classList.remove("collapsing");
    expandedEl.style.display = "";
    capsuleEl.setAttribute("aria-expanded", "true");
    try { api?.setState?.(true)?.catch(() => {}); } catch (_) {}
    syncMediaTick();
    applyIgnore();
  }

  function close() {
    capsuleEl.classList.remove("open");
    diEl.classList.remove("open");
    diEl.classList.remove("wide");
    expandedEl.classList.remove("wide");
    leaveWide(true);
    capsuleEl.setAttribute("aria-expanded", "false");
    try { api?.setState?.(false)?.catch(() => {}); } catch (_) {}
    stopMediaTick();
    expandedEl.classList.add("collapsing");
    setTimeout(() => {
      expandedEl.classList.remove("collapsing");
      expandedEl.style.display = "none";
      applyIgnore();
    }, 340);
  }

  function enterWide(type) {
    capsuleEl.classList.add("open");
    diEl.classList.add("open");
    diEl.classList.add("wide");
    expandedEl.classList.add("wide");
    expandedEl.classList.remove("collapsing");
    expandedEl.style.display = "";
    [briefPane, calendarPane].forEach((p) => { if (p) p.hidden = p.dataset.pane !== type; });
    applyIgnore();
  }

  function leaveWide(silent) {
    diEl.classList.remove("wide");
    expandedEl.classList.remove("wide");
    [briefPane, calendarPane].forEach((p) => { if (p) p.hidden = true; });
    if (!silent) applyIgnore();
  }

  /* ── 事件 ── */
  function bindEvents() {
    capsuleEl.addEventListener("click", () => {
      if (capsuleEl.classList.contains("open")) { close(); return; }
      spawnBurstParticles();
      open();
    });
    capsuleEl.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        capsuleEl.classList.contains("open") ? close() : open();
      }
    });
    closeBtn.addEventListener("click", (e) => { e.stopPropagation(); close(); });
    // hover 展开（interaction=hover/both）
    capsuleEl.addEventListener("mouseenter", onCapsuleMouseEnter);
    capsuleEl.addEventListener("mouseleave", onCapsuleMouseLeave);
    window.addEventListener("resize", resizeCanvas);
    // 点击屏幕外 → 自动回弹
    document.addEventListener("pointerdown", (e) => {
      if (e.target.closest(".di-inner")) return;
      if (diEl.classList.contains("open")) close();
    });
    // 窗口失焦 → 自动回弹
    window.addEventListener("blur", () => { if (diEl.classList.contains("open")) close(); });
  }

  function onCapsuleMouseEnter() {
    if (capsuleEl.classList.contains("open")) return;
    // click 模式：hover 拉长由 CSS 完成，窗口恒宽无需 resize（无裁切/闪烁）
    // hover/both 模式：延迟展开
    if (config.interaction === "hover" || config.interaction === "both") {
      hoverTimer = setTimeout(open, config.hoverDelay);
    }
  }
  function onCapsuleMouseLeave() {
    if (hoverTimer) { clearTimeout(hoverTimer); hoverTimer = null; }
  }

  /* ── 动作 ── */
  function handleQuickAction(action) {
    const tabMap = { chat: "chat", brief: "brief", cognition: "cognition", settings: "settings", calendar: "calendar" };
    if (action === "restart") {
      try { window.aerie?.electron?.system?.restartBackend?.(); } catch (_) {}
      close();
      return;
    }
    if (action === "brief" || action === "calendar") {
      enterWide(action === "brief" ? "brief" : "calendar");
      return;
    }
    const tab = tabMap[action];
    if (tab) { try { api?.openMain?.(tab)?.catch(() => {}); } catch (_) {} }
    close();
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
          if (r?.ok && r.data) { uiState.media = r.data; renderExpanded(); renderCapsule(); syncMediaTick(); }
        }).catch(() => {});
      } else if (action === "next") {
        api.mediaNext?.().catch(() => {});
      } else if (action === "prev") {
        api.mediaPrev?.().catch(() => {});
      }
    } catch (_) {}
  }

  function handleMediaSeek(targetSec) {
    if (!api || !Number.isFinite(targetSec) || targetSec < 0) return;
    // 立即本地更新进度提供即时反馈；SMTC 回包后再同步真实状态。
    uiState.media.progress = targetSec;
    updateMediaProgressDom();
    api.mediaSeek?.(targetSec).then((r) => {
      if (r?.ok && r.data) { uiState.media = r.data; renderExpanded(); renderCapsule(); syncMediaTick(); }
    }).catch(() => {});
  }

  function updateMediaProgressDom() {
    const m = uiState.media;
    const bar = expandedBody.querySelector(".media .bar i");
    const now = expandedBody.querySelector(".media .now");
    const tot = expandedBody.querySelector(".media .tot");
    if (bar) bar.style.width = (m.duration > 0 ? Math.min(100, (m.progress / m.duration) * 100) : 0) + "%";
    if (now) now.textContent = fmt(m.progress);
    if (tot) tot.textContent = fmt(m.duration);
  }

  let mediaTickTimer = null;
  function startMediaTick() {
    stopMediaTick();
    mediaTickTimer = setInterval(() => {
      if (!uiState.media.playing || !diEl.classList.contains("open")) return;
      uiState.media.progress += 1;
      updateMediaProgressDom();
    }, 1000);
  }
  function stopMediaTick() {
    if (mediaTickTimer) { clearInterval(mediaTickTimer); mediaTickTimer = null; }
  }
  function syncMediaTick() {
    if (uiState.media.playing && diEl.classList.contains("open")) startMediaTick();
    else stopMediaTick();
  }

  /* ── IPC & SSE ── */
  function bindIpcListeners() {
    if (!api) return;
    try {
      api.onConfigChange?.((cfg) => {
        if (!cfg) return;
        if (cfg.theme) applyTheme(cfg.theme);
        if (cfg.interaction) config.interaction = cfg.interaction;
        if (cfg.avatarUrl) avatarImg.src = cfg.avatarUrl;
        const cap = sanitizeComponents(cfg.capsuleComponents, VALID_CAPSULE);
        if (cap) config.capsuleComponents = cap;
        const exp = sanitizeComponents(cfg.expandedComponents, VALID_EXPANDED);
        if (exp) config.expandedComponents = exp;
        saveConfig();
        renderCapsule();
        renderExpanded();
      });

      api.onNotify?.((data) => {
        if (data && (data.title || data.desc)) addNotification(data.title, data.desc, data.icon, data.type);
      });

      api.onSystemStatus?.((data) => {
        if (data) { uiState.system = data; if (diEl.classList.contains("open")) renderExpanded(); renderCapsule(); }
      });

      api.onMediaUpdate?.((data) => {
        if (data) { uiState.media = data; if (diEl.classList.contains("open")) renderExpanded(); renderCapsule(); syncMediaTick(); }
      });

      api.sseSubscribe?.((payload) => handleSseEvent(payload));

      api.onCalendarReminder?.((data) => handleCalendarReminder(data));
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

  const seenNotifyEventIds = new Set();

  function handleSseEvent(payload) {
    if (!payload?.type) return;
    switch (payload.type) {
      case "proactive_message":
      case "chat_message": {
        const data = payload.data || payload;
        if (data.text) {
          const eid = payload.event_id || data.event_id;
          if (eid) {
            if (seenNotifyEventIds.has(eid)) return;
            seenNotifyEventIds.add(eid);
            if (seenNotifyEventIds.size > 800) seenNotifyEventIds.delete(seenNotifyEventIds.values().next().value);
          }
          addNotification(data.title || "云栖", data.text, data.icon || "ui-bell", payload.type);
          if (payload.type === "proactive_message" && data.notify_system) {
            api?.systemNotify?.({ title: data.title || "Aerie · 云栖", body: data.text, scene: data.scene })?.catch?.(() => {});
          }
        }
        break;
      }
      case "calendar_reminder":
        handleCalendarReminder(payload.data || payload);
        break;
      case "emotion_update":
      case "mood_change":
        if (payload.data?.mood) {
          uiState.companion.mood = payload.data.mood;
          applyMoodHalo(payload.data.mood);
          renderCapsule();
          if (diEl.classList.contains("open")) renderExpanded();
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
          if (payload.data?.scene) uiState.statusScene = payload.data.scene;
          renderCapsule();
        }
        break;
    }
  }

  function applyMoodHalo(mood) {
    const rgb = MOOD_HALO[mood];
    if (rgb) diEl.style.setProperty("--di-halo", rgb);
  }

  function addNotification(title, desc, icon, type) {
    uiState.notifications.items.unshift({ icon: icon || "ui-bell", title: title || "", desc: desc || "", time: "刚刚", type: type || "" });
    if (uiState.notifications.items.length > 20) uiState.notifications.items.pop();
    uiState.notifications.count++;
    renderCapsule();
    if (diEl.classList.contains("open")) renderExpanded();
    if (!diEl.classList.contains("open")) {
      diEl.classList.add("notif");
      setTimeout(() => diEl.classList.remove("notif"), 600);
    }
  }

  /* ── 粒子系统 ── */
  const PARTICLE_TYPES = ["circle", "heart", "star", "sparkle"];

  function spawnBurstParticles() {
    const rect = diEl.getBoundingClientRect();
    const cx = rect.width / 2;
    const cy = rect.height / 2;
    for (let i = 0; i < 12; i++) {
      const angle = (Math.PI * 2 * i) / 12 + Math.random() * 0.4;
      const speed = 2 + Math.random() * 3;
      particles.push({
        x: cx, y: cy,
        vx: Math.cos(angle) * speed, vy: Math.sin(angle) * speed - 1.5,
        size: 3 + Math.random() * 4,
        life: 1, decay: 0.015 + Math.random() * 0.02,
        type: PARTICLE_TYPES[Math.floor(Math.random() * PARTICLE_TYPES.length)],
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.1,
      });
    }
    if (!animFrame) animateParticles();
  }

  function animateParticles() {
    const dpr = window.devicePixelRatio || 1;
    ctx.clearRect(0, 0, particlesCanvas.width / dpr, particlesCanvas.height / dpr);
    particles = particles.filter((p) => p.life > 0);
    const accent = getComputedStyle(diEl).getPropertyValue("--di-accent").trim() || "#7db5ee";
    for (const p of particles) {
      p.x += p.vx; p.y += p.vy; p.vy += 0.04; p.vx *= 0.99;
      p.rotation += p.rotationSpeed; p.life -= p.decay;
      ctx.save();
      ctx.globalAlpha = p.life;
      ctx.fillStyle = accent;
      ctx.translate(p.x, p.y);
      ctx.rotate(p.rotation);
      ctx.scale(p.life, p.life);
      drawParticle(p.type, p.size);
      ctx.restore();
    }
    animFrame = particles.length > 0 ? requestAnimationFrame(animateParticles) : null;
  }

  function drawParticle(type, size) {
    ctx.beginPath();
    if (type === "heart") {
      const s = size * 0.6;
      ctx.moveTo(0, s * 0.3);
      ctx.bezierCurveTo(-s, -s * 0.4, -s * 1.2, s * 0.3, 0, s);
      ctx.bezierCurveTo(s * 1.2, s * 0.3, s, -s * 0.4, 0, s * 0.3);
    } else if (type === "star") {
      const outer = size, inner = size * 0.45;
      for (let i = 0; i < 10; i++) {
        const r = i % 2 === 0 ? outer : inner;
        const a = -Math.PI / 2 + (i * Math.PI) / 5;
        i === 0 ? ctx.moveTo(Math.cos(a) * r, Math.sin(a) * r) : ctx.lineTo(Math.cos(a) * r, Math.sin(a) * r);
      }
      ctx.closePath();
    } else if (type === "sparkle") {
      const s = size;
      ctx.moveTo(0, -s); ctx.lineTo(s * 0.2, -s * 0.2); ctx.lineTo(s, 0); ctx.lineTo(s * 0.2, s * 0.2);
      ctx.lineTo(0, s); ctx.lineTo(-s * 0.2, s * 0.2); ctx.lineTo(-s, 0); ctx.lineTo(-s * 0.2, -s * 0.2);
      ctx.closePath();
    } else {
      ctx.arc(0, 0, size, 0, Math.PI * 2);
    }
    ctx.fill();
  }

  /* ── 工具 ── */
  function formatDuration(ms) {
    const s = Math.floor(ms / 1000);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    if (h > 0) return `${h}小时${m}分`;
    if (m > 0) return `${m}分${s % 60}秒`;
    return `${s}秒`;
  }
  function fmt(sec) {
    const s = Math.max(0, Math.floor(sec || 0));
    const m = Math.floor(s / 60);
    return `${m}:${String(s % 60).padStart(2, "0")}`;
  }
  function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  /* ── Public API ── */
  window.DynamicIsland = {
    open, close, applyTheme,
    notify: addNotification,
    updateStatus(text, scene) { uiState.statusText = text; if (scene) uiState.statusScene = scene; renderCapsule(); },
    setConfig(cfg) {
      Object.assign(config, cfg);
      saveConfig();
      if (cfg.theme) applyTheme(cfg.theme);
      renderCapsule();
      renderExpanded();
    },
    getState() { return diEl.classList.contains("open") ? "expanded" : "capsule"; },
    getConfig() { return { ...config }; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
