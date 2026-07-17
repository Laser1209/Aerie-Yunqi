"use strict";

(function () {
  const diEl = document.getElementById("dynamic-island");
  const capsuleEl = diEl.querySelector(".di-capsule");
  const expandedEl = diEl.querySelector(".di-expanded");
  const closeBtn = document.getElementById("di-close");
  const particlesCanvas = document.getElementById("di-particles");
  const ctx = particlesCanvas.getContext("2d");

  let state = "capsule";
  let config = {
    theme: "dark",
    interaction: "click",
    expandType: "panel",
    hoverDelay: 300,
    longPressDuration: 500,
    capsuleComponents: ["companion", "status", "notifications"],
    expandedComponents: ["quickActions", "notifList"],
  };

  let componentState = {
    companion: { status: "online", mood: "happy" },
    status: { text: "云栖在你身边", sub: "" },
    notifications: { count: 3, items: [] },
    quickActions: { items: ["chat", "brief", "cognition", "settings"] },
    notifList: { items: [] },
    media: { playing: false, title: "", artist: "", progress: 0 },
    system: { cpu: 0, mem: 0, net: 0 },
  };

  let hoverTimer = null;
  let pressTimer = null;
  let pressStart = 0;
  let particles = [];
  let animFrame = null;
  let lastMousePos = { x: 0, y: 0 };

  /* ── Component Registry ─────────────────────── */
  const CapsuleComponents = {
    companion: {
      name: "陪伴状态",
      position: "left",
      render() {
        const s = componentState.companion;
        const moodEmoji = { happy: "🌸", thinking: "💭", sleeping: "💤", busy: "⚡" }[s.mood] || "✨";
        const statusColor = s.status === "online" ? "var(--di-success)" : "var(--di-text-tertiary)";
        return `
          <div class="di-companion">
            <div class="di-avatar">
              <span class="di-avatar-mood">${moodEmoji}</span>
              <span class="di-avatar-dot" style="background:${statusColor};box-shadow:0 0 8px ${statusColor}"></span>
            </div>
          </div>
        `;
      },
    },

    status: {
      name: "状态文字",
      position: "center",
      render() {
        const s = componentState.status;
        return `
          <div class="di-status">
            <span class="di-status-text">${s.text || "云栖在你身边"}</span>
          </div>
        `;
      },
    },

    notifications: {
      name: "消息提醒",
      position: "right",
      render() {
        const count = componentState.notifications.count;
        return `
          <div class="di-notif-badge">
            ${count > 0 ? `<span class="di-badge">${count > 99 ? "99+" : count}</span>` : ""}
          </div>
        `;
      },
    },

    quickChat: {
      name: "快捷对话",
      position: "right",
      render() {
        return `
          <div class="di-quick-chat-icon">
            <span>💬</span>
          </div>
        `;
      },
    },

    system: {
      name: "系统状态",
      position: "center",
      render() {
        const s = componentState.system;
        return `
          <div class="di-system-mini">
            <span class="di-system-item">CPU ${Math.round(s.cpu)}%</span>
          </div>
        `;
      },
    },

    media: {
      name: "媒体控制",
      position: "center",
      render() {
        const s = componentState.media;
        if (!s.playing) return `<div class="di-status"><span class="di-status-text">♪ 未播放</span></div>`;
        return `
          <div class="di-media-mini">
            <span class="di-media-icon">🎵</span>
            <span class="di-media-title">${s.title || "播放中"}</span>
          </div>
        `;
      },
    },
  };

  const ExpandedComponents = {
    quickActions: {
      name: "快捷操作",
      render() {
        const actions = {
          chat: { icon: "💬", label: "快捷对话" },
          brief: { icon: "📋", label: "今日简报" },
          cognition: { icon: "🧠", label: "认知面板" },
          settings: { icon: "⚙️", label: "设置" },
          calendar: { icon: "📅", label: "日程" },
          files: { icon: "📁", label: "文件" },
        };
        const items = componentState.quickActions.items
          .map((k) => actions[k])
          .filter(Boolean);

        return `
          <div class="di-section">
            <div class="di-section-title">快捷操作</div>
            <div class="di-quick-grid">
              ${items
                .map(
                  (a, i) => `
                <button class="di-quick-item" data-action="${componentState.quickActions.items[i]}" style="animation-delay:${i * 30}ms">
                  <span class="di-quick-icon">${a.icon}</span>
                  <span class="di-quick-label">${a.label}</span>
                </button>
              `
                )
                .join("")}
            </div>
          </div>
        `;
      },
    },

    notifList: {
      name: "消息通知",
      render() {
        const items = componentState.notifList.items;
        return `
          <div class="di-section">
            <div class="di-section-title">最近消息</div>
            <div class="di-notif-list">
              ${
                items.length === 0
                  ? `<div class="di-empty">暂无消息</div>`
                  : items
                      .map(
                        (n, i) => `
                <div class="di-notif-item" data-index="${i}" style="animation-delay:${i * 40 + 100}ms">
                  <span class="di-notif-icon">${n.icon || "🔔"}</span>
                  <div class="di-notif-content">
                    <div class="di-notif-title">${n.title || ""}</div>
                    <div class="di-notif-desc">${n.desc || ""}</div>
                  </div>
                  <span class="di-notif-time">${n.time || "now"}</span>
                </div>
              `
                      )
                      .join("")
              }
            </div>
          </div>
        `;
      },
    },

    companionDetail: {
      name: "陪伴详情",
      render() {
        const s = componentState.companion;
        const moodText = { happy: "开心陪伴中", thinking: "在想你呢", sleeping: "休息中", busy: "忙工作中" }[s.mood] || "陪伴中";
        return `
          <div class="di-section">
            <div class="di-section-title">云栖状态</div>
            <div class="di-companion-card">
              <div class="di-companion-avatar">
                <span class="di-companion-emoji">🌸</span>
              </div>
              <div class="di-companion-info">
                <div class="di-companion-name">云栖</div>
                <div class="di-companion-mood">${moodText}</div>
                <div class="di-companion-together">已陪伴 2小时 35分</div>
              </div>
            </div>
          </div>
        `;
      },
    },

    mediaControl: {
      name: "媒体控制",
      render() {
        const s = componentState.media;
        return `
          <div class="di-section">
            <div class="di-section-title">媒体控制</div>
            <div class="di-media-card">
              <div class="di-media-cover">🎵</div>
              <div class="di-media-info">
                <div class="di-media-title">${s.title || "未在播放"}</div>
                <div class="di-media-artist">${s.artist || ""}</div>
                <div class="di-media-progress">
                  <div class="di-media-progress-bar" style="width:${s.progress || 0}%"></div>
                </div>
              </div>
              <div class="di-media-controls">
                <button class="di-media-btn">⏮</button>
                <button class="di-media-btn di-media-play">${s.playing ? "⏸" : "▶"}</button>
                <button class="di-media-btn">⏭</button>
              </div>
            </div>
          </div>
        `;
      },
    },

    systemStatus: {
      name: "系统状态",
      render() {
        const s = componentState.system;
        return `
          <div class="di-section">
            <div class="di-section-title">系统状态</div>
            <div class="di-system-grid">
              <div class="di-system-card">
                <div class="di-system-label">CPU</div>
                <div class="di-system-value">${Math.round(s.cpu)}%</div>
                <div class="di-system-bar"><div class="di-system-bar-fill" style="width:${s.cpu}%"></div></div>
              </div>
              <div class="di-system-card">
                <div class="di-system-label">内存</div>
                <div class="di-system-value">${Math.round(s.mem)}%</div>
                <div class="di-system-bar"><div class="di-system-bar-fill" style="width:${s.mem}%"></div></div>
              </div>
              <div class="di-system-card">
                <div class="di-system-label">网络</div>
                <div class="di-system-value">${s.net || 0} KB/s</div>
                <div class="di-system-bar"><div class="di-system-bar-fill" style="width:${Math.min(s.net / 10, 100)}%"></div></div>
              </div>
            </div>
          </div>
        `;
      },
    },
  };

  /* ── Init ───────────────────────────────────── */
  function init() {
    loadConfig();
    applyTheme(config.theme);
    initDemoData();
    setupCanvas();
    renderAll();
    bindEvents();
    resizeCanvas();
    startBreathParticles();
    bindIpcListeners();
    trySetIgnoreMouse(true);
  }

  function initDemoData() {
    componentState.notifList.items = [
      { icon: "🌸", title: "想你啦", desc: "今天过得怎么样呀～", time: "2m" },
      { icon: "📝", title: "简报已生成", desc: "今日工作简报已准备好", time: "5m" },
      { icon: "📅", title: "日程提醒", desc: "下午3点有个会议", time: "1h" },
    ];
    componentState.notifications.count = 3;
  }

  function renderAll() {
    renderCapsule();
    renderExpanded();
  }

  function renderCapsule() {
    const left = [];
    const center = [];
    const right = [];

    for (const key of config.capsuleComponents) {
      const comp = CapsuleComponents[key];
      if (!comp) continue;
      const html = comp.render();
      if (comp.position === "left") left.push(html);
      else if (comp.position === "right") right.push(html);
      else center.push(html);
    }

    capsuleEl.innerHTML = `
      <div class="di-capsule-left">${left.join("")}</div>
      <div class="di-capsule-center">${center.join("")}</div>
      <div class="di-capsule-right">${right.join("")}</div>
    `;
  }

  function renderExpanded() {
    const sections = config.expandedComponents
      .map((key) => ExpandedComponents[key])
      .filter(Boolean)
      .map((c) => c.render())
      .join("");

    const body = expandedEl.querySelector(".di-expanded-body");
    if (body) {
      body.innerHTML = sections;
    }
  }

  function updateComponent(compKey, data) {
    if (componentState[compKey]) {
      Object.assign(componentState[compKey], data);
    }
    renderAll();
  }

  /* ── Config & Theme ─────────────────────────── */
  function loadConfig() {
    try {
      const saved = localStorage.getItem("di_config");
      if (saved) {
        config = Object.assign(config, JSON.parse(saved));
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

  /* ── Canvas ─────────────────────────────────── */
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

  /* ── Events ─────────────────────────────────── */
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

    diEl.addEventListener("click", (e) => {
      if (e.target.closest(".di-quick-item")) {
        handleQuickAction(e.target.closest(".di-quick-item").dataset.action);
      }
      if (e.target.closest(".di-notif-item")) {
        handleNotifClick(e.target.closest(".di-notif-item"));
      }
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
    ripple.style.width = ripple.style.height = size + "px";
    ripple.style.left = x - size / 2 + "px";
    ripple.style.top = y - size / 2 + "px";

    capsuleEl.appendChild(ripple);
    setTimeout(() => ripple.remove(), 600);
  }

  function onCapsuleMouseEnter() {
    if (config.interaction === "click") return;
    if (state !== "capsule") return;

    hoverTimer = setTimeout(() => {
      expand();
    }, config.hoverDelay);
  }

  function onCapsuleMouseLeave() {
    if (hoverTimer) {
      clearTimeout(hoverTimer);
      hoverTimer = null;
    }
  }

  function onCapsuleMouseDown(e) {
    pressStart = Date.now();
    lastMousePos = { x: e.clientX, y: e.clientY };

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
    if (pressTimer) {
      clearTimeout(pressTimer);
      pressTimer = null;
    }
  }

  /* ── Expand / Collapse ──────────────────────── */
  function expand() {
    if (state !== "capsule") return;
    state = "expanding";
    diEl.classList.add("di--expanding");
    renderExpanded();

    const expandedWidth = 320;
    const expandedHeight = estimateExpandedHeight();

    try {
      if (window.aerie?.dynamicIsland?.setSize) {
        window.aerie.dynamicIsland.setSize(expandedWidth, expandedHeight);
      }
    } catch (_) {}

    setTimeout(() => {
      state = "expanded";
      diEl.classList.remove("di--expanding");
      diEl.classList.add("di--expanded");
      resizeCanvas();
      trySetIgnoreMouse(false);
    }, 480);
  }

  function collapse() {
    if (state !== "expanded") return;
    state = "collapsing";
    diEl.classList.add("di--collapsing");
    diEl.classList.remove("di--expanded");

    setTimeout(() => {
      state = "capsule";
      diEl.classList.remove("di--collapsing");

      try {
        if (window.aerie?.dynamicIsland?.setSize) {
          window.aerie.dynamicIsland.setSize(200, 36);
        }
      } catch (_) {}

      resizeCanvas();
      trySetIgnoreMouse(true);
    }, 340);
  }

  function estimateExpandedHeight() {
    const temp = expandedEl.cloneNode(true);
    temp.style.position = "absolute";
    temp.style.visibility = "hidden";
    temp.style.display = "block";
    temp.style.width = "320px";
    document.body.appendChild(temp);
    const h = temp.offsetHeight + 8;
    document.body.removeChild(temp);
    return Math.min(h, 460);
  }

  function trySetIgnoreMouse(ignore) {
    try {
      if (window.aerie?.dynamicIsland?.setIgnoreMouse) {
        window.aerie.dynamicIsland.setIgnoreMouse(ignore);
      }
    } catch (_) {}
  }

  /* ── Action Handlers ────────────────────────── */
  function handleQuickAction(action) {
    const tabMap = {
      chat: "chat",
      brief: "brief",
      cognition: "cognition",
      settings: "settings",
      calendar: "calendar",
      files: "files",
    };
    const tab = tabMap[action];
    if (tab) {
      try {
        if (window.aerie?.dynamicIsland?.openMain) {
          window.aerie.dynamicIsland.openMain(tab);
        }
      } catch (_) {}
    }
    collapse();
  }

  function handleNotifClick(item) {
    item.style.opacity = "0";
    item.style.transform = "translateX(20px)";
    setTimeout(() => {
      const idx = parseInt(item.dataset.index, 10);
      if (!isNaN(idx)) {
        componentState.notifList.items.splice(idx, 1);
        componentState.notifications.count = Math.max(0, componentState.notifications.count - 1);
        renderAll();
      }
    }, 300);
  }

  /* ── IPC ────────────────────────────────────── */
  function bindIpcListeners() {
    try {
      if (window.aerie?.dynamicIsland?.onConfigChange) {
        window.aerie.dynamicIsland.onConfigChange((cfg) => {
          if (cfg.theme) applyTheme(cfg.theme);
          if (cfg.interaction) config.interaction = cfg.interaction;
          if (cfg.expandType) config.expandType = cfg.expandType;
          if (cfg.capsuleComponents) config.capsuleComponents = cfg.capsuleComponents;
          if (cfg.expandedComponents) config.expandedComponents = cfg.expandedComponents;
          saveConfig();
          renderAll();
        });
      }
    } catch (_) {}

    try {
      if (window.aerie?.dynamicIsland?.onNotify) {
        window.aerie.dynamicIsland.onNotify((data) => {
          if (data.title || data.desc) {
            window.DynamicIsland.notify(data.title, data.desc, data.icon);
          }
        });
      }
    } catch (_) {}

    try {
      if (window.aerie?.dynamicIsland?.sseSubscribe) {
        window.aerie.dynamicIsland.sseSubscribe((payload) => {
          handleSseEvent(payload);
        });
      }
    } catch (_) {}
  }

  function handleSseEvent(payload) {
    if (!payload || !payload.type) return;

    switch (payload.type) {
      case "proactive_message":
      case "chat_message":
        if (payload.data?.text) {
          window.DynamicIsland.notify(
            payload.data.title || "云栖",
            payload.data.text,
            payload.data.icon || "🌸"
          );
        }
        break;
      case "companion_status":
        if (payload.data) {
          updateComponent("companion", payload.data);
        }
        break;
      case "system_status":
        if (payload.data) {
          updateComponent("system", payload.data);
        }
        break;
      case "media_update":
        if (payload.data) {
          updateComponent("media", payload.data);
        }
        break;
    }
  }

  /* ── Particle System ────────────────────────── */
  const PARTICLE_TYPES = ["circle", "heart", "star", "sparkle"];

  function spawnBurstParticles(x, y) {
    const rect = diEl.getBoundingClientRect();
    const px = x - rect.left;
    const py = y - rect.top;

    const count = 16;
    for (let i = 0; i < count; i++) {
      const angle = (Math.PI * 2 * i) / count + Math.random() * 0.4;
      const speed = 2.5 + Math.random() * 3.5;
      const type = PARTICLE_TYPES[Math.floor(Math.random() * PARTICLE_TYPES.length)];
      particles.push({
        x: px,
        y: py,
        vx: Math.cos(angle) * speed,
        vy: Math.sin(angle) * speed - 1.5,
        size: 3 + Math.random() * 4,
        life: 1,
        decay: 0.015 + Math.random() * 0.02,
        color: getAccentColor(),
        type,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.1,
      });
    }

    if (!animFrame) {
      animateParticles();
    }
  }

  function startBreathParticles() {
    setInterval(() => {
      if (state !== "capsule") return;
      const rect = capsuleEl.getBoundingClientRect();
      const diRect = diEl.getBoundingClientRect();
      const px = rect.left - diRect.left + rect.width / 2 + (Math.random() - 0.5) * 30;
      const py = rect.top - diRect.top + rect.height / 2;

      const type = Math.random() > 0.7 ? "heart" : "sparkle";
      particles.push({
        x: px,
        y: py,
        vx: (Math.random() - 0.5) * 0.6,
        vy: -0.4 - Math.random() * 0.6,
        size: 2 + Math.random() * 2.5,
        life: 1,
        decay: 0.006 + Math.random() * 0.005,
        color: getAccentColor(),
        type,
        rotation: Math.random() * Math.PI * 2,
        rotationSpeed: (Math.random() - 0.5) * 0.05,
      });

      if (!animFrame) {
        animateParticles();
      }
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
      ctx.fillStyle = p.color;
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
      case "heart":
        drawHeart(size);
        break;
      case "star":
        drawStar(size);
        break;
      case "sparkle":
        drawSparkle(size);
        break;
      case "circle":
      default:
        ctx.beginPath();
        ctx.arc(0, 0, size, 0, Math.PI * 2);
        ctx.fill();
        break;
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
    const outerR = size;
    const innerR = size * 0.45;
    const spikes = 5;
    let rot = -Math.PI / 2;

    ctx.beginPath();
    for (let i = 0; i < spikes * 2; i++) {
      const r = i % 2 === 0 ? outerR : innerR;
      const x = Math.cos(rot) * r;
      const y = Math.sin(rot) * r;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
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
    const styles = getComputedStyle(diEl);
    return styles.getPropertyValue("--di-accent").trim() || "#66abff";
  }

  /* ── Public API ─────────────────────────────── */
  window.DynamicIsland = {
    expand,
    collapse,
    applyTheme,
    updateComponent,
    renderAll,

    notify(title, desc, icon) {
      componentState.notifList.items.unshift({
        icon: icon || "🔔",
        title: title || "",
        desc: desc || "",
        time: "now",
      });
      componentState.notifications.count++;
      renderAll();

      if (state === "capsule") {
        diEl.classList.add("di--notif");
        setTimeout(() => diEl.classList.remove("di--notif"), 600);
      }
    },

    updateStatus(text) {
      updateComponent("status", { text });
    },

    setConfig(cfg) {
      config = Object.assign(config, cfg);
      saveConfig();
      if (cfg.theme) applyTheme(cfg.theme);
      renderAll();
    },

    getState() {
      return state;
    },

    getConfig() {
      return { ...config };
    },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
