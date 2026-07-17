"use strict";
/* Aerie · 云栖 v10.1.1 — Floating Ball Logic
 * 仿豆包悬浮球 · 拖动吸附边缘 + 隐藏 + 右键菜单 + 外观自定义
 * 设计参考：
 *   1) 豆包桌面悬浮球（拖动吸附 / 右键菜单 / 设置开关）
 *   2) Dify AI 智能体悬浮球（菜单跟随 + 智能避让）
 *   3) HiyokoHelper（Tauri 悬浮助手：alwaysOnTop + activationPolicy）
 *
 * 核心交互（5 项）：
 *   - 拖动：5px 阈值防误触；松手时吸附最近 x 边
 *   - 吸附后：缩为细条 / 半透明；hover 或点击边缘 tab 唤出
 *   - 单击：打开主窗口（清未读）
 *   - 双击：直接打开对话浮窗（快捷入口）
 *   - 右键：上下文菜单（10 个常用操作）
 *   - 设置：外观 + 行为实时预览，关闭后保存
 */

(function () {
  "use strict";

  // ==================== 常量 ====================
  const SNAP_MARGIN = 10; // 距离边缘的最小距离（px）
  const DRAG_THRESHOLD = 5; // 拖动判定阈值（px）· 防误触
  const DOCKED_PEEK = 6; // 吸附后露出的边距（px）· 方便鼠标 hover 唤出
  const SETTINGS_KEY = "aerie_floating_ball_settings_v101_1";
  const EDGE_TAB_HIDE_DELAY = 240;

  const THEMES = {
    aerie: { grad1: "#66abff", grad2: "#007aff", glow: "rgba(0,122,255,0.45)" },
    dawn: { grad1: "#ffb199", grad2: "#ff7a7a", glow: "rgba(255,122,122,0.45)" },
    forest: { grad1: "#6dd5a3", grad2: "#1f9d68", glow: "rgba(31,157,104,0.45)" },
    lavender: { grad1: "#b09dff", grad2: "#7c5cff", glow: "rgba(124,92,255,0.45)" },
    amber: { grad1: "#ffd58a", grad2: "#ff9d2e", glow: "rgba(255,157,46,0.45)" },
    ink: { grad1: "#6a7488", grad2: "#2a3142", glow: "rgba(42,49,66,0.45)" },
  };

  const DEFAULT_SETTINGS = {
    glyph: "栖",
    theme: "aerie",
    size: 56,
    opacity: 100,
    snapToEdge: true,
    autoHide: true,
    showBadge: true,
  };

  // ==================== DOM 引用 ====================
  const ball = document.getElementById("floating-ball");
  const ballGlyph = document.getElementById("ball-glyph");
  const badge = document.getElementById("ball-badge");
  const contextMenu = document.getElementById("ball-context-menu");
  const settingsPanel = document.getElementById("ball-settings");
  const edgeTab = document.getElementById("ball-edge-tab");
  const edgeTabGlyph = edgeTab ? edgeTab.querySelector(".edge-tab-glyph") : null;
  const previewBall = document.getElementById("preview-ball");
  const previewGlyph = document.getElementById("preview-glyph");

  if (!ball) {
    console.warn("[floating-ball] #floating-ball not found, aborting init");
    return;
  }

  // ==================== 状态 ====================
  let settings = loadSettings();
  let unread = 0;
  let isDragging = false;
  let isDocked = false; // 是否处于吸附隐藏状态
  let isMenuOpen = false;
  let isSettingsOpen = false;
  let dragStart = null;
  let hasMoved = false;
  let edgeTabHideTimer = null;
  let lastClickTime = 0; // 用于双击检测

  // ==================== 初始化 ====================
  applySettings(settings);
  initPosition();
  attachListeners();

  // ==================== 持久化 ====================
  function loadSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      if (!raw) return { ...DEFAULT_SETTINGS };
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_SETTINGS, ...parsed };
    } catch (err) {
      console.warn("[floating-ball] settings load failed:", err.message);
      return { ...DEFAULT_SETTINGS };
    }
  }

  function saveSettings(s) {
    try {
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(s));
    } catch (err) {
      console.warn("[floating-ball] settings save failed:", err.message);
    }
  }

  // ==================== 应用设置 ====================
  function applySettings(s) {
    if (!s) return;
    settings = { ...settings, ...s };

    // 字符
    if (ballGlyph) ballGlyph.textContent = settings.glyph;
    if (edgeTabGlyph) edgeTabGlyph.textContent = settings.glyph;
    if (previewGlyph) previewGlyph.textContent = settings.glyph;

    // 配色
    const theme = THEMES[settings.theme] || THEMES.aerie;
    document.documentElement.style.setProperty("--ball-grad-1", theme.grad1);
    document.documentElement.style.setProperty("--ball-grad-2", theme.grad2);
    document.documentElement.style.setProperty("--ball-glow", theme.glow);

    // 尺寸
    document.documentElement.style.setProperty("--ball-size", settings.size + "px");
    ball.style.width = settings.size + "px";
    ball.style.height = settings.size + "px";

    // 透明度
    document.documentElement.style.setProperty(
      "--ball-opacity",
      (settings.opacity / 100).toString()
    );
    ball.style.opacity = (settings.opacity / 100).toString();

    // 角标
    if (badge) {
      badge.style.display = settings.showBadge ? "" : "none";
    }

    // 同步面板 UI
    syncSettingsUI();
  }

  function syncSettingsUI() {
    const glyphInput = document.getElementById("glyph-input");
    if (glyphInput) glyphInput.value = settings.glyph;

    document.querySelectorAll(".glyph-chip").forEach((chip) => {
      chip.classList.toggle("active", chip.dataset.glyph === settings.glyph);
    });

    document.querySelectorAll(".theme-chip").forEach((chip) => {
      chip.classList.toggle("active", chip.dataset.theme === settings.theme);
    });

    const sizeSlider = document.getElementById("size-slider");
    const sizeValue = document.getElementById("size-value");
    if (sizeSlider) sizeSlider.value = settings.size;
    if (sizeValue) sizeValue.textContent = settings.size + "px";

    const opacitySlider = document.getElementById("opacity-slider");
    const opacityValue = document.getElementById("opacity-value");
    if (opacitySlider) opacitySlider.value = settings.opacity;
    if (opacityValue) opacityValue.textContent = settings.opacity + "%";

    const snapToggle = document.getElementById("snap-toggle");
    if (snapToggle) snapToggle.checked = settings.snapToEdge;
    const autohideToggle = document.getElementById("autohide-toggle");
    if (autohideToggle) autohideToggle.checked = settings.autoHide;
    const badgeToggle = document.getElementById("badge-toggle");
    if (badgeToggle) badgeToggle.checked = settings.showBadge;
  }

  // ==================== 初始位置 ====================
  function initPosition() {
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const size = settings.size;
    ball.style.left = vw - size - SNAP_MARGIN + "px";
    ball.style.top = Math.round(vh * 0.4) + "px";
    if (edgeTab) {
      edgeTab.classList.add("hidden");
      edgeTab.classList.remove("left", "right");
    }
    isDocked = false;
    ball.classList.remove("docked");
  }

  // ==================== 事件绑定 ====================
  function attachListeners() {
    // 拖动 - 使用 pointerdown / pointermove 兼顾鼠标和触屏
    ball.addEventListener("pointerdown", handlePointerDown);
    document.addEventListener("pointermove", handlePointerMove);
    document.addEventListener("pointerup", handlePointerUp);

    // 单击 / 双击（在 pointerup 中根据位移判定）
    ball.addEventListener("click", handleClick);

    // 右键菜单
    ball.addEventListener("contextmenu", handleContextMenu);

    // 点击外部关闭右键菜单
    document.addEventListener("click", (e) => {
      if (isMenuOpen && !contextMenu.contains(e.target) && !ball.contains(e.target)) {
        closeContextMenu();
      }
      if (isSettingsOpen && !e.target.closest(".settings-panel") && !e.target.closest("[data-action='open-settings']")) {
        // 设置面板由自身 backdrop 处理关闭
      }
    });

    // 边缘 tab 唤出
    if (edgeTab) {
      edgeTab.addEventListener("click", () => {
        if (isDocked) undock();
      });
      edgeTab.addEventListener("mouseenter", () => {
        if (isDocked) undock();
      });
    }

    // 鼠标移出球体进入非 tab 区域 → 延迟隐藏
    ball.addEventListener("mouseleave", () => {
      if (isDocked && settings.autoHide) {
        scheduleEdgeTabHide();
      }
    });

    // 窗口尺寸变化
    window.addEventListener("resize", () => {
      // 重新计算位置保证不出屏
      const rect = ball.getBoundingClientRect();
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      const minVisible = 20;
      const newLeft = Math.max(
        SNAP_MARGIN,
        Math.min(rect.left, vw - settings.size - SNAP_MARGIN)
      );
      const newTop = Math.max(
        SNAP_MARGIN,
        Math.min(rect.top, vh - settings.size - SNAP_MARGIN)
      );
      if (newLeft !== rect.left) ball.style.left = newLeft + "px";
      if (newTop !== rect.top) ball.style.top = newTop + "px";
    });

    // 菜单项点击
    contextMenu.addEventListener("click", (e) => {
      const item = e.target.closest(".menu-item");
      if (!item) return;
      const action = item.dataset.action;
      handleMenuAction(action);
      closeContextMenu();
    });

    // 设置面板交互
    attachSettingsListeners();

    // 监听后端消息
    if (window.aerie && window.aerie.api && window.aerie.api.onMessage) {
      window.aerie.api.onMessage((msg) => {
        if (msg && msg.role === "assistant") {
          incrementUnread();
        }
      });
    }
  }

  // ==================== 拖动处理 ====================
  function handlePointerDown(e) {
    if (e.button !== 0 && e.pointerType === "mouse") {
      // 鼠标右键交给 contextmenu 事件处理
      return;
    }
    e.preventDefault();
    isDragging = true;
    hasMoved = false;
    ball.classList.add("dragging");
    const rect = ball.getBoundingClientRect();
    dragStart = {
      clientX: e.clientX,
      clientY: e.clientY,
      offsetX: e.clientX - rect.left,
      offsetY: e.clientY - rect.top,
      originLeft: rect.left,
      originTop: rect.top,
    };
    if (isDocked) {
      // 从吸附状态拽出
      undock(false);
    }
  }

  function handlePointerMove(e) {
    if (!isDragging || !dragStart) return;
    const dx = e.clientX - dragStart.clientX;
    const dy = e.clientY - dragStart.clientY;
    const dist = Math.sqrt(dx * dx + dy * dy);
    if (dist > DRAG_THRESHOLD) hasMoved = true;

    if (!hasMoved) return;

    let newLeft = dragStart.originLeft + dx;
    let newTop = dragStart.originTop + dy;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    newLeft = Math.max(SNAP_MARGIN, Math.min(newLeft, vw - settings.size - SNAP_MARGIN));
    newTop = Math.max(SNAP_MARGIN, Math.min(newTop, vh - settings.size - SNAP_MARGIN));
    ball.style.left = newLeft + "px";
    ball.style.top = newTop + "px";

    // 拖动中预览边缘吸附目标
    if (settings.snapToEdge) {
      previewSnapTarget(newLeft);
    }
  }

  function handlePointerUp(e) {
    if (!isDragging) return;
    isDragging = false;
    ball.classList.remove("dragging");
    if (!dragStart) return;

    if (hasMoved && settings.snapToEdge) {
      snapToNearestEdge();
    } else if (!hasMoved) {
      // 点击事件交由 click 事件处理
    }
    dragStart = null;
  }

  // ==================== 边缘吸附 ====================
  function snapToNearestEdge() {
    const rect = ball.getBoundingClientRect();
    const vw = window.innerWidth;
    const distToLeft = rect.left;
    const distToRight = vw - rect.right;
    const finalLeft = distToLeft < distToRight
      ? SNAP_MARGIN
      : vw - settings.size - SNAP_MARGIN;
    ball.style.left = finalLeft + "px";
    ball.dataset.edge = finalLeft < vw / 2 ? "left" : "right";

    if (settings.autoHide) {
      // 吸附后延迟 dock，模拟豆包收起效果
      setTimeout(() => dock(), 200);
    }
  }

  function previewSnapTarget(currentLeft) {
    const vw = window.innerWidth;
    ball.style.boxShadow = currentLeft < vw / 2
      ? "0 0 0 9999px rgba(0,0,0,0.02)"
      : "0 0 0 9999px rgba(0,0,0,0.02)";
  }

  function dock() {
    if (!isDragging) {
      isDocked = true;
      ball.classList.add("docked");
      const edge = ball.dataset.edge || "right";
      if (edgeTab) {
        edgeTab.classList.remove("hidden");
        edgeTab.classList.add(edge);
        edgeTab.style.top = ball.getBoundingClientRect().top + "px";
        edgeTab.style.height = settings.size + "px";
      }
    }
  }

  function undock(showEdgeTab = true) {
    isDocked = false;
    ball.classList.remove("docked");
    ball.style.opacity = (settings.opacity / 100).toString();
    if (edgeTab) {
      if (showEdgeTab) {
        scheduleEdgeTabHide();
      } else {
        edgeTab.classList.add("hidden");
      }
    }
  }

  function scheduleEdgeTabHide() {
    clearTimeout(edgeTabHideTimer);
    edgeTabHideTimer = setTimeout(() => {
      if (edgeTab && !isDocked) {
        edgeTab.classList.add("hidden");
      }
    }, 3000);
  }

  // ==================== 点击处理 ====================
  function handleClick(e) {
    if (hasMoved) {
      hasMoved = false;
      return;
    }
    const now = Date.now();
    if (now - lastClickTime < 320) {
      // 双击 → 打开对话浮窗
      lastClickTime = 0;
      openQuickChat();
      return;
    }
    lastClickTime = now;
    // 延迟处理单击（避免和双击冲突）
    setTimeout(() => {
      if (lastClickTime === now) {
        openMain();
      }
    }, 320);
  }

  function openMain() {
    unread = 0;
    updateBadge();
    if (isDocked) undock();
    sendIpc("ui:open-main", { source: "floating-ball", action: "click" });
    if (window.aerie && window.aerie.electron && window.aerie.electron.openMain) {
      window.aerie.electron.openMain();
    }
  }

  function openQuickChat() {
    if (isDocked) undock();
    sendIpc("ui:open-quick-chat", { source: "floating-ball", action: "double-click" });
    if (window.aerie && window.aerie.electron && window.aerie.electron.openQuickChat) {
      window.aerie.electron.openQuickChat();
    }
  }

  // ==================== 右键菜单 ====================
  function handleContextMenu(e) {
    e.preventDefault();
    if (isDocked) undock();
    positionContextMenu(e.clientX, e.clientY);
    openContextMenu();
  }

  function positionContextMenu(x, y) {
    if (!contextMenu) return;
    contextMenu.style.visibility = "hidden";
    contextMenu.classList.remove("hidden");
    const rect = contextMenu.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let finalX = x;
    let finalY = y;
    if (x + rect.width > vw - 8) {
      finalX = vw - rect.width - 8;
    }
    if (y + rect.height > vh - 8) {
      finalY = vh - rect.height - 8;
    }
    finalX = Math.max(8, finalX);
    finalY = Math.max(8, finalY);
    contextMenu.style.left = finalX + "px";
    contextMenu.style.top = finalY + "px";
    contextMenu.style.visibility = "visible";
  }

  function openContextMenu() {
    if (!contextMenu) return;
    contextMenu.classList.remove("hidden");
    isMenuOpen = true;
  }

  function closeContextMenu() {
    if (!contextMenu) return;
    contextMenu.classList.add("hidden");
    isMenuOpen = false;
  }

  function handleMenuAction(action) {
    switch (action) {
      case "open-main":
        openMain();
        break;
      case "open-quick":
        openQuickChat();
        break;
      case "screenshot-ask":
        sendIpc("ui:screenshot-ask", {});
        if (window.aerie && window.aerie.electron && window.aerie.electron.screenshotAsk) {
          window.aerie.electron.screenshotAsk();
        }
        break;
      case "meeting-note":
        sendIpc("ui:meeting-note", {});
        if (window.aerie && window.aerie.electron && window.aerie.electron.meetingNote) {
          window.aerie.electron.meetingNote();
        }
        break;
      case "quick-summarize":
        sendIpc("ui:quick-summarize", {});
        if (window.aerie && window.aerie.electron && window.aerie.electron.quickSummarize) {
          window.aerie.electron.quickSummarize();
        }
        break;
      case "open-settings":
        openSettings();
        break;
      case "hide-until-restart":
        hideUntilRestart();
        break;
      case "quit":
        sendIpc("ui:quit-app", {});
        if (window.aerie && window.aerie.electron && window.aerie.electron.quit) {
          window.aerie.electron.quit();
        }
        break;
    }
  }

  // ==================== 设置面板 ====================
  function openSettings() {
    if (!settingsPanel) return;
    syncSettingsUI();
    settingsPanel.classList.remove("hidden");
    isSettingsOpen = true;
  }

  function closeSettings() {
    if (!settingsPanel) return;
    settingsPanel.classList.add("hidden");
    isSettingsOpen = false;
  }

  function attachSettingsListeners() {
    if (!settingsPanel) return;

    // 关闭
    settingsPanel.addEventListener("click", (e) => {
      if (e.target.classList.contains("settings-backdrop") ||
          e.target.dataset.action === "close-settings") {
        closeSettings();
      }
    });

    // 字符选择
    settingsPanel.querySelectorAll(".glyph-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        const g = chip.dataset.glyph;
        applySettings({ glyph: g });
      });
    });

    const glyphInput = document.getElementById("glyph-input");
    if (glyphInput) {
      glyphInput.addEventListener("input", (e) => {
        const val = (e.target.value || "").trim().slice(0, 3);
        if (val) applySettings({ glyph: val });
      });
    }

    // 主题
    settingsPanel.querySelectorAll(".theme-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        applySettings({ theme: chip.dataset.theme });
      });
    });

    // 尺寸
    const sizeSlider = document.getElementById("size-slider");
    if (sizeSlider) {
      sizeSlider.addEventListener("input", (e) => {
        const v = parseInt(e.target.value, 10);
        applySettings({ size: v });
      });
    }

    // 透明度
    const opacitySlider = document.getElementById("opacity-slider");
    if (opacitySlider) {
      opacitySlider.addEventListener("input", (e) => {
        const v = parseInt(e.target.value, 10);
        applySettings({ opacity: v });
      });
    }

    // 行为开关
    const snapToggle = document.getElementById("snap-toggle");
    if (snapToggle) {
      snapToggle.addEventListener("change", (e) => {
        applySettings({ snapToEdge: e.target.checked });
      });
    }
    const autohideToggle = document.getElementById("autohide-toggle");
    if (autohideToggle) {
      autohideToggle.addEventListener("change", (e) => {
        applySettings({ autoHide: e.target.checked });
      });
    }
    const badgeToggle = document.getElementById("badge-toggle");
    if (badgeToggle) {
      badgeToggle.addEventListener("change", (e) => {
        applySettings({ showBadge: e.target.checked });
      });
    }

    // 底部按钮
    settingsPanel.querySelectorAll("[data-action='save-settings']").forEach((btn) => {
      btn.addEventListener("click", () => {
        saveSettings(settings);
        closeSettings();
        flash("设置已保存 ✓");
      });
    });

    settingsPanel.querySelectorAll("[data-action='reset-settings']").forEach((btn) => {
      btn.addEventListener("click", () => {
        applySettings(DEFAULT_SETTINGS);
        saveSettings(DEFAULT_SETTINGS);
        flash("已恢复默认设置 ✓");
      });
    });
  }

  // ==================== 未读角标 ====================
  function incrementUnread() {
    if (!settings.showBadge) return;
    unread++;
    updateBadge();
    ball.classList.add("has-unread");
  }

  function updateBadge() {
    if (!badge) return;
    if (unread > 0 && settings.showBadge) {
      badge.textContent = unread > 99 ? "99+" : String(unread);
      badge.classList.remove("hidden");
      badge.classList.remove("bump");
      // 触发回流以重启动画
      void badge.offsetWidth;
      badge.classList.add("bump");
    } else {
      badge.classList.add("hidden");
      ball.classList.remove("has-unread");
    }
  }

  // ==================== 隐藏直到重启 ====================
  function hideUntilRestart() {
    ball.style.display = "none";
    if (edgeTab) edgeTab.classList.add("hidden");
    try {
      sessionStorage.setItem("aerie_ball_hidden_until_restart", "1");
    } catch (_) {}
  }

  // 检查是否需要默认隐藏
  try {
    if (sessionStorage.getItem("aerie_ball_hidden_until_restart") === "1") {
      ball.style.display = "none";
    }
  } catch (_) {}

  // ==================== IPC ====================
  function sendIpc(channel, payload) {
    try {
      if (window.aerie && window.aerie.electron && window.aerie.electron.ipcRenderer) {
        window.aerie.electron.ipcRenderer.send(channel, payload);
      } else if (window.electron && window.electron.ipcRenderer) {
        window.electron.ipcRenderer.send(channel, payload);
      }
    } catch (err) {
      console.warn("[floating-ball] ipc send failed:", err.message);
    }
  }

  // ==================== 短暂提示 ====================
  function flash(text) {
    const tip = document.createElement("div");
    tip.textContent = text;
    tip.style.cssText = [
      "position: fixed",
      "left: 50%",
      "top: 30%",
      "transform: translateX(-50%)",
      "background: rgba(28,30,36,0.94)",
      "color: #f0f1f5",
      "padding: 10px 20px",
      "border-radius: 999px",
      "font-size: 13px",
      "z-index: 99999",
      "backdrop-filter: blur(12px)",
      "-webkit-backdrop-filter: blur(12px)",
      "box-shadow: 0 8px 24px rgba(0,0,0,0.32)",
      "opacity: 0",
      "transition: opacity 0.2s ease",
    ].join(";");
    document.body.appendChild(tip);
    requestAnimationFrame(() => {
      tip.style.opacity = "1";
    });
    setTimeout(() => {
      tip.style.opacity = "0";
      setTimeout(() => tip.remove(), 240);
    }, 1400);
  }

  // ==================== 暴露 API（供外部调用） ====================
  window.aerieBall = {
    incrementUnread,
    resetUnread: () => { unread = 0; updateBadge(); },
    openSettings,
    show: () => { ball.style.display = ""; },
    hide: () => { ball.style.display = "none"; },
    applySettings,
    getSettings: () => ({ ...settings }),
  };
})();
