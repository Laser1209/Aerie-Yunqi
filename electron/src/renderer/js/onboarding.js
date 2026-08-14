"use strict";
/* ============================================================
   Aerie · 云栖 — 首次使用新手教程（OnboardingController）
   分步：API → 人设 → 快捷键 → 其它设置 → 使用指南（WIKI）
   由 app.js 在后端就绪后调用 maybeShow() 决定是否弹出。
   规则：
   - localStorage.aerie_onboarding_done === "1" 时不显示
   - 未配置 API 时强制显示、不可跳过，第一步定位 API 设置
   - 已配置 API 时可跳过 / 点击背景或 Esc 关闭
   ============================================================ */

window.OnboardingController = class OnboardingController {
  constructor() {
    this.storageKey = "aerie_onboarding_done";
    this.shownKey = "aerie_onboarding_shown_version";
    this.root = null;
    this.card = null;
    this.wiki = null;
    this._built = false;
    this._iconUse = null;
    this._title = null;
    this._subtitle = null;
    this._dots = null;
    this._body = null;
    this._prev = null;
    this._primary = null;
    this._wikiFrame = null;
    this.skipBtn = null;
    this.closeBtn = null;

    this.visible = false;
    this.skippable = false; // API 已配置后才允许跳过 / 关闭
    this.hasApiKey = false;
    this.current = 0;
    this.wikiOpen = false;

    this._onKeydown = this._onKeydown.bind(this);

    this.steps = [
      {
        key: "api",
        icon: "icon-ui-settings",
        title: "设置 AI 服务",
        subtitle: "先让 Aerie 学会说话：选择服务商并填入 API Key。",
        nav: () => this._navigateSettings("apikey"),
        body: () =>
          '<p class="onb-p">已为你打开 <b>设置 → API Key</b>。点击右上角的「＋ 添加模型」按钮，选择 AI 服务商并填入你的 API Key，保存后回来校验。</p>'
          + '<p class="onb-hint">密钥只保存在本地，不会上传到任何地方。</p>'
          + '<p class="onb-hint">想让她发图 / 生成图片？生图需要单独的专属 API（<code>IMAGE_GEN_*</code>），和对话 AI 的 Key 是分开的。</p>'
          + '<div class="onb-status" id="onb-api-status"></div>',
        primary: { label: "我已填好 API Key", action: () => this._verifyApiKey() },
      },
      {
        key: "persona",
        icon: "icon-ui-flower",
        title: "设置第一个角色",
        subtitle: "在「人设」面板里创建 Aerie 的第一个身份。",
        nav: () => this._navigateTab("persona-hub"),
        body: () =>
          '<p class="onb-p">已为你打开 <b>人设（Persona Hub）</b>。你可以先看看预设身份，或创建一个专属人设。</p>'
          + '<p class="onb-hint">角色决定 Aerie 的语气、记忆与行为方式，随时可以回来调整。</p>',
        primary: { label: "下一步", action: () => this.next() },
      },
      {
        key: "shortcuts",
        icon: "icon-ui-mouse",
        title: "常用快捷键",
        subtitle: "记下这几个，日常使用会顺手很多。",
        nav: null,
        body: () => this._renderShortcuts(),
        primary: { label: "下一步", action: () => this.next() },
      },
      {
        key: "settings",
        icon: "icon-ui-heart",
        title: "其它设置",
        subtitle: "主题、开机自启、通知与主动推送，都在「设置」里。",
        nav: () => this._navigateSettings("form"),
        body: () =>
          '<p class="onb-p">已为你打开 <b>设置 → 常用</b>，这里可以调整：</p>'
          + '<ul class="onb-list">'
          + '<li><b>主题</b>：伊塔粉 / 深夜紫 / 樱白 / 海蓝 / 森绿</li>'
          + '<li><b>开机自启</b>：登录系统后自动启动 Aerie</li>'
          + '<li><b>主动推送</b>：允许 Aerie 主动关心你，可设置每日次数与间隔</li>'
          + '</ul>'
          + '<p class="onb-hint">「她」的样子（名字 / 头像 / 称呼）也在这里设置。</p>',
        primary: { label: "下一步", action: () => this.next() },
      },
      {
        key: "wiki",
        icon: "icon-ui-book-open",
        title: "使用指南",
        subtitle: "完整的功能说明都收在 WIKI 里。",
        nav: null,
        body: () =>
          '<p class="onb-p">打开完整的《Aerie · 云栖使用指南》，从对话、记忆到灵动岛一网打尽。</p>'
          + '<div class="onb-wiki-actions">'
          + '<button type="button" class="btn btn-secondary" id="onb-open-wiki">'
          + '<svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-book-open"/></svg>打开完整指南'
          + '</button></div>',
        primary: { label: "完成教程", action: () => this._finish() },
      },
    ];
  }

  init() {
    this.root = document.getElementById("onboarding-root");
    if (!this.root) return;
    this._buildDom();
  }

  /* 后端就绪后由 app.js 调用，判断是否弹出教程 */
  async maybeShow(version) {
    if (this.visible || this._isDone() || this._isShown(version)) return;

    let hasKey = false;
    try {
      const r = await this._selfCheck();
      hasKey = !!(r && r.data && r.data.has_api_key);
    } catch (_) {
      hasKey = false;
    }
    this.hasApiKey = hasKey;
    this.skippable = hasKey; // 已配置 API 即可跳过
    this._markShown(version);
    this.show(0);
  }

  show(step) {
    if (!this.root) this.init();
    this._buildDom();

    this.current = Math.min(Math.max(step || 0, 0), this.steps.length - 1);
    this.visible = true;
    this.root.classList.add("is-visible");
    document.addEventListener("keydown", this._onKeydown);
    this._render();
  }

  next() {
    if (this.current < this.steps.length - 1) {
      this.current += 1;
      this._render();
    } else {
      this._finish();
    }
  }

  prev() {
    if (this.current > 0) {
      this.current -= 1;
      this._render();
    }
  }

  /* 「跳过教程」：写持久化标记并关闭（仅 API 配置后可用） */
  skip() {
    if (!this.skippable) return;
    this._setDone();
    this._hide();
  }

  /* 手动重新打开教程（设置页「开启教程」按钮） */
  reopen() {
    if (this.visible) return;
    this.skippable = true; // 手动打开可随时跳过 / 关闭
    this.show(0);
  }

  _finish() {
    this._setDone();
    this._hide();
  }

  _hide() {
    if (!this.visible) return;
    this.visible = false;
    this.wikiOpen = false;
    if (this.wiki) this.wiki.classList.remove("is-open");
    if (this.root) this.root.classList.remove("is-visible");
    document.removeEventListener("keydown", this._onKeydown);
  }

  /* ── DOM 骨架 ─────────────────────────────────────── */
  _buildDom() {
    if (this._built || !this.root) return;
    this._built = true;

    this.root.innerHTML =
      '<div class="onb-backdrop"></div>'
      + '<aside class="onb-card" role="dialog" aria-label="新手教程">'
      +   '<header class="onb-head">'
      +     '<div class="onb-head-icon"><svg class="icon icon--20" aria-hidden="true"><use id="onb-step-icon" href="#icon-ui-settings"></use></svg></div>'
      +     '<div class="onb-head-text">'
      +       '<h2 class="onb-title" id="onb-title"></h2>'
      +       '<p class="onb-subtitle" id="onb-subtitle"></p>'
      +     '</div>'
      +     '<button type="button" class="onb-head-close" id="onb-close" title="关闭教程" aria-label="关闭教程"><svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-close"></use></svg></button>'
      +   '</header>'
      +   '<div class="onb-dots" id="onb-dots"></div>'
      +   '<div class="onb-body" id="onb-body"></div>'
      +   '<footer class="onb-foot">'
      +     '<button type="button" class="btn btn-secondary" id="onb-prev">上一步</button>'
      +     '<button type="button" class="btn btn-primary" id="onb-primary">下一步</button>'
      +     '<button type="button" class="onb-skip" id="onb-skip">跳过教程</button>'
      +   '</footer>'
      + '</aside>'
      + '<div class="onb-wiki" id="onb-wiki">'
      +   '<header class="onb-wiki-head">'
      +     '<span class="onb-wiki-title"><svg class="icon icon--18" aria-hidden="true"><use href="#icon-ui-book-open"></use></svg>使用指南 · Aerie Wiki</span>'
      +     '<button type="button" class="onb-wiki-close" id="onb-wiki-close"><svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-close"></use></svg>返回教程</button>'
      +   '</header>'
      +   '<iframe id="onb-wiki-frame" title="Aerie 使用指南" data-src="wiki.html"></iframe>'
      + '</div>';

    this.card = this.root.querySelector(".onb-card");
    this._iconUse = this.root.querySelector("#onb-step-icon");
    this._title = this.root.querySelector("#onb-title");
    this._subtitle = this.root.querySelector("#onb-subtitle");
    this._dots = this.root.querySelector("#onb-dots");
    this._body = this.root.querySelector("#onb-body");
    this._prev = this.root.querySelector("#onb-prev");
    this._primary = this.root.querySelector("#onb-primary");
    this.skipBtn = this.root.querySelector("#onb-skip");
    this.closeBtn = this.root.querySelector("#onb-close");
    this.wiki = this.root.querySelector("#onb-wiki");
    this._wikiFrame = this.root.querySelector("#onb-wiki-frame");

    this._prev.addEventListener("click", () => this.prev());
    this.skipBtn.addEventListener("click", () => this.skip());
    this.closeBtn.addEventListener("click", () => this._hide());
    this.root.querySelector("#onb-wiki-close").addEventListener("click", () => this._closeWiki());
  }

  _render() {
    const step = this.steps[this.current];
    if (!step) return;

    if (this._iconUse) this._iconUse.setAttribute("href", "#" + step.icon);
    if (this._title) this._title.textContent = step.title;
    if (this._subtitle) this._subtitle.textContent = step.subtitle;

    this._renderDots();
    this._renderBody();
    this._renderFooter(step);

    if (typeof step.nav === "function") step.nav();
    this._applySkippable();
  }

  _renderDots() {
    if (!this._dots) return;
    this._dots.innerHTML = "";
    this.steps.forEach((_, i) => {
      const d = document.createElement("span");
      d.className = "onb-dot";
      if (i < this.current) d.classList.add("onb-dot--done");
      else if (i === this.current) d.classList.add("onb-dot--active");
      this._dots.appendChild(d);
    });
  }

  _renderBody() {
    if (!this._body) return;
    const step = this.steps[this.current];
    this._body.innerHTML = step.body();

    const openWiki = this._body.querySelector("#onb-open-wiki");
    if (openWiki) openWiki.addEventListener("click", () => this._openWiki());
  }

  _renderFooter(step) {
    if (this._prev) this._prev.style.display = this.current === 0 ? "none" : "";
    if (this._primary) {
      this._primary.textContent = step.primary.label;
      this._primary.disabled = false;
      this._primary.onclick = () => step.primary.action();
    }
  }

  _applySkippable() {
    if (this.skipBtn) this.skipBtn.style.display = this.skippable ? "" : "none";
    if (this.closeBtn) this.closeBtn.style.display = this.skippable ? "" : "none";
  }

  /* ── 步骤 1：校验 API Key ──────────────────────────── */
  async _verifyApiKey() {
    const status = this._body ? this._body.querySelector("#onb-api-status") : null;
    const setStatus = (cls, text) => {
      if (!status) return;
      status.className = "onb-status" + (cls ? " " + cls : "");
      status.textContent = text;
    };

    if (this._primary) this._primary.disabled = true;
    setStatus("", "正在校验…");
    try {
      const r = await this._selfCheck();
      const ok = !!(r && r.data && r.data.has_api_key);
      if (ok) {
        this.hasApiKey = true;
        this.skippable = true;
        this._applySkippable();
        setStatus("is-ok", "已检测到 API Key，校验通过！");
        setTimeout(() => {
          if (this._primary) this._primary.disabled = false;
          this.next();
        }, 700);
      } else {
        if (this._primary) this._primary.disabled = false;
        setStatus("is-err", "还没有检测到 API Key，请确认已保存并稍等片刻再试。");
      }
    } catch (_) {
      if (this._primary) this._primary.disabled = false;
      setStatus("is-err", "校验失败，请确认后端已连接后重试。");
    }
  }

  async _selfCheck() {
    if (!window.aerie || !window.aerie.api || typeof window.aerie.api.request !== "function") {
      throw new Error("api unavailable");
    }
    return await window.aerie.api.request({ method: "GET", path: "/api/self-check" });
  }

  /* ── 导航到现有面板 ───────────────────────────────── */
  _navigateTab(tab) {
    const btn = document.querySelector('.sidebar-tab[data-tab="' + tab + '"]');
    if (btn) btn.click();
  }

  _navigateSettings(mode) {
    this._navigateTab("settings");
    // 等设置面板渲染后再切换子视图（apikey / form）
    setTimeout(() => {
      if (window.settingsPanel && typeof window.settingsPanel._switchMode === "function") {
        try { window.settingsPanel._switchMode(mode); } catch (_) {}
      }
    }, 220);
  }

  /* ── WIKI 覆盖层 ──────────────────────────────────── */
  _openWiki() {
    if (!this.wiki) return;
    if (this._wikiFrame && !this._wikiFrame.getAttribute("src")) {
      this._wikiFrame.setAttribute("src", this._wikiFrame.getAttribute("data-src") || "wiki.html");
    }
    this.wikiOpen = true;
    this.wiki.classList.add("is-open");
  }

  _closeWiki() {
    if (this.wiki) this.wiki.classList.remove("is-open");
    this.wikiOpen = false;
  }

  /* ── 事件处理 ─────────────────────────────────────── */
  _onKeydown(e) {
    if (e.key !== "Escape") return;
    if (this.wikiOpen) { this._closeWiki(); return; }
    if (this.skippable) this._hide();
  }

  /* ── 持久化 ───────────────────────────────────────── */
  _isDone() {
    try { return localStorage.getItem(this.storageKey) === "1"; } catch (_) { return false; }
  }

  _isShown(version) {
    try { return localStorage.getItem(this.shownKey) === version; } catch (_) { return false; }
  }

  _markShown(version) {
    try { localStorage.setItem(this.shownKey, version || ""); } catch (_) {}
  }

  _setDone() {
    try { localStorage.setItem(this.storageKey, "1"); } catch (_) {}
  }

  /* ── 快捷键文案（静态内容 + SVG 雪碧图图标） ────────── */
  _renderShortcuts() {
    return (
      '<div class="onb-shortcuts">'
      + '<div class="onb-shortcut onb-shortcut--primary">'
      +   '<div class="onb-shortcut-icon"><svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-mouse"/></svg></div>'
      +   '<div class="onb-shortcut-text">'
      +     '<span class="onb-shortcut-name"><span class="onb-kbd onb-kbd--alt">ALT</span>穿透灵动岛</span>'
      +     '<span class="onb-shortcut-desc">按住 ALT，鼠标可透过桌面灵动岛，点击其后方的窗口内容。</span>'
      +   '</div>'
      + '</div>'
      + '<div class="onb-shortcut">'
      +   '<div class="onb-shortcut-icon"><svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-message"/></svg></div>'
      +   '<div class="onb-shortcut-text">'
      +     '<span class="onb-shortcut-name"><span class="onb-kbd">Enter</span>发送 · <span class="onb-kbd">Shift</span>+<span class="onb-kbd">Enter</span>换行</span>'
      +     '<span class="onb-shortcut-desc">聊天输入框中回车直接发送，换行用 Shift+Enter。</span>'
      +   '</div>'
      + '</div>'
      + '<div class="onb-shortcut">'
      +   '<div class="onb-shortcut-icon"><svg class="icon icon--16" aria-hidden="true"><use href="#icon-ui-close"/></svg></div>'
      +   '<div class="onb-shortcut-text">'
      +     '<span class="onb-shortcut-name"><span class="onb-kbd">Esc</span>关闭 / 取消</span>'
      +     '<span class="onb-shortcut-desc">关闭弹窗、抽屉，或取消正在引用的消息。</span>'
      +   '</div>'
      + '</div>'
      + '</div>'
    );
  }
};
