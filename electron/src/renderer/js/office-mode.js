"use strict";
/* v13.0: Office Mode 办公模式前端控制 */

class OfficeModeController {
  constructor() {
    this._currentMode = "auto";  // chat / office / auto
    this._detectedMode = null;
    this._menuEl = null;
  }

  init() {
    const btn = document.getElementById("chat-office-btn");
    if (!btn) return;

    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      this._toggleMenu(btn);
    });

    // 点击其他地方关闭菜单
    document.addEventListener("click", () => {
      this._hideMenu();
    });

    // 加载当前模式
    this._loadMode();

    // 监听模式变更事件
    if (window.aerie && window.aerie.sse && window.aerie.sse.subscribe) {
      window.aerie.sse.subscribe((ev) => {
        if (ev && ev.event === "office_mode_changed") {
          this._currentMode = (ev.data && ev.data.mode) || "auto";
          this._updateButtonState();
        }
      });
    }
  }

  async _loadMode() {
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/office/mode",
      });
      if (r && r.data) {
        this._currentMode = r.data.mode || "auto";
        this._detectedMode = r.data.detected_mode;
        this._updateButtonState();
      }
    } catch (e) {
      console.warn("load office mode failed:", e);
    }
  }

  _toggleMenu(btn) {
    if (this._menuEl && this._menuEl.classList.contains("office-menu--visible")) {
      this._hideMenu();
    } else {
      this._showMenu(btn);
    }
  }

  _showMenu(btn) {
    if (!this._menuEl) {
      this._menuEl = document.createElement("div");
      this._menuEl.className = "office-menu";
      this._menuEl.innerHTML = this._buildMenuHtml();
      btn.parentElement.appendChild(this._menuEl);

      // 绑定菜单点击
      this._menuEl.addEventListener("click", (e) => {
        e.stopPropagation();
        const item = e.target.closest(".office-menu__item[data-mode]");
        if (item) {
          const mode = item.getAttribute("data-mode");
          this._setMode(mode);
          this._hideMenu();
        }
      });
    }

    // 先更新选中状态
    this._updateMenuSelection();
    requestAnimationFrame(() => {
      this._menuEl.classList.add("office-menu--visible");
    });
  }

  _hideMenu() {
    if (this._menuEl) {
      this._menuEl.classList.remove("office-menu--visible");
    }
  }

  _buildMenuHtml() {
    const modeLabels = {
      auto: "自动识别",
      chat: "聊天模式",
      office: "办公模式",
    };
    const modeDesc = {
      auto: "根据对话内容自动切换",
      chat: "专注陪伴闲聊",
      office: "专业高效，优先用豆包模型",
    };

    return `
      <div class="office-menu__header">模式选择</div>
      <div class="office-menu__item" data-mode="auto">
        <svg class="office-menu__item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/>
          <path d="M21 3v5h-5"/>
        </svg>
        <span>自动识别</span>
      </div>
      <div class="office-menu__item" data-mode="chat">
        <svg class="office-menu__item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
        </svg>
        <span>聊天模式</span>
      </div>
      <div class="office-menu__item" data-mode="office">
        <svg class="office-menu__item-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
          <line x1="16" y1="13" x2="8" y2="13"/>
          <line x1="16" y1="17" x2="8" y2="17"/>
        </svg>
        <span>办公模式</span>
      </div>
      <div class="office-menu__divider"></div>
      <div class="office-menu__info">
        当前：<strong id="office-menu-current">自动</strong><br>
        <span id="office-menu-desc">根据对话内容自动切换</span>
      </div>
    `;
  }

  _updateMenuSelection() {
    if (!this._menuEl) return;
    this._menuEl.querySelectorAll(".office-menu__item").forEach((item) => {
      const mode = item.getAttribute("data-mode");
      item.classList.toggle("office-menu__item--active", mode === this._currentMode);
    });

    const currentEl = this._menuEl.querySelector("#office-menu-current");
    const descEl = this._menuEl.querySelector("#office-menu-desc");
    const labels = { auto: "自动识别", chat: "聊天模式", office: "办公模式" };
    const descs = {
      auto: "根据对话内容自动切换",
      chat: "专注陪伴闲聊",
      office: "专业高效，优先豆包模型",
    };
    if (currentEl) currentEl.textContent = labels[this._currentMode] || this._currentMode;
    if (descEl) descEl.textContent = descs[this._currentMode] || "";
  }

  async _setMode(mode) {
    try {
      await window.aerie.api.request({
        method: "PUT",
        path: "/api/office/mode",
        body: JSON.stringify({ mode }),
        headers: { "Content-Type": "application/json" },
      });
      this._currentMode = mode;
      this._updateButtonState();
    } catch (e) {
      console.warn("set office mode failed:", e);
    }
  }

  _updateButtonState() {
    const btn = document.getElementById("chat-office-btn");
    if (!btn) return;

    const isOffice = this._currentMode === "office";
    btn.setAttribute("aria-pressed", isOffice ? "true" : "false");
    btn.classList.toggle("chat-input-toolbar__btn--office-active", isOffice);

    // 更新 tooltip
    const titles = {
      auto: "自动识别模式",
      chat: "聊天模式",
      office: "办公模式 · 豆包优先",
    };
    btn.title = titles[this._currentMode] || "办公模式";
  }
}

window.OfficeModeController = OfficeModeController;
