"use strict";
/* Settings panel — Phase 9 Batch 3: dual mode (form + YAML editor) */

class SettingsPanel {
  constructor() {
    this._currentMode = "form"; // "form" | "apikey" | "yaml"
    this._currentYamlFile = "settings.yaml";
    // AI 厂商表（数据来自 GET /api/ai/providers）
    this._providers = [];
    this._availableBuiltins = [];
    this._specialServices = [];
    this._modelRoles = [];
    this._bindableProviders = [];
    this._providerSort = { key: "name", dir: 1 };
    this._drawerState = null; // { mode, id, kind, enabled }
  }

  init() {
    this.load();
    this._initIslandSettings();
    this._initNotifSettings();
    this._initOfficeDir();
    this._initDiagnostics();
    this._initSelfEvolveSwitch();
    // Form view
    document.getElementById("settings-save-btn").addEventListener("click", () => this.save());
    document.getElementById("settings-reset-btn").addEventListener("click", () => this.reset());
    // R6.6: one-click backend restart. Schedules main.py to exit and
    // respawn; the Electron window stays open and the renderer keeps
    // polling /api/health until the new backend is up.
    const restartBtn = document.getElementById("settings-restart-btn");
    if (restartBtn) {
      if (!restartBtn.getAttribute("data-original-title")) {
        restartBtn.setAttribute("data-original-title", restartBtn.title || "");
      }
      restartBtn.addEventListener("click", () => this.restartBackend());
    }
    const restartAppBtn = document.getElementById("settings-restart-app-btn");
    if (restartAppBtn) {
      restartAppBtn.addEventListener("click", () => this.restartApp());
    }
    const reloadConfigBtn = document.getElementById("settings-reload-config-btn");
    if (reloadConfigBtn) {
      reloadConfigBtn.addEventListener("click", () => this.reloadConfig());
    }

    const themeSel = document.getElementById("setting-theme");
    if (themeSel) {
      themeSel.addEventListener("change", (e) => {
        if (window.themeSwitcher) {
          window.themeSwitcher.apply(e.target.value);
        }
      });
    }

    // R7.1: weather-city reset-to-auto button.
    const weatherReset = document.getElementById("setting-weather-reset");
    if (weatherReset) {
      weatherReset.addEventListener("click", () => {
        const inp = document.getElementById("setting-weather-city");
        if (inp) {
          inp.value = "";
          inp.focus();
        }
        const hint = document.getElementById("setting-weather-hint");
        if (hint) {
          hint.textContent = "已清空，保存后将重新 IP 定位 / Cleared, will re-detect on next save.";
        }
      });
    }

    // Block-2 A2: persona block controls
    this._initPersonaControls();

    // Persona 变更联动：在人设中心切换/启用/保存人设后，
    // 刷新设置页"她的样子"（名字/头像/称呼性别）
    window.addEventListener("aerie:persona-updated", () => {
      this.loadPersona();
    });

    // Mode tabs
    document.querySelectorAll(".settings-mode-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        this._switchMode(mode);
      });
    });

    // 首次进入 & 窗口尺寸变化时，同步滑动 pill 的位置/宽度
    requestAnimationFrame(() => this._syncModePill());
    window.addEventListener("resize", () => this._syncModePill());

    // YAML view controls
    const yamlSelect = document.getElementById("yaml-file-select");
    if (yamlSelect) {
      yamlSelect.addEventListener("change", (e) => {
        this._currentYamlFile = e.target.value;
        this.loadYaml();
      });
    }
    const saveBtn = document.getElementById("yaml-save-btn");
    if (saveBtn) saveBtn.addEventListener("click", () => this.saveYaml());
    const reloadBtn = document.getElementById("yaml-reload-btn");
    if (reloadBtn) reloadBtn.addEventListener("click", () => this.loadYaml());
    const backupBtn = document.getElementById("yaml-backup-btn");
    if (backupBtn) backupBtn.addEventListener("click", () => this.backupYaml());

    // API Key view controls
    const reloadApiBtn = document.getElementById("apikey-reload-btn");
    if (reloadApiBtn) reloadApiBtn.addEventListener("click", () => { this.loadEntitlement(); this.loadApiKeys(); this.loadBaiduMap(); });
    const baiduSaveBtn = document.getElementById("baidu-map-save-btn");
    if (baiduSaveBtn) baiduSaveBtn.addEventListener("click", () => this.saveBaiduMap());
    const addProviderBtn = document.getElementById("apikey-add-btn");
    if (addProviderBtn) addProviderBtn.addEventListener("click", () => this._openAddChooser());
    const testAllBtn = document.getElementById("apikey-testall-btn");
    if (testAllBtn) testAllBtn.addEventListener("click", () => this._testAllProviders());
    const rolesSaveBtn = document.getElementById("model-roles-save-btn");
    if (rolesSaveBtn) rolesSaveBtn.addEventListener("click", () => this.saveModelRoles());
    const drawerSaveBtn = document.getElementById("apikey-drawer-save");
    if (drawerSaveBtn) drawerSaveBtn.addEventListener("click", () => this._saveProvider());
    const drawerTestBtn = document.getElementById("apikey-drawer-test");
    if (drawerTestBtn) drawerTestBtn.addEventListener("click", () => this._testDrawerProvider());
    const drawerCancelBtn = document.getElementById("apikey-drawer-cancel");
    if (drawerCancelBtn) drawerCancelBtn.addEventListener("click", () => this._closeProviderDrawer());
    const drawerCloseBtn = document.getElementById("apikey-drawer-close");
    if (drawerCloseBtn) drawerCloseBtn.addEventListener("click", () => this._closeProviderDrawer());
    const drawerMask = document.getElementById("apikey-drawer-mask");
    if (drawerMask) drawerMask.addEventListener("click", () => this._closeProviderDrawer());
    const drawerEyeBtn = document.getElementById("apikey-drawer-eye");
    if (drawerEyeBtn) drawerEyeBtn.addEventListener("click", () => {
      const input = document.getElementById("apikey-drawer-api-key");
      if (input) input.type = input.type === "password" ? "text" : "password";
    });
    const featureReloadBtn = document.getElementById("feature-api-reload-btn");
    if (featureReloadBtn) featureReloadBtn.addEventListener("click", () => this.loadFeatureApis());

    // 模块中心（功能包 .aeriepack）
    this._pluginProgress = new Map();
    const pluginsReloadBtn = document.getElementById("plugins-reload-btn");
    if (pluginsReloadBtn) pluginsReloadBtn.addEventListener("click", () => this.loadPlugins());
    const pluginsLocalBtn = document.getElementById("plugins-install-local-btn");
    if (pluginsLocalBtn) pluginsLocalBtn.addEventListener("click", () => this.installLocalPlugin());
    const pluginsDirBtn = document.getElementById("plugins-open-dir-btn");
    if (pluginsDirBtn) pluginsDirBtn.addEventListener("click", () => {
      if (window.aerie && window.aerie.plugins) window.aerie.plugins.openDir();
    });
    if (window.aerie && window.aerie.plugins && window.aerie.plugins.onProgress) {
      window.aerie.plugins.onProgress((p) => this._onPluginProgress(p));
    }

    // 常用视图：分类折叠 + 右侧快速导航
    this._initFormNav();
  }

  _syncModePill() {
    const tabs = Array.from(document.querySelectorAll(".settings-mode-tab"));
    if (!tabs.length) return;
    const pill = document.querySelector(".settings-mode-tabs__pill");
    if (!pill) return;
    const active = tabs.find((b) => b.classList.contains("active")) || tabs[0];
    if (!active) return;
    const tabsEl = active.parentElement;
    const rectTabs = tabsEl.getBoundingClientRect();
    const rectBtn = active.getBoundingClientRect();
    const leftPad = 5;
    pill.style.width = rectBtn.width + "px";
    pill.style.transform = `translateX(${rectBtn.left - rectTabs.left - leftPad}px)`;
  }

  // ── 常用视图：分类折叠卡片 + 右侧快速导航 ─────────────────
  // 纯前端交互，不修改任何表单控件的 id，save() 不受折叠影响。

  _initFormNav() {
    const formView = document.getElementById("settings-form-view");
    if (!formView) return;
    this._cats = Array.from(formView.querySelectorAll(".settings-category"));
    if (!this._cats.length) return;

    this._collapsedCats = new Set(this._readCollapsedCats());

    this._cats.forEach((sec) => {
      const key = sec.getAttribute("data-settings-cat");
      if (this._collapsedCats.has(key)) {
        sec.classList.add("is-collapsed");
        const toggle = sec.querySelector(".settings-category__toggle");
        if (toggle) toggle.setAttribute("aria-expanded", "false");
      }
      const toggle = sec.querySelector(".settings-category__toggle");
      if (toggle) toggle.addEventListener("click", () => this._toggleCat(key));
    });

    const expandAll = document.getElementById("settings-expand-all");
    if (expandAll) expandAll.addEventListener("click", () => this._setAllCats(false));
    const collapseAll = document.getElementById("settings-collapse-all");
    if (collapseAll) collapseAll.addEventListener("click", () => this._setAllCats(true));

    document.querySelectorAll(".settings-rail__link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        this._jumpToCat(a.getAttribute("data-settings-cat"));
      });
    });

    this._initRailScrollSpy();
    this._updateRailSpy();
    this._syncRailState();
  }

  _toggleCat(key) {
    const sec = document.getElementById("setting-cat-" + key);
    if (!sec) return;
    const willCollapse = !sec.classList.contains("is-collapsed");
    sec.classList.toggle("is-collapsed", willCollapse);
    const toggle = sec.querySelector(".settings-category__toggle");
    if (toggle) toggle.setAttribute("aria-expanded", String(!willCollapse));
    if (willCollapse) {
      this._collapsedCats.add(key);
    } else {
      this._collapsedCats.delete(key);
    }
    this._writeCollapsedCats();
    this._syncRailState();
  }

  _setAllCats(collapsed) {
    this._collapsedCats.clear();
    this._cats.forEach((sec) => {
      const key = sec.getAttribute("data-settings-cat");
      sec.classList.toggle("is-collapsed", collapsed);
      const toggle = sec.querySelector(".settings-category__toggle");
      if (toggle) toggle.setAttribute("aria-expanded", String(!collapsed));
      if (collapsed) this._collapsedCats.add(key);
    });
    this._writeCollapsedCats();
    this._syncRailState();
  }

  _syncRailState() {
    document.querySelectorAll(".settings-rail__link").forEach((a) => {
      const key = a.getAttribute("data-settings-cat");
      a.classList.toggle("is-dimmed", this._collapsedCats.has(key));
    });
  }

  _readCollapsedCats() {
    try {
      const raw = localStorage.getItem("aerie.settings.collapsed");
      return raw ? JSON.parse(raw) : [];
    } catch (_) { return []; }
  }

  _writeCollapsedCats() {
    try {
      localStorage.setItem("aerie.settings.collapsed", JSON.stringify(Array.from(this._collapsedCats)));
    } catch (_) {}
  }

  _jumpToCat(key) {
    const sec = document.getElementById("setting-cat-" + key);
    if (!sec) return;
    // 先展开目标分类，保证跳转后内容可见
    if (this._collapsedCats.has(key)) this._toggleCat(key);
    const panel = document.getElementById("panel-settings");
    if (panel) {
      const panelRect = panel.getBoundingClientRect();
      const secRect = sec.getBoundingClientRect();
      const target = panel.scrollTop + (secRect.top - panelRect.top) - 78;
      panel.scrollTo({ top: Math.max(0, target), behavior: "smooth" });
    }
    document.querySelectorAll(".settings-rail__link").forEach((a) => {
      a.classList.toggle("is-active", a.getAttribute("data-settings-cat") === key);
    });
  }

  // 滚动跟随：高亮当前可见的分类
  _initRailScrollSpy() {
    const panel = document.getElementById("panel-settings");
    if (!panel) return;
    this._spyPending = false;
    panel.addEventListener("scroll", () => {
      if (this._spyPending) return;
      this._spyPending = true;
      requestAnimationFrame(() => {
        this._spyPending = false;
        this._updateRailSpy();
      });
    });
  }

  _updateRailSpy() {
    if (!this._cats || !this._cats.length) return;
    const panel = document.getElementById("panel-settings");
    if (!panel || !panel.classList.contains("active")) return;
    const panelRect = panel.getBoundingClientRect();
    if (panelRect.height <= 0) return;
    const marker = panelRect.top + 128;
    let activeKey = this._cats[0].getAttribute("data-settings-cat");
    for (const sec of this._cats) {
      if (sec.offsetParent === null) continue; // 被折叠时不计入
      const r = sec.getBoundingClientRect();
      if (r.top <= marker && r.bottom >= panelRect.top + 40) {
        activeKey = sec.getAttribute("data-settings-cat");
      }
    }
    document.querySelectorAll(".settings-rail__link").forEach((a) => {
      a.classList.toggle("is-active", a.getAttribute("data-settings-cat") === activeKey);
    });
  }

  _switchMode(mode) {
    this._currentMode = mode;
    document.querySelectorAll(".settings-mode-tab").forEach((b) => {
      const isActive = b.getAttribute("data-mode") === mode;
      b.classList.toggle("active", isActive);
      b.classList.toggle("is-active", isActive);
      b.setAttribute("aria-selected", isActive ? "true" : "false");
    });
    const formView = document.getElementById("settings-form-view");
    const apikeyView = document.getElementById("settings-apikey-view");
    const featureView = document.getElementById("settings-feature-view");
    const pluginsView = document.getElementById("settings-plugins-view");
    const yamlView = document.getElementById("settings-yaml-view");
    if (formView) formView.style.display = mode === "form" ? "" : "none";
    if (apikeyView) apikeyView.style.display = mode === "apikey" ? "" : "none";
    if (featureView) featureView.style.display = mode === "feature" ? "" : "none";
    if (pluginsView) pluginsView.style.display = mode === "plugins" ? "" : "none";
    if (yamlView) yamlView.style.display = mode === "yaml" ? "" : "none";
    this._syncModePill();
    if (mode === "form") {
      this._updateRailSpy();
    } else if (mode === "yaml") {
      this.loadYaml();
    } else if (mode === "apikey") {
      this.loadEntitlement();
      this.loadApiKeys();
      this.loadBaiduMap();
    } else if (mode === "feature") {
      this.loadFeatureApis();
    } else if (mode === "plugins") {
      this.loadPlugins();
    }
  }

  // ── 模块中心：功能包目录 / 安装 / 移除 ─────────────────

  _pluginStateLabel(state) {
    return {
      not_installed: "未安装",
      loaded: "已启用",
      awaiting_restart: "已安装 · 待重启",
      broken: "已损坏",
      incompatible: "不兼容",
    }[state] || state;
  }

  _pluginProgressLabel(phase) {
    return {
      queued: "排队中…",
      downloading: "下载中…",
      verifying: "校验中…",
      installing: "安装中…",
      done: "完成",
      idle: "",
    }[phase] || "";
  }

  _setPluginsStatus(text, tone) {
    const el = document.getElementById("plugins-status");
    if (!el) return;
    el.textContent = text || "";
    el.style.color = tone === "warn"
      ? "var(--warning, #f39c12)"
      : tone === "error"
        ? "var(--danger, #e74c3c)"
        : "var(--text-muted, #999)";
  }

  async loadPlugins() {
    if (!window.aerie || !window.aerie.plugins) {
      this._setPluginsStatus("IPC 不可用", "error");
      return;
    }
    const listEl = document.getElementById("plugins-list");
    if (listEl) listEl.innerHTML = '<div class="plugins-empty">正在读取模块目录…</div>';
    const r = await window.aerie.plugins.catalog();
    if (!r || !r.ok) {
      if (listEl) listEl.innerHTML = "";
      this._setPluginsStatus((r && r.error) || "模块目录不可用", "error");
      return;
    }
    this._pluginCatalog = r;
    this.renderPlugins();
    this._setPluginsStatus(
      r.backendOnline ? "安装 / 移除后请重启后端生效。" : "后端离线：仅显示本地安装状态。",
      r.backendOnline ? "muted" : "warn",
    );
  }

  renderPlugins() {
    const listEl = document.getElementById("plugins-list");
    if (!listEl || !this._pluginCatalog) return;
    const packs = this._pluginCatalog.packs || [];
    listEl.innerHTML = "";

    packs.forEach((pack) => {
      const progress = this._pluginProgress.get(pack.id);
      const card = document.createElement("div");
      card.className = "plugin-card";
      card.dataset.id = pack.id;

      const stateLabel = this._pluginStateLabel(pack.state);
      const sizeText = pack.sizeMb >= 1000
        ? `${(pack.sizeMb / 1000).toFixed(1)} GB`
        : `${pack.sizeMb} MB`;
      // 版本属于已发布产物：未发布目录条目没有版本，已安装时以本地清单为准
      const versionText = pack.installedVersion || pack.version || "";

      const actions = this._renderPluginActions(pack, progress);

      card.innerHTML = `
        <div class="plugin-card__icon">
          <svg class="icon icon--18" aria-hidden="true"><use href="#icon-ui-package"/></svg>
        </div>
        <div class="plugin-card__body">
          <div class="plugin-card__head">
            <span class="plugin-card__name"></span>
            <span class="plugin-card__state plugin-card__state--${pack.state}">${stateLabel}</span>
          </div>
          <div class="plugin-card__desc"></div>
          <div class="plugin-card__meta">
            <span>${sizeText}</span>
            ${versionText ? `<span>v${versionText}</span>` : ""}
            ${pack.error ? `<span class="plugin-card__error" title="${this._escapeAttr(pack.error)}">${this._escapeHtml(pack.error)}</span>` : ""}
          </div>
          ${progress ? `
            <div class="plugin-card__progress">
              <div class="plugin-card__bar"><div class="plugin-card__bar-fill" style="width:${Math.round((progress.percent || 0) * 100)}%"></div></div>
              <span class="plugin-card__progress-label">${this._pluginProgressLabel(progress.phase)} ${Math.round((progress.percent || 0) * 100)}%</span>
            </div>` : ""}
        </div>
        <div class="plugin-card__actions"></div>
      `;
      // bilingual 文本经 textContent 注入，避免手工拼接 HTML
      card.querySelector(".plugin-card__name").textContent =
        `${pack.name.zh} · ${pack.name.en}`;
      card.querySelector(".plugin-card__desc").textContent = pack.summary.zh;
      const actionsSlot = card.querySelector(".plugin-card__actions");
      actions.forEach((btn) => actionsSlot.appendChild(btn));
      listEl.appendChild(card);
    });
  }

  _renderPluginActions(pack, progress) {
    const buttons = [];
    const make = (label, kind, handler, disabled) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = `btn btn-sm ${kind === "primary" ? "btn-primary" : "btn-secondary"} plugin-card__btn`;
      btn.textContent = label;
      btn.disabled = !!disabled;
      btn.addEventListener("click", handler);
      return btn;
    };

    if (progress && progress.phase !== "idle" && progress.phase !== "done") {
      buttons.push(make("取消", "secondary", () => this.cancelPluginInstall(pack.id)));
      return buttons;
    }

    switch (pack.state) {
      case "not_installed":
        if (pack.available) {
          buttons.push(make("安装", "primary", () => this.installPlugin(pack.id)));
        } else {
          buttons.push(make("即将推出", "secondary", () => {}, true));
        }
        break;
      case "loaded":
      case "awaiting_restart":
      case "broken":
      case "incompatible":
        buttons.push(make("移除", "secondary", () => this.removePlugin(pack.id)));
        break;
    }
    return buttons;
  }

  _onPluginProgress(p) {
    if (!p || !p.id) return;
    if (p.phase === "idle" || p.phase === "done") {
      if (p.phase === "done") this._pluginProgress.delete(p.id);
      else this._pluginProgress.set(p.id, p);
    } else {
      this._pluginProgress.set(p.id, p);
    }
    this.renderPlugins();
  }

  async installPlugin(id) {
    this._setPluginsStatus("开始下载…", "muted");
    const r = await window.aerie.plugins.install(id);
    await this.loadPlugins();
    if (r && r.ok) {
      this._setPluginsStatus("安装完成，重启后端后生效。", "warn");
      this._offerRestart();
    } else {
      this._setPluginsStatus((r && r.error) || "安装失败", "error");
    }
  }

  async cancelPluginInstall(id) {
    await window.aerie.plugins.cancel(id);
    this._pluginProgress.delete(id);
    this.renderPlugins();
    this._setPluginsStatus("已取消下载（已下载部分将在下次续传）。", "muted");
  }

  async removePlugin(id) {
    if (!confirm("确定移除该模块吗？\nRemove this module?\n（重启后端后生效 / takes effect after backend restart）")) return;
    const r = await window.aerie.plugins.remove(id);
    await this.loadPlugins();
    if (r && r.ok) {
      this._setPluginsStatus("已移除，重启后端后生效。", "warn");
      this._offerRestart();
    } else {
      this._setPluginsStatus("移除失败", "error");
    }
  }

  async installLocalPlugin() {
    const r = await window.aerie.plugins.installLocal();
    if (r && r.canceled) return;
    await this.loadPlugins();
    if (r && r.ok) {
      this._setPluginsStatus(`本地模块 ${r.id}@${r.version} 已安装，重启后端后生效。`, "warn");
      this._offerRestart();
    } else {
      this._setPluginsStatus((r && r.error) || "本地安装失败", "error");
    }
  }

  _offerRestart() {
    if (confirm("立即重启后端让模块生效吗？\nRestart the backend now?")) {
      this.restartBackend();
    }
  }

  _escapeHtml(text) {
    return String(text || "").replace(/[&<>"']/g, (c) => (
      { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
    ));
  }

  _escapeAttr(text) {
    return this._escapeHtml(text);
  }

  async loadEntitlement() {
    const planEl = document.getElementById("settings-entitlement-plan");
    const summaryEl = document.getElementById("settings-entitlement-summary");
    const dotEl = document.getElementById("settings-entitlement-dot");
    if (!planEl || !summaryEl) return;
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/billing/entitlement" });
      const data = (r && r.data && !r.data.error) ? r.data : null;
      if (!data) throw new Error((r && r.data && r.data.error) || "状态不可用");
      const plan = String(data.plan || "free");
      const pricing = data.pricing || {};
      const usage = data.usage || {};
      const limits = data.limits || {};
      const formatLimit = (value) => value == null ? "不限" : Number(value).toLocaleString("zh-CN");
      const software = Number(pricing.monthly_software_cents || 0) / 100;
      const softwareLabel = software > 0 ? `${software.toFixed(2)} ${pricing.currency || "CNY"}/月` : "0 元/月";
      planEl.textContent = pricing.label || plan;
      planEl.style.color = plan === "free" ? "var(--text-muted,#999)" : "var(--success,#2ecc71)";
      if (dotEl) dotEl.style.background = plan === "free" ? "var(--text-muted,#999)" : "var(--success,#2ecc71)";
      summaryEl.innerHTML = `软件：<strong>${softwareLabel}</strong> · 云调用：<strong>${Number(usage.cloud_calls || 0).toLocaleString("zh-CN")} / ${formatLimit(limits.cloud_calls_month)}</strong> · Token：<strong>${Number(usage.cloud_tokens || 0).toLocaleString("zh-CN")} / ${formatLimit(limits.cloud_tokens_month)}</strong> · 周期：${data.period || "-"}`;
    } catch (e) {
      planEl.textContent = "状态不可用";
      planEl.style.color = "var(--warning,#f39c12)";
      if (dotEl) dotEl.style.background = "var(--warning,#f39c12)";
      summaryEl.textContent = "无法读取本地方案与用量；不会因此阻断聊天或 API 配置。";
    }
  }

  async restartBackend() {
    const st = document.getElementById("settings-status");
    const btn = document.getElementById("settings-restart-btn");
    if (!window.aerie || !window.aerie.electron || !window.aerie.electron.system || !window.aerie.electron.system.restartBackend) {
      if (st) st.textContent = "IPC 不可用";
      return;
    }
    if (!confirm("确定要重启后端服务吗？\nRestart the backend service?")) return;
    if (btn) { btn.disabled = true; }
    if (st) { st.textContent = "正在重启后端…"; st.style.color = "var(--warning, #f39c12)"; }
    try {
      const r = await window.aerie.electron.system.restartBackend();
      if (r && r.error) {
        if (st) { st.textContent = "重启失败: " + r.error; st.style.color = "var(--danger, #e74c3c)"; }
      } else {
        if (st) { st.textContent = "后端重启已调度 / Restart scheduled"; st.style.color = "var(--success, #2ecc71)"; }
      }
    } catch (e) {
      if (st) { st.textContent = "异常: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    } finally {
      setTimeout(() => { if (btn) btn.disabled = false; }, 5000);
    }
  }

  async restartApp() {
    const st = document.getElementById("settings-status");
    const btn = document.getElementById("settings-restart-app-btn");
    if (!window.aerie || !window.aerie.electron || !window.aerie.electron.system || !window.aerie.electron.system.restartApp) {
      if (st) st.textContent = "IPC 不可用";
      return;
    }
    if (!confirm("确定要重启整个应用吗？\nRestart the entire application?")) return;
    if (btn) { btn.disabled = true; }
    if (st) { st.textContent = "正在重启应用…"; st.style.color = "var(--warning, #f39c12)"; }
    try {
      await window.aerie.electron.system.restartApp();
    } catch (e) {
      if (st) { st.textContent = "异常: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
      if (btn) btn.disabled = false;
    }
  }

  async reloadConfig() {
    const st = document.getElementById("settings-status");
    const btn = document.getElementById("settings-reload-config-btn");
    if (!window.aerie || !window.aerie.electron || !window.aerie.electron.system || !window.aerie.electron.system.reloadConfig) {
      if (st) st.textContent = "IPC 不可用";
      return;
    }
    if (btn) { btn.disabled = true; }
    if (st) { st.textContent = "正在热重载配置…"; st.style.color = "var(--warning, #f39c12)"; }
    try {
      const r = await window.aerie.electron.system.reloadConfig();
      if (r && r.error) {
        if (st) { st.textContent = "热重载失败: " + r.error; st.style.color = "var(--danger, #e74c3c)"; }
      } else {
        const results = (r && r.results) || {};
        const reloaded = (results.reloaded || []).join(", ");
        const updated = (results.updated || []).join(", ");
        if (st) {
          st.textContent = "配置已热重载。 " + (reloaded ? "[" + reloaded + "]" : "");
          st.style.color = "var(--success, #2ecc71)";
        }
      }
    } catch (e) {
      if (st) { st.textContent = "异常: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    } finally {
      setTimeout(() => { if (btn) btn.disabled = false; }, 2000);
      setTimeout(() => { if (st) st.textContent = ""; }, 5000);
    }
  }

  // ── AI 厂商表：加载 / 渲染 / 行内操作 ─────────────────
  async loadApiKeys() {
    const st = document.getElementById("apikey-status");
    try {
      if (st) { st.textContent = "加载中…"; st.style.color = "var(--text-muted, #999)"; }
      const [provR, rolesR, bindR] = await Promise.all([
        window.aerie.api.request({ method: "GET", path: "/api/ai/providers" }),
        window.aerie.api.request({ method: "GET", path: "/api/env/model-roles" }),
        window.aerie.api.request({ method: "GET", path: "/api/env/bindable-providers" }),
      ]);
      const pd = (provR && provR.data) || {};
      if (pd.error) throw new Error(pd.error);
      this._providers = pd.providers || [];
      this._availableBuiltins = pd.available_builtins || [];
      this._specialServices = pd.special_services || [];
      const rd = (rolesR && rolesR.data) || {};
      this._modelRoles = rd.roles || [];
      if (Array.isArray(rd.special_services) && rd.special_services.length) {
        this._specialServices = rd.special_services;
      }
      this._bindableProviders = (bindR && bindR.data && bindR.data.providers) || [];
      this._renderApiKeyStatusBar();
      this._renderModelRolesCard();
      this._renderProviderTable();
      this._renderSpecialServices();
      if (st) { st.textContent = ""; }
    } catch (e) {
      if (st) { st.textContent = "加载失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    }
  }

  // 统一请求封装：把非 2xx 的 {error, check} 响应转成异常，便于统一处理。
  async _apiCall(method, path, body) {
    let r;
    try {
      r = await window.aerie.api.request(body === undefined
        ? { method, path }
        : { method, path, body });
    } catch (e) {
      if (!e.status && e.data && e.data.status) e.status = e.data.status;
      throw e;
    }
    const d = (r && r.data) || {};
    if (d && d.error) {
      const err = new Error(d.error);
      err.status = (r && r.status) || 0;
      err.data = d;
      throw err;
    }
    return d;
  }

  // 连通性测试失败可 force 重发：422 或响应体带 check/results 均可强制保存。
  // 主进程 IPC 会把非 2xx 归一成 {status:0, data:{error}}，故再用后端
  // run_provider_check 的失败文案兜底识别，避免误伤 400 参数校验错误。
  _isForceable(err) {
    if (!err) return false;
    if (err.status === 422) return true;
    const d = err.data || {};
    if (d.check && typeof d.check === "object") return true;
    if (Array.isArray(d.results) && d.results.some((r) => r && r.check)) return true;
    return /连通性测试失败|尚未配置有效凭证|鉴权失败|接口或模型不存在|触发限流|服务端错误|网络不可达|请求超时|Base URL 或 API Key 为空/.test(String(err.message || ""));
  }

  _esc(value) {
    return this._escapeHtml(value);
  }

  _setApiKeyStatus(text, tone) {
    const st = document.getElementById("apikey-status");
    if (!st) return;
    st.textContent = text || "";
    st.style.color = tone === "error" ? "var(--danger, #e74c3c)"
      : tone === "warn" ? "var(--warning, #f39c12)"
        : tone === "ok" ? "var(--success, #2ecc71)"
          : "var(--text-muted, #999)";
  }

  _providerKindLabel(kind) {
    return kind === "builtin" ? "内置" : kind === "local_cli" ? "本地 CLI" : "自定义";
  }

  _providerDisplayName(key) {
    if (!key) return "默认";
    const p = this._providers.find((x) => x.id === key || x.key === key)
      || this._bindableProviders.find((x) => x.key === key);
    return p ? (p.name || key) : key;
  }

  _providerStatusInfo(p) {
    if (p.enabled === false) return { text: "已停用", tone: "muted", dot: "var(--text-muted, #999)" };
    const check = p.check || {};
    if (check.ok === true) return { text: "连通正常 " + (check.latency_ms || 0) + "ms", tone: "ok", dot: "var(--success, #2ecc71)" };
    if (check.ok === false) return { text: "测试失败" + (check.http_status ? "(" + check.http_status + ")" : ""), tone: "error", dot: "var(--danger, #e74c3c)" };
    if (p.health_status === "banned") return { text: "余额耗尽", tone: "warn", dot: "var(--warning, #f39c12)" };
    if (p.health_status === "cooldown") return { text: "限流冷却", tone: "warn", dot: "var(--warning, #f39c12)" };
    if (p.balance != null && p.balance !== "") return { text: "余额 ¥" + p.balance, tone: "ok", dot: "var(--success, #2ecc71)" };
    return { text: "未测试", tone: "muted", dot: "var(--text-muted, #999)" };
  }

  _providerStatusColor(tone) {
    return tone === "ok" ? "var(--success, #2ecc71)"
      : tone === "error" ? "var(--danger, #e74c3c)"
        : tone === "warn" ? "var(--warning, #f39c12)"
          : "var(--text-muted, #999)";
  }

  _providerStatusRank(p) {
    if (p.enabled === false) return 4;
    const check = p.check || {};
    if (check.ok === true) return 0;
    if (check.ok === false) return 1;
    if (p.health_status === "banned" || p.health_status === "cooldown") return 2;
    return 3;
  }

  _sortedProviders() {
    const { key, dir } = this._providerSort || { key: "name", dir: 1 };
    const value = (p) => {
      if (key === "kind") return p.kind || "";
      if (key === "status") return this._providerStatusRank(p);
      return String(p.name || p.id || "").toLowerCase();
    };
    return this._providers.slice().sort((a, b) => {
      const va = value(a);
      const vb = value(b);
      if (va < vb) return -dir;
      if (va > vb) return dir;
      return 0;
    });
  }

  _providerRoleTags(p) {
    const tags = [];
    (this._modelRoles || []).forEach((r) => {
      if (r.provider && (r.provider === p.id || r.provider === p.key)) tags.push(r.name || r.key);
    });
    (this._specialServices || []).forEach((s) => {
      if (s.provider && (s.provider === p.id || s.provider === p.key)) tags.push(s.name || s.key);
    });
    return tags;
  }

  _renderApiKeyStatusBar() {
    const countEl = document.getElementById("apikey-online-count");
    if (countEl) {
      const total = this._providers.length;
      const online = this._providers.filter((p) => p.enabled !== false && p.check && p.check.ok === true).length;
      countEl.textContent = "● 在线 " + online + " / 共 " + total;
      countEl.style.color = total === 0 ? "var(--text-muted, #999)"
        : online > 0 ? "var(--success, #2ecc71)" : "var(--danger, #e74c3c)";
    }
    const sumEl = document.getElementById("apikey-role-summary");
    if (!sumEl) return;
    const parts = [];
    (this._modelRoles || []).forEach((r) => {
      if (r.provider) parts.push((r.name || r.key) + " → " + this._providerDisplayName(r.provider));
    });
    (this._specialServices || []).forEach((s) => {
      if (s.model) parts.push((s.name || s.key) + " → " + s.model);
    });
    sumEl.textContent = parts.length ? parts.join(" · ") : "尚未绑定功能点";
  }

  _renderProviderTable() {
    const wrap = document.getElementById("apikey-provider-list");
    if (!wrap) return;
    wrap.innerHTML = "";
    const rows = this._sortedProviders();
    const arrow = (k) => this._providerSort.key === k ? (this._providerSort.dir > 0 ? " ▲" : " ▼") : "";
    const table = document.createElement("table");
    table.className = "apikey-table";
    table.innerHTML = `
      <thead>
        <tr>
          <th class="sortable" data-sort="name">厂商${arrow("name")}</th>
          <th class="sortable" data-sort="kind">类型${arrow("kind")}</th>
          <th>模型</th>
          <th class="sortable" data-sort="status">状态${arrow("status")}</th>
          <th>角色</th>
          <th style="text-align:right;">操作</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");
    if (!rows.length) {
      const tr = document.createElement("tr");
      const td = document.createElement("td");
      td.colSpan = 6;
      td.className = "apikey-empty";
      td.textContent = "还没有任何 AI 厂商。点击右上角「＋ 添加厂商」开始：可添加内置厂商（自动预填默认地址与模型），或任意 OpenAI 兼容的自定义厂商。";
      tr.appendChild(td);
      tbody.appendChild(tr);
    }
    rows.forEach((p) => {
      const info = this._providerStatusInfo(p);
      const tags = this._providerRoleTags(p);
      const tagsHtml = tags.length
        ? tags.map((t) => '<span class="apikey-role-tag">' + this._esc(t) + "</span>").join("")
        : '<span style="color:var(--text-muted,#999);">-</span>';
      const kind = p.kind || "custom";
      const tr = document.createElement("tr");
      tr.dataset.id = p.id || "";
      tr.innerHTML = `
        <td>
          <span class="apikey-provider-cell">
            <span class="apikey-provider-dot" style="background:${info.dot};box-shadow:none;"></span>
            ${this._esc(p.name || p.id || "")}
          </span>
        </td>
        <td><span class="apikey-badge apikey-badge--${this._esc(kind)}">${this._esc(this._providerKindLabel(kind))}</span></td>
        <td>${this._esc(p.model || "-")}</td>
        <td style="color:${this._providerStatusColor(info.tone)};white-space:nowrap;">${this._esc(info.text)}</td>
        <td>${tagsHtml}</td>
        <td>
          <div class="apikey-row-actions">
            <button type="button" class="apikey-icon-btn" data-act="edit" title="编辑">编辑</button>
            <button type="button" class="apikey-icon-btn" data-act="test" title="测试连通性">测试</button>
            <button type="button" class="apikey-icon-btn" data-act="more" title="更多操作">更多</button>
          </div>
        </td>
      `;
      tr.addEventListener("click", (e) => {
        if (e.target.closest("button")) return;
        this._openProviderDrawer({ mode: "edit", provider: p });
      });
      tr.querySelector('[data-act="edit"]').addEventListener("click", () => this._openProviderDrawer({ mode: "edit", provider: p }));
      tr.querySelector('[data-act="test"]').addEventListener("click", () => this._testProvider(p));
      tr.querySelector('[data-act="more"]').addEventListener("click", (e) => this._openRowMenu(e.currentTarget, p));
      tbody.appendChild(tr);
    });
    wrap.appendChild(table);
    table.querySelectorAll("th.sortable").forEach((th) => {
      th.addEventListener("click", () => {
        const key = th.getAttribute("data-sort");
        if (this._providerSort.key === key) this._providerSort.dir *= -1;
        else this._providerSort = { key, dir: 1 };
        this._renderProviderTable();
      });
    });
  }

  _openRowMenu(anchor, p) {
    this._closeRowMenu();
    const menu = document.createElement("div");
    menu.className = "apikey-more-menu";
    menu.id = "apikey-row-menu";
    const enabled = p.enabled !== false;
    menu.innerHTML = `
      <button type="button" data-act="toggle">${enabled ? "停用" : "启用"}</button>
      <button type="button" data-act="copy">复制</button>
      <button type="button" data-act="delete" class="danger">删除</button>
    `;
    document.body.appendChild(menu);
    const rect = anchor.getBoundingClientRect();
    menu.style.top = (rect.bottom + 4) + "px";
    menu.style.left = Math.max(8, Math.min(rect.right - 128, window.innerWidth - 140)) + "px";
    menu.querySelector('[data-act="toggle"]').addEventListener("click", () => { this._closeRowMenu(); this._toggleProvider(p); });
    menu.querySelector('[data-act="copy"]').addEventListener("click", () => { this._closeRowMenu(); this._copyProvider(p); });
    menu.querySelector('[data-act="delete"]').addEventListener("click", () => { this._closeRowMenu(); this._deleteProvider(p); });
    setTimeout(() => {
      document.addEventListener("click", this._rowMenuOutside = (ev) => {
        if (!menu.contains(ev.target)) this._closeRowMenu();
      });
    }, 0);
  }

  _closeRowMenu() {
    const menu = document.getElementById("apikey-row-menu");
    if (menu) menu.remove();
    if (this._rowMenuOutside) { document.removeEventListener("click", this._rowMenuOutside); this._rowMenuOutside = null; }
  }

  async _testProvider(p) {
    if (!p || !p.id) return;
    this._setApiKeyStatus("正在测试「" + (p.name || p.id) + "」…", "muted");
    try {
      const d = await this._apiCall("POST", "/api/ai/providers/" + encodeURIComponent(p.id) + "/check");
      p.check = d.check || p.check;
      this._setApiKeyStatus("「" + (p.name || p.id) + "」" + (d.check && d.check.ok ? "连通正常 " + (d.check.latency_ms || 0) + "ms" : "测试失败"), d.check && d.check.ok ? "ok" : "error");
    } catch (e) {
      this._setApiKeyStatus("测试失败: " + e.message, "error");
    }
    this._renderProviderTable();
    this._renderApiKeyStatusBar();
  }

  async _testAllProviders() {
    const btn = document.getElementById("apikey-testall-btn");
    const list = this._providers.slice();
    if (!list.length) { this._setApiKeyStatus("没有可测试的厂商", "warn"); return; }
    if (btn) btn.disabled = true;
    let okCount = 0;
    for (let i = 0; i < list.length; i += 1) {
      const p = list[i];
      this._setApiKeyStatus("测速中 " + (i + 1) + "/" + list.length + "：" + (p.name || p.id), "muted");
      try {
        const d = await this._apiCall("POST", "/api/ai/providers/" + encodeURIComponent(p.id) + "/check");
        p.check = d.check || p.check;
        if (d.check && d.check.ok) okCount += 1;
      } catch (_) { /* 单项失败跳过，继续下一项 */ }
      this._renderProviderTable();
    }
    this._renderApiKeyStatusBar();
    this._setApiKeyStatus("全部测速完成：连通正常 " + okCount + " / " + list.length, okCount === list.length ? "ok" : "warn");
    if (btn) btn.disabled = false;
  }

  async _toggleProvider(p) {
    if (!p || !p.id) return;
    const next = !(p.enabled !== false);
    try {
      const d = await this._apiCall("POST", "/api/ai/providers/" + encodeURIComponent(p.id) + "/enabled", { enabled: next });
      p.enabled = d.provider ? d.provider.enabled !== false : next;
      this._setApiKeyStatus("「" + (p.name || p.id) + "」已" + (p.enabled ? "启用" : "停用"), "ok");
    } catch (e) {
      this._setApiKeyStatus("操作失败: " + e.message, "error");
    }
    this._renderProviderTable();
    this._renderApiKeyStatusBar();
  }

  _copyProvider(p) {
    if (!p) return;
    const kind = p.kind === "local_cli" ? "local_cli" : "custom";
    this._openProviderDrawer({
      mode: "create",
      kind,
      name: (p.name || p.id || "厂商") + " 副本",
      base_url: p.base_url || "",
      model: p.model || "",
      models: p.models || [],
      supports_tools: !!p.supports_tools,
      max_tool_calls: p.max_tool_calls,
      title: "复制厂商",
    });
  }

  async _deleteProvider(p) {
    if (!p || !p.id) return;
    const msg = "删除「" + (p.name || p.id) + "」？\n\n"
      + (p.kind === "builtin"
        ? "这是内置厂商，删除会同时清掉 .env 里的凭据，引用它的功能点会回落默认。\n"
        : "引用它的功能点绑定会回落默认。\n")
      + "此操作不可撤销。";
    if (!window.confirm(msg)) return;
    try {
      await this._apiCall("DELETE", "/api/ai/providers/" + encodeURIComponent(p.id));
      this._setApiKeyStatus("已删除「" + (p.name || p.id) + "」", "ok");
    } catch (e) {
      this._setApiKeyStatus("删除失败: " + e.message, "error");
      return;
    }
    await this.loadApiKeys();
  }

  // ── 添加厂商：内置 / 自定义选择器 ─────────────────────
  _openAddChooser() {
    const existing = document.getElementById("apikey-add-chooser");
    if (existing) { this._closeAddChooser(); return; }
    const btn = document.getElementById("apikey-add-btn");
    const box = document.createElement("div");
    box.id = "apikey-add-chooser";
    box.className = "apikey-add-chooser";
    const builtins = this._availableBuiltins || [];
    const html = ['<div class="apikey-add-chooser__group">内置厂商</div>'];
    if (builtins.length) {
      builtins.forEach((b, i) => {
        html.push('<button type="button" class="apikey-add-chooser__item" data-idx="' + i + '">'
          + this._esc(b.name || b.key) + "</button>");
      });
    } else {
      html.push('<div class="apikey-add-chooser__group">内置厂商已全部添加</div>');
    }
    html.push('<div class="apikey-add-chooser__group">其它</div>');
    html.push('<button type="button" class="apikey-add-chooser__item" data-custom="1">＋ 自定义厂商（任意 OpenAI 兼容 API）</button>');
    box.innerHTML = html.join("");
    document.body.appendChild(box);
    const rect = btn ? btn.getBoundingClientRect() : { bottom: 200, left: 200 };
    box.style.top = (rect.bottom + 6) + "px";
    box.style.left = Math.max(8, Math.min(rect.left, window.innerWidth - 260)) + "px";
    box.querySelectorAll("button[data-idx]").forEach((b) => {
      b.addEventListener("click", () => {
        const item = builtins[Number.parseInt(b.dataset.idx, 10)];
        this._closeAddChooser();
        this._addBuiltinProvider(item);
      });
    });
    const customBtn = box.querySelector("button[data-custom]");
    if (customBtn) customBtn.addEventListener("click", () => {
      this._closeAddChooser();
      this._openProviderDrawer({ mode: "create", kind: "custom", title: "添加自定义厂商" });
    });
    setTimeout(() => {
      document.addEventListener("click", this._addChooserOutside = (ev) => {
        if (!box.contains(ev.target) && ev.target !== btn) this._closeAddChooser();
      });
    }, 0);
  }

  _closeAddChooser() {
    const box = document.getElementById("apikey-add-chooser");
    if (box) box.remove();
    if (this._addChooserOutside) {
      document.removeEventListener("click", this._addChooserOutside);
      this._addChooserOutside = null;
    }
  }

  _addBuiltinProvider(b) {
    if (!b) return;
    this._openProviderDrawer({
      mode: "create",
      kind: "builtin",
      id: b.key,
      name: b.name || b.key,
      base_url: b.default_url || "",
      model: b.default_model || "",
      models: b.models || [],
      title: "添加内置厂商 · " + (b.name || b.key),
    });
  }

  // ── 编辑抽屉 ─────────────────────────────────────────
  _openProviderDrawer(opts) {
    const drawer = document.getElementById("apikey-drawer");
    const mask = document.getElementById("apikey-drawer-mask");
    if (!drawer || !mask) return;
    const o = opts || {};
    const isEdit = o.mode === "edit";
    const p = o.provider || {};
    this._drawerState = {
      mode: isEdit ? "edit" : "create",
      id: o.id || p.id || "",
      kind: o.kind || p.kind || "custom",
      enabled: isEdit ? p.enabled !== false : o.enabled !== false,
    };
    const setVal = (id, value) => { const el = document.getElementById(id); if (el) el.value = value == null ? "" : value; };
    const title = document.getElementById("apikey-drawer-title");
    if (title) title.textContent = o.title || (isEdit ? "编辑厂商 · " + (p.name || p.id) : "添加厂商");
    const kindEl = document.getElementById("apikey-drawer-kind");
    if (kindEl) kindEl.value = this._providerKindLabel(this._drawerState.kind);
    setVal("apikey-drawer-name", o.name != null ? o.name : p.name);
    setVal("apikey-drawer-base-url", o.base_url != null ? o.base_url : p.base_url);
    setVal("apikey-drawer-model", o.model != null ? o.model : p.model);
    const apiKeyInput = document.getElementById("apikey-drawer-api-key");
    if (apiKeyInput) {
      apiKeyInput.value = "";
      apiKeyInput.type = "password";
      apiKeyInput.placeholder = isEdit ? "留空则继续使用已保存的 Key" : "sk-...";
    }
    const tools = document.getElementById("apikey-drawer-supports-tools");
    if (tools) tools.checked = isEdit ? !!p.supports_tools : !!o.supports_tools;
    const maxCalls = document.getElementById("apikey-drawer-max-tool-calls");
    if (maxCalls) maxCalls.value = String(p.max_tool_calls || o.max_tool_calls || 8);
    const models = o.models || p.models || [];
    const dl = document.getElementById("apikey-drawer-model-list");
    if (dl) dl.innerHTML = models.map((m) => '<option value="' + this._esc(m) + '"></option>').join("");
    const urlField = document.getElementById("apikey-drawer-base-url-field");
    if (urlField) urlField.style.display = this._drawerState.kind === "local_cli" ? "none" : "";
    const testBtn = document.getElementById("apikey-drawer-test");
    if (testBtn) testBtn.disabled = !isEdit;
    const saveBtn = document.getElementById("apikey-drawer-save");
    if (saveBtn) saveBtn.disabled = false;
    const adv = document.getElementById("apikey-drawer-advanced");
    if (adv) adv.open = false;
    const st = document.getElementById("apikey-drawer-status");
    if (st) st.textContent = "";
    drawer.style.display = "flex";
    mask.style.display = "";
    setTimeout(() => { const n = document.getElementById("apikey-drawer-name"); if (n) n.focus(); }, 0);
  }

  _closeProviderDrawer() {
    const drawer = document.getElementById("apikey-drawer");
    const mask = document.getElementById("apikey-drawer-mask");
    if (drawer) drawer.style.display = "none";
    if (mask) mask.style.display = "none";
    this._drawerState = null;
  }

  async _testDrawerProvider() {
    const state = this._drawerState;
    if (!state || !state.id) return;
    const st = document.getElementById("apikey-drawer-status");
    const btn = document.getElementById("apikey-drawer-test");
    if (btn) btn.disabled = true;
    if (st) { st.textContent = "测试中…"; st.style.color = "var(--text-muted, #999)"; }
    try {
      const d = await this._apiCall("POST", "/api/ai/providers/" + encodeURIComponent(state.id) + "/check");
      const check = d.check || {};
      if (st) {
        st.textContent = check.ok
          ? "连通正常 " + (check.latency_ms || 0) + "ms"
          : "测试失败：" + (check.detail || ("HTTP " + (check.http_status || "?")));
        st.style.color = check.ok ? "var(--success, #2ecc71)" : "var(--danger, #e74c3c)";
      }
    } catch (e) {
      if (st) { st.textContent = "测试失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async _saveProvider(force) {
    const state = this._drawerState;
    if (!state) return;
    const st = document.getElementById("apikey-drawer-status");
    const btn = document.getElementById("apikey-drawer-save");
    const get = (id) => document.getElementById(id);
    const nameEl = get("apikey-drawer-name");
    const urlEl = get("apikey-drawer-base-url");
    const keyEl = get("apikey-drawer-api-key");
    const modelEl = get("apikey-drawer-model");
    const toolsEl = get("apikey-drawer-supports-tools");
    const maxEl = get("apikey-drawer-max-tool-calls");
    const name = nameEl ? nameEl.value.trim() : "";
    const baseUrl = urlEl ? urlEl.value.trim() : "";
    const apiKey = keyEl ? keyEl.value.trim() : "";
    const model = modelEl ? modelEl.value.trim() : "";
    const supportsTools = !!(toolsEl && toolsEl.checked);
    const parsedMax = Number.parseInt(maxEl ? maxEl.value : "8", 10);
    const isLocalCli = state.kind === "local_cli";
    const isCreate = state.mode === "create";
    const fail = (text) => { if (st) { st.textContent = text; st.style.color = "var(--warning, #f39c12)"; } };

    if (!name) { fail("请填写名称"); return; }
    if (!isLocalCli && !baseUrl) { fail("请填写 Base URL"); return; }
    if (isCreate && !isLocalCli && !apiKey) { fail("新增厂商必须填写 API Key"); return; }

    const body = {
      kind: state.kind,
      name,
      model,
      supports_tools: supportsTools,
      max_tool_calls: Number.isNaN(parsedMax) ? 8 : Math.min(50, Math.max(1, parsedMax)),
      enabled: state.enabled !== false,
      force: !!force,
    };
    if (state.id) body.id = state.id;
    if (!isLocalCli) body.base_url = baseUrl;
    if (apiKey) body.api_key = apiKey;

    if (btn) btn.disabled = true;
    if (st) { st.textContent = "测试并保存中…（先小流量验证，通过才写入）"; st.style.color = "var(--text-muted, #999)"; }
    try {
      const d = await this._apiCall("PUT", "/api/ai/providers", body);
      const check = d.check;
      this._closeProviderDrawer();
      this._setApiKeyStatus((isCreate ? "已添加并热加载" : "已保存并热加载")
        + (check && check.ok ? "（连通 " + (check.latency_ms || 0) + "ms）" : ""), "ok");
      await this.loadApiKeys();
    } catch (e) {
      if (this._isForceable(e) && !force) {
        if (window.confirm("连通性测试失败：" + (e.message || "") + "。仍然保存？")) {
          return this._saveProvider(true);
        }
        if (st) { st.textContent = "已取消保存"; st.style.color = "var(--warning, #f39c12)"; }
        if (btn) btn.disabled = false;
        return;
      }
      if (st) { st.textContent = "未保存: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
      if (btn) btn.disabled = false;
    }
  }

  // 自定义厂商的增删改已统一由抽屉（_saveProvider / _deleteProvider）处理。

  // ── 专用服务（ASR / 生图 / TTS）：只读展示，凭据在 .env ──
  _renderSpecialServices() {
    const wrap = document.getElementById("special-services-table");
    if (!wrap) return;
    const list = this._specialServices || [];
    if (!list.length) {
      wrap.innerHTML = '<div class="apikey-empty">暂无专用服务。</div>';
      return;
    }
    wrap.innerHTML = '<table class="apikey-table"><thead><tr><th>服务</th><th>模型</th></tr></thead><tbody>'
      + list.map((s) => "<tr><td>" + this._esc(s.name || s.key)
        + (s.desc ? '<div style="font-size:11px;color:var(--text-muted,#999);margin-top:2px;">' + this._esc(s.desc) + "</div>" : "")
        + "</td><td>" + this._esc(s.model || "默认") + "</td></tr>").join("")
      + "</tbody></table>";
  }

  // 内置厂商的 Key/Base URL/模型修改已统一由抽屉 + PUT /api/ai/providers 处理。

  async loadBaiduMap() {
    const dot = document.getElementById("baidu-map-dot");
    const statusEl = document.getElementById("baidu-map-status");
    const akInput = document.getElementById("baidu-map-ak");
    const skInput = document.getElementById("baidu-map-sk");
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/env/baidu-map" });
      const d = (r && r.data) || {};
      const configured = !!(d.ak_configured || d.sk_configured);
      if (dot) dot.style.background = configured ? "var(--success, #2ecc71)" : "var(--text-muted, #999)";
      if (statusEl) statusEl.textContent = configured ? "已配置" : "未配置";
      if (akInput) akInput.value = d.ak_masked || "";
      if (skInput) skInput.value = d.sk_masked || "";
    } catch (e) {
      if (statusEl) { statusEl.textContent = "读取失败"; statusEl.style.color = "var(--danger, #e74c3c)"; }
    }
  }

  async saveBaiduMap() {
    const st = document.getElementById("apikey-status");
    const btn = document.getElementById("baidu-map-save-btn");
    const akInput = document.getElementById("baidu-map-ak");
    const skInput = document.getElementById("baidu-map-sk");
    const body = {};
    if (akInput && akInput.value.trim()) body.ak = akInput.value.trim();
    if (skInput && skInput.value.trim()) body.sk = skInput.value.trim();
    if (btn) btn.disabled = true;
    if (st) { st.textContent = "保存中…"; st.style.color = "var(--text-muted, #999)"; }
    try {
      const r = await window.aerie.api.request({ method: "POST", path: "/api/env/baidu-map", body });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      if (st) { st.textContent = "保存成功，重启后端后生效"; st.style.color = "var(--success, #2ecc71)"; }
      await this.loadBaiduMap();
    } catch (e) {
      if (st) { st.textContent = "保存失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ── 功能点路由卡片：功能点 / 厂商下拉 / 模型输入 ──────
  _renderModelRolesCard() {
    const wrap = document.getElementById("model-roles-table");
    if (!wrap) return;
    wrap.innerHTML = "";
    const roles = this._modelRoles || [];
    if (!roles.length) {
      wrap.innerHTML = '<div class="apikey-empty">暂无功能点配置。</div>';
      return;
    }
    const providers = this._bindableProviders || [];
    const models = [];
    providers.forEach((p) => {
      (p.models || []).forEach((m) => { if (models.indexOf(m) < 0) models.push(m); });
      if (p.model && models.indexOf(p.model) < 0) models.push(p.model);
    });
    const table = document.createElement("table");
    table.className = "apikey-table";
    table.innerHTML = `
      <thead>
        <tr>
          <th style="width:170px;">功能点</th>
          <th>厂商</th>
          <th>模型</th>
        </tr>
      </thead>
      <tbody></tbody>
    `;
    const tbody = table.querySelector("tbody");
    roles.forEach((role) => {
      const optionsHtml = providers.map((p) => {
        const suffix = (p.virtual || p.multi_key) ? "（多 Key 池）" : "";
        const selected = p.key === role.provider ? " selected" : "";
        return '<option value="' + this._esc(p.key) + '"' + selected + ">"
          + this._esc((p.name || p.key) + suffix) + "</option>";
      }).join("");
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>
          <span style="font-weight:600;">${this._esc(role.name || role.key)}</span>
          ${role.desc ? '<div style="font-size:11px;color:var(--text-muted,#999);margin-top:2px;">' + this._esc(role.desc) + "</div>" : ""}
        </td>
        <td><select class="apikey-input" data-role-provider="${this._esc(role.key)}">${optionsHtml}</select></td>
        <td><input type="text" class="apikey-input" data-role-model="${this._esc(role.key)}" list="model-roles-model-list" value="${this._esc(role.model || "")}" placeholder="模型名 / model"></td>
      `;
      tbody.appendChild(tr);
    });
    wrap.appendChild(table);
    wrap.insertAdjacentHTML("beforeend", '<datalist id="model-roles-model-list">'
      + models.map((m) => '<option value="' + this._esc(m) + '"></option>').join("")
      + "</datalist>");
    wrap.querySelectorAll("select[data-role-provider]").forEach((sel) => {
      sel.addEventListener("change", () => {
        const key = sel.getAttribute("data-role-provider");
        const input = wrap.querySelector('input[data-role-model="' + key + '"]');
        const p = providers.find((x) => x.key === sel.value);
        if (input && !input.value.trim() && p && p.model) input.value = p.model;
      });
    });
  }

  async saveModelRoles(force) {
    const st = document.getElementById("model-roles-status");
    const btn = document.getElementById("model-roles-save-btn");
    const wrap = document.getElementById("model-roles-table");
    if (!wrap) return;
    const roles = [];
    wrap.querySelectorAll("select[data-role-provider]").forEach((sel) => {
      const key = sel.getAttribute("data-role-provider");
      const modelInput = wrap.querySelector(`input[data-role-model="${key}"]`);
      roles.push({ key, provider: sel.value, model: modelInput ? modelInput.value.trim() : "" });
    });
    if (!roles.length) {
      if (st) { st.textContent = "暂无可保存的功能点"; st.style.color = "var(--warning,#f39c12)"; }
      return;
    }
    if (btn) btn.disabled = true;
    if (st) { st.textContent = "小流量测试中…（每个功能点发一次 max_tokens=1 的探测请求）"; st.style.color = "var(--text-muted,#999)"; }
    try {
      await this._apiCall("POST", "/api/env/model-roles", { roles, force: !!force });
      if (st) { st.textContent = "全部通过，已保存并热加载"; st.style.color = "var(--success,#2ecc71)"; }
      await this.loadApiKeys();
    } catch (e) {
      if (this._isForceable(e) && !force) {
        if (window.confirm("存在功能点测试失败：" + (e.message || "") + "。仍然保存全部绑定？")) {
          return this.saveModelRoles(true);
        }
        if (st) { st.textContent = "已取消保存"; st.style.color = "var(--warning,#f39c12)"; }
      } else if (st) {
        st.textContent = "未保存: " + e.message;
        st.style.color = "var(--danger,#e74c3c)";
      }
    } finally {
      if (btn) btn.disabled = false;
      setTimeout(() => { if (st) st.textContent = ""; }, 6000);
    }
  }

  // ── 功能 API 配置：搜索 / 天气 / 位置等外部服务 ──────────
  async loadFeatureApis() {
    const list = document.getElementById("feature-api-list");
    const credList = document.getElementById("platform-credential-list");
    if (!list && !credList) return;
    const st = document.getElementById("feature-api-status");
    try {
      if (st) { st.textContent = "加载中…"; st.style.color = "var(--text-muted, #999)"; }
      const r = await window.aerie.api.request({ method: "GET", path: "/api/env/feature-apis" });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      const data = (r && r.data) || {};
      this._renderFeatureApis(data.features || [], "feature-api-list");
      // 平台凭证与功能 API 共用同一份元数据与保存端点，只是渲染进各自的容器。
      this._renderFeatureApis(data.platform_credentials || [], "platform-credential-list");
      if (st) { st.textContent = ""; }
    } catch (e) {
      if (st) { st.textContent = "加载失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    }
  }

  _renderFeatureApis(features, listId = "feature-api-list") {
    const list = document.getElementById(listId);
    if (!list) return;
    list.innerHTML = "";
    features.forEach((f) => {
      const card = document.createElement("div");
      card.className = "apikey-provider-card" + (f.configured ? " configured" : "");
      const statusText = f.builtin ? "内置 · 无需密钥" : (f.configured ? "已配置" : "未配置");
      const statusColor = (f.builtin || f.configured) ? "var(--success, #2ecc71)" : "var(--text-muted, #999)";
      const fieldsHtml = (f.fields || []).map((fd) => `
        <label class="apikey-field">
          <span>${fd.label}</span>
          <input type="${fd.secret ? 'password' : 'text'}" class="apikey-input" data-feature="${f.key}" data-env="${fd.env_key}"
                 value="${fd.masked || ''}" placeholder="${fd.secret ? '请输入密钥' : ''}">
        </label>
      `).join("");
      const fieldsBlock = f.builtin ? "" : `<div class="apikey-provider-fields">${fieldsHtml}</div>`;
      const actionBlock = f.builtin ? "" : `
        <div class="apikey-provider-actions">
          <button type="button" class="btn btn-primary btn-sm feature-save-btn" data-feature="${f.key}">保存并热加载 · Save</button>
        </div>
      `;
      card.innerHTML = `
        <div class="apikey-provider-header">
          <div class="apikey-provider-name">
            <span class="apikey-provider-dot" style="background: ${f.configured ? 'var(--success, #2ecc71)' : 'var(--text-muted, #999)'}"></span>
            ${f.name}
          </div>
          <div class="apikey-provider-status" style="color:${statusColor}">${statusText}</div>
        </div>
        <div style="font-size:12px;color:var(--text-muted,#999);margin:0 0 8px;">${f.desc}</div>
        ${fieldsBlock}
        ${actionBlock}
        <div style="font-size:12px;line-height:1.5;margin-top:8px;color:var(--text-muted,#999);">
          ${f.how_to}${f.tutorial ? ` · <a href="#" data-tutorial="${f.tutorial}" class="feature-tutorial-link" style="color:var(--accent,#ff5b9c);">申请教程 ↗</a>` : ""}
        </div>
      `;
      list.appendChild(card);
    });
    list.querySelectorAll(".feature-save-btn").forEach((btn) => {
      btn.addEventListener("click", () => this.saveFeatureApi(btn.dataset.feature));
    });
    list.querySelectorAll(".feature-tutorial-link").forEach((a) => {
      a.addEventListener("click", (e) => {
        e.preventDefault();
        const url = a.dataset.tutorial || "";
        if (window.aerie && window.aerie.electron && window.aerie.electron.shell && window.aerie.electron.shell.openExternal) {
          window.aerie.electron.shell.openExternal(url);
        } else {
          window.open(url, "_blank", "noopener");
        }
      });
    });
  }

  async saveFeatureApi(featureKey) {
    // 同一个 key 只会出现在一个列表里；先定位它，状态提示也跟着它走。
    const containers = [
      ["feature-api-list", "feature-api-status"],
      ["platform-credential-list", "platform-credential-status"],
    ];
    let scope = null;
    let st = null;
    for (const [listId, statusId] of containers) {
      const el = document.getElementById(listId);
      if (el && el.querySelector(`[data-feature="${featureKey}"]`)) {
        scope = el;
        st = document.getElementById(statusId);
        break;
      }
    }
    if (!scope) return;
    const fields = {};
    scope.querySelectorAll(`input[data-feature="${featureKey}"]`).forEach((input) => {
      fields[input.dataset.env] = input.value.trim();
    });
    const btn = scope.querySelector(`.feature-save-btn[data-feature="${featureKey}"]`);
    if (btn) btn.disabled = true;
    if (st) { st.textContent = "保存并热加载中…"; st.style.color = "var(--text-muted, #999)"; }
    try {
      const r = await window.aerie.api.request({ method: "POST", path: "/api/env/feature-apis", body: { feature_key: featureKey, fields } });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      await this.loadFeatureApis();
      const activated = (r && r.data && r.data.activated_skills) || [];
      if (st) {
        // 后端保存后会重扫 skill：明确告诉用户这一填有没有真的点亮某个能力。
        st.textContent = activated.length
          ? `已保存并热加载 · 新启用技能：${activated.join("、")}`
          : "已保存并热加载";
        st.style.color = "var(--success, #2ecc71)";
      }
    } catch (e) {
      if (st) { st.textContent = "保存失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    } finally {
      if (btn) btn.disabled = false;
      setTimeout(() => { if (st) st.textContent = ""; }, 6000);
    }
  }

  async load() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/settings" });
      const s = (r.data && !r.data.error) ? r.data : {};
      const theme = s.theme || {};
      const startup = s.startup || {};
      const proactive = s.proactive || {};
      const weather = s.weather || {};

      document.getElementById("setting-theme").value = theme.current || "yita-pink";
      document.getElementById("setting-auto-start").checked = startup.auto_start === true;
      document.getElementById("setting-start-minimized").checked = startup.start_minimized === true;
      if (window.aerie && window.aerie.startup && window.aerie.startup.get) {
        const startupState = await window.aerie.startup.get();
        if (startupState && startupState.ok) {
          document.getElementById("setting-auto-start").checked = startupState.autoStart === true;
        }
      }
      document.getElementById("setting-proactive").checked = proactive.enabled !== false;

      // Daily proactive message frequency controls.
      const maxPerDayEl = document.getElementById("setting-proactive-max-per-day");
      if (maxPerDayEl) {
        const v = Number(proactive.max_per_day != null ? proactive.max_per_day : 0);
        maxPerDayEl.value = String([3, 5, 8, 10, 15, 20, 30, 0].includes(v) ? v : 5);
      }
      const minIntervalEl = document.getElementById("setting-proactive-min-interval");
      if (minIntervalEl) {
        const v = Number(proactive.min_interval_min != null ? proactive.min_interval_min : 0);
        minIntervalEl.value = String([15, 30, 60].includes(v) ? v : 30);
      }

      // Daily proactive image limit + today's usage readout.
      const limitEl = document.getElementById("setting-proactive-image-limit");
      if (limitEl) {
        const limit = (proactive.image_max_per_day != null) ? Number(proactive.image_max_per_day) : 0;
        limitEl.value = String([6, 10, 20, 0].includes(limit) ? limit : 0);
      }
      const usageEl = document.getElementById("setting-proactive-image-usage");
      if (usageEl) {
        const used = (proactive.image_used_today != null) ? Number(proactive.image_used_today) : 0;
        const max = (proactive.image_max_per_day != null) ? Number(proactive.image_max_per_day) : 0;
        usageEl.textContent = max > 0
          ? `今日已用 ${used} / 上限 ${max} · Used ${used}/${max} today`
          : `今日已用 ${used} · Used ${used} today (不限制 / Unlimited)`;
      }

      // Proactive image min interval (seconds in settings, minutes in UI).
      const photoIntervalEl = document.getElementById("setting-proactive-photo-interval");
      if (photoIntervalEl) {
        const sec = Number(proactive.photo_min_interval_sec != null ? proactive.photo_min_interval_sec : 0);
        const min = Math.round(sec / 60);
        photoIntervalEl.value = String([0, 10, 30, 60, 120].includes(min) ? min : 0);
      }

      // Companion image probability
      const companionProbEl = document.getElementById("setting-proactive-companion-image-prob");
      if (companionProbEl) {
        const prob = proactive.companion_image_probability != null
          ? Number(proactive.companion_image_probability) : 0.3;
        const candidates = [0, 0.1, 0.2, 0.3, 0.5, 0.8, 1];
        // Snap to nearest option
        let best = 0.3;
        let bestDiff = Infinity;
        for (const c of candidates) {
          const d = Math.abs(c - prob);
          if (d < bestDiff) { bestDiff = d; best = c; }
        }
        companionProbEl.value = String(best);
      }

      // L4 self-evolution (beta) toggle — read back from feature_flags.
      const l4El = document.getElementById("setting-self-evolve-l4");
      if (l4El) {
        l4El.checked = ((s.feature_flags || {}).self_evolve_l4_enabled) === true;
      }

      // Task progress granularity — read back from agent.progress.style.
      const progressEl = document.getElementById("setting-task-progress-style");
      if (progressEl) {
        const style = (((s.agent || {}).progress) || {}).style || "stage";
        progressEl.value = ["stage", "start_end", "verbose", "off"].includes(style)
          ? style
          : "stage";
      }

      // Max messages per turn — read back from agent.max_segments_per_turn.
      const segEl = document.getElementById("setting-max-segments");
      if (segEl) {
        const raw = ((s.agent || {}).max_segments_per_turn);
        const maxSeg = (raw == null) ? 3 : Number(raw);
        segEl.value = String([1, 2, 3, 4, 0].includes(maxSeg) ? maxSeg : 3);
      }

      // 高级设置：消息合并首条聚合窗（T_idle / T_cap）双向绑定读取。
      const mb = s.message_batching || {};
      const batchIdleEl = document.getElementById("setting-batch-idle-seconds");
      const batchCapEl = document.getElementById("setting-batch-cap-seconds");
      if (batchIdleEl) {
        const v = Number(mb.first_message_idle_seconds != null ? mb.first_message_idle_seconds : 3);
        batchIdleEl.value = String(Number.isFinite(v) ? v : 3);
      }
      if (batchCapEl) {
        const v = Number(mb.first_message_cap_seconds != null ? mb.first_message_cap_seconds : 8);
        batchCapEl.value = String(Number.isFinite(v) ? v : 8);
      }

      // R7.1: my-location picker.
      const cityInput = document.getElementById("setting-weather-city");
      const hint = document.getElementById("setting-weather-hint");
      if (cityInput) {
        cityInput.value = (weather.city || "").trim();
      }
      if (hint) {
        const auto = (weather.auto_detected || "").trim();
        hint.textContent = (weather.city || "").trim()
          ? "已使用手动城市 / Using manual override."
          : (auto
              ? "已自动检测到: " + auto + " (留空将使用) / Auto-detected: " + auto + " (leave empty to use)"
              : "留空时简报会显示通过 IP 自动检测到的城市。/ Leave empty for IP auto-detect.");
      }

      // Brief subscriptions (订阅源自选).
      const subSrcs = ((s.brief_subscriptions || {}).sources) || {};
      const gh = subSrcs.github_trending || {};
      const ghEl = document.getElementById("setting-sub-github");
      const ghMinEl = document.getElementById("setting-sub-github-min");
      if (ghEl) ghEl.checked = gh.enabled !== false;
      if (ghMinEl) ghMinEl.value = String(gh.min_stars != null ? gh.min_stars : 200);
      const astroEl = document.getElementById("setting-sub-astronomy");
      const astro = subSrcs.astronomy || {};
      if (astroEl) astroEl.checked = astro.enabled !== false;
      this.startBootProgressPolling();
    } catch (e) {
      console.warn("settings load failed", e);
    }
  }

  renderBootProgress(progress) {
    const fill = document.getElementById("boot-progress-fill");
    const list = document.getElementById("boot-progress-list");
    if (!fill || !list) return;
    const steps = (progress && Array.isArray(progress.steps)) ? progress.steps : [];
    if (steps.length === 0) {
      list.textContent = "等待后端状态…";
      fill.style.width = "0%";
      return;
    }
    const done = steps.filter((s) => s.status === "done" || s.status === "skipped").length;
    const pct = Math.min(100, Math.round((done / steps.length) * 100));
    fill.style.width = pct + "%";
    const lines = steps.map((s) => {
      const icon = s.status === "done" ? "完成" : s.status === "error" ? "失败" : s.status === "running" ? "处理中" : "等待";
      const ms = s.elapsed_ms != null ? ` ${s.elapsed_ms}ms` : "";
      return `${icon} ${s.detail || s.name}${ms}`;
    });
    list.textContent = lines.join(" · ");
  }

  startBootProgressPolling() {
    if (this._bootProgressTimer) return;
    const tick = async () => {
      try {
        const r = await window.aerie.api.request({ method: "GET", path: "/api/health" });
        const sp = r.data && r.data.startup_progress;
        if (sp) this.renderBootProgress(sp);
      } catch (_) {}
    };
    tick();
    this._bootProgressTimer = setInterval(tick, 1000);
  }

  async save() {
    // 高级设置：消息合并首条聚合窗（T_idle / T_cap）校验后再写入。
    const batchIdleEl = document.getElementById("setting-batch-idle-seconds");
    const batchCapEl = document.getElementById("setting-batch-cap-seconds");
    const batchStatusEl = document.getElementById("setting-batch-status");
    let batchIdle = null;
    let batchCap = null;
    if (batchIdleEl && batchCapEl) {
      batchIdle = Number(batchIdleEl.value);
      batchCap = Number(batchCapEl.value);
      const fail = (msg) => {
        if (batchStatusEl) {
          batchStatusEl.textContent = msg;
          batchStatusEl.className = "settings-hint office-dir-status--error";
        }
        const st = document.getElementById("settings-status");
        if (st) { st.textContent = msg; st.style.color = "var(--error)"; }
      };
      if (!Number.isFinite(batchIdle) || batchIdle < 0 || !Number.isFinite(batchCap) || batchCap < 0) {
        fail("消息合并参数必须是非负数字");
        return;
      }
      if (batchCap < batchIdle) {
        fail("聚合总时长上限 T_cap 不能小于首条静默时长 T_idle");
        return;
      }
      if (batchStatusEl) { batchStatusEl.textContent = ""; batchStatusEl.className = "settings-hint"; }
    }
    const cityRaw = (document.getElementById("setting-weather-city")?.value || "").trim();
    const data = {
      theme: {
        current: document.getElementById("setting-theme").value,
      },
      startup: {
        auto_start: document.getElementById("setting-auto-start").checked,
        start_minimized: document.getElementById("setting-start-minimized").checked,
      },
      proactive: {
        enabled: document.getElementById("setting-proactive").checked,
        max_per_day: Number(document.getElementById("setting-proactive-max-per-day")?.value || 5),
        min_interval_min: Number(document.getElementById("setting-proactive-min-interval")?.value || 30),
        image_max_per_day: Number(document.getElementById("setting-proactive-image-limit")?.value || 0),
        photo_min_interval_sec: Number(document.getElementById("setting-proactive-photo-interval")?.value || 0) * 60,
        companion_image_probability: Number(document.getElementById("setting-proactive-companion-image-prob")?.value || 0.3),
      },
      // R7.1: empty string ⇒ resolver falls back to IP auto-detect.
      weather: {
        city: cityRaw,
      },
      // Brief subscriptions (订阅源自选).
      brief_subscriptions: {
        enabled: true,
        sources: {
          github_trending: {
            enabled: document.getElementById("setting-sub-github")?.checked === true,
            min_stars: Number(document.getElementById("setting-sub-github-min")?.value || 200),
          },
          astronomy: {
            enabled: document.getElementById("setting-sub-astronomy")?.checked === true,
          },
        },
      },
      // L4 self-evolution (beta) toggle — persists into feature_flags.
      feature_flags: {
        self_evolve_l4_enabled: document.getElementById("setting-self-evolve-l4")?.checked === true,
      },
      // Task execution settings — persist into agent.*.
      agent: {
        progress: {
          style: document.getElementById("setting-task-progress-style")?.value || "stage",
        },
        max_segments_per_turn: Number(document.getElementById("setting-max-segments")?.value ?? 3),
      },
    };
    // 高级设置：消息合并首条聚合窗（后端 PUT /api/settings 热应用）。
    if (batchIdle !== null && batchCap !== null) {
      data.message_batching = {
        first_message_idle_seconds: batchIdle,
        first_message_cap_seconds: batchCap,
      };
    }
    try {
      const r = await window.aerie.api.request({ method: "PUT", path: "/api/settings", body: data });
      const st = document.getElementById("settings-status");
      if (r.data && !r.data.error) {
        if (window.aerie && window.aerie.startup && window.aerie.startup.set) {
          const startupResult = await window.aerie.startup.set({
            autoStart: data.startup.auto_start,
            startMinimized: data.startup.start_minimized,
          });
          if (!startupResult || startupResult.ok === false) {
            st.textContent = "设置已保存，但开机启动项写入失败: " + (startupResult?.error || "unknown");
            st.style.color = "var(--error)";
            setTimeout(() => { st.textContent = ""; }, 5000);
            return;
          }
        }
        st.textContent = "设置已保存";
        st.style.color = "var(--success)";
      } else {
        st.textContent = "保存失败: " + (r.data?.error || "unknown");
        st.style.color = "var(--error)";
      }
      setTimeout(() => { st.textContent = ""; }, 3000);
    } catch (e) {
      const st = document.getElementById("settings-status");
      st.textContent = "保存失败: " + e.message;
      st.style.color = "var(--error)";
    }
  }

  async reset() {
    if (!confirm("确定恢复默认设置？")) return;
    try {
      await window.aerie.api.request({ method: "POST", path: "/api/settings/reset" });
      if (window.aerie && window.aerie.startup && window.aerie.startup.set) {
        await window.aerie.startup.set({ autoStart: false, startMinimized: false });
      }
      this.load();
      const st = document.getElementById("settings-status");
      st.textContent = "已恢复默认设置";
      st.style.color = "var(--success)";
      setTimeout(() => { st.textContent = ""; }, 3000);
    } catch (e) {
      console.warn("settings reset failed", e);
    }
  }

  // ── L4 自进化（内测）开关：开启需两次风险确认 ──────────

  _initSelfEvolveSwitch() {
    const el = document.getElementById("setting-self-evolve-l4");
    const modal = document.getElementById("l4-enable-modal");
    if (!el || !modal) return;
    const statusEl = document.getElementById("se-master-status");
    const showStatus = (msg, ok) => {
      if (!statusEl) return;
      statusEl.style.display = "";
      statusEl.textContent = msg;
      statusEl.style.color = ok ? "var(--success, #2ecc71)" : "var(--danger, #e74c3c)";
      setTimeout(() => { statusEl.style.display = "none"; }, 5000);
    };
    // 把开关状态写进 settings.yaml（后端热应用），成功后触发热重载。
    const applyToggle = async (checked) => {
      try {
        const r = await window.aerie.api.request({
          method: "PUT",
          path: "/api/settings",
          body: { feature_flags: { self_evolve_l4_enabled: checked } },
        });
        if (r.data && !r.data.error) {
          if (window.aerie && window.aerie.electron && window.aerie.electron.system && window.aerie.electron.system.reloadConfig) {
            try { await window.aerie.electron.system.reloadConfig(); } catch (_) {}
          }
          showStatus(checked ? "已开启 L4 代码自进化" : "已关闭 L4 代码自进化", true);
        } else {
          showStatus("保存失败: " + (r.data?.error || "unknown"), false);
        }
      } catch (e) {
        showStatus("保存失败: " + e.message, false);
      }
    };

    el.addEventListener("change", () => {
      if (el.checked) {
        this._openL4EnableModal(); // 开启 → 两次确认
      } else {
        applyToggle(false); // 关闭 → 直接生效
      }
    });

    // 取消 / 关闭弹窗 → 回滚开关状态
    const close = () => {
      modal.classList.add("hidden");
      this._resetL4WarnSteps();
      if (el.checked) el.checked = false;
    };
    modal.querySelectorAll("[data-l4-close]").forEach((b) => b.addEventListener("click", close));

    const nextBtn = document.getElementById("l4-warn-next");
    const confirmBtn = document.getElementById("l4-warn-confirm");
    const step1 = document.getElementById("l4-warn-step-1");
    const step2 = document.getElementById("l4-warn-step-2");
    const note = document.getElementById("l4-warn-progress");
    if (nextBtn && confirmBtn && step1 && step2 && note) {
      nextBtn.addEventListener("click", () => {
        step1.classList.add("hidden");
        step2.classList.remove("hidden");
        nextBtn.classList.add("hidden");
        confirmBtn.classList.remove("hidden");
        note.textContent = "请完整阅读以上两条提示后，逐次确认（当前第 2 / 2 条）";
      });
      confirmBtn.addEventListener("click", async () => {
        close();
        await applyToggle(true); // 第二次确认后真正开启
      });
    }
  }

  _openL4EnableModal() {
    const modal = document.getElementById("l4-enable-modal");
    if (!modal) return;
    this._resetL4WarnSteps();
    modal.classList.remove("hidden");
  }

  _resetL4WarnSteps() {
    const s1 = document.getElementById("l4-warn-step-1");
    const s2 = document.getElementById("l4-warn-step-2");
    const next = document.getElementById("l4-warn-next");
    const confirm = document.getElementById("l4-warn-confirm");
    const note = document.getElementById("l4-warn-progress");
    if (s1) s1.classList.remove("hidden");
    if (s2) s2.classList.add("hidden");
    if (next) next.classList.remove("hidden");
    if (confirm) confirm.classList.add("hidden");
    if (note) note.textContent = "请完整阅读以上两条提示后，逐次确认（当前第 1 / 2 条）";
  }

  // ── Phase 9 Batch 3: YAML editor mode ─────────────────

  async loadYaml() {
    const st = document.getElementById("yaml-status");
    if (st) { st.textContent = "加载中… / Loading…"; st.style.color = "var(--text-muted, #888)"; }
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/config/yaml?file=" + encodeURIComponent(this._currentYamlFile),
      });
      const editor = document.getElementById("yaml-editor");
      // api_request may wrap body in resp.data, or return text directly
      if (typeof r.data === "string") {
        editor.value = r.data;
      } else if (r.data && typeof r.data === "object") {
        // Fallback: if the response was JSON-wrapped somehow
        editor.value = JSON.stringify(r.data, null, 2);
      } else {
        editor.value = String(r.data || "");
      }
      if (st) {
        st.textContent = "已加载 " + this._currentYamlFile;
        st.style.color = "var(--success)";
        setTimeout(() => { st.textContent = ""; }, 2000);
      }
    } catch (e) {
      if (st) {
        st.textContent = "加载失败: " + e.message;
        st.style.color = "var(--error)";
      }
    }
  }

  async saveYaml() {
    const editor = document.getElementById("yaml-editor");
    const st = document.getElementById("yaml-status");
    if (!editor || !st) return;
    const text = editor.value;
    if (!text.trim()) {
      st.textContent = "YAML 不能为空 / YAML cannot be empty";
      st.style.color = "var(--error)";
      return;
    }
    if (!confirm("保存会覆盖 " + this._currentYamlFile + "，并自动备份。继续？\nSave will overwrite " + this._currentYamlFile + " and create a backup. Continue?")) {
      return;
    }
    st.textContent = "保存中… / Saving…";
    st.style.color = "var(--text-muted, #888)";
    try {
      const r = await window.aerie.api.request({
        method: "PUT",
        path: "/api/config/yaml?file=" + encodeURIComponent(this._currentYamlFile),
        body: text,
        rawBody: true,
      });
      if (r.data && r.data.status === "ok") {
        st.textContent = "已保存。" + (this._personaPronoun || "她") + "下次启动会用新配置。/ Saved.";
        st.style.color = "var(--success)";
      } else {
        const err = (r.data && (r.data.detail || r.data.error)) || "unknown";
        st.textContent = "YAML 格式错误，已恢复上次备份。错误：" + err + " / YAML error. Restored.";
        st.style.color = "var(--error)";
      }
    } catch (e) {
      st.textContent = "保存失败: " + e.message + " / Save failed.";
      st.style.color = "var(--error)";
    }
  }

  async backupYaml() {
    const st = document.getElementById("yaml-status");
    if (st) { st.textContent = "备份中… / Backing up…"; st.style.color = "var(--text-muted, #888)"; }
    try {
      const r = await window.aerie.api.request({
        method: "POST",
        path: "/api/config/yaml/backup?file=" + encodeURIComponent(this._currentYamlFile),
      });
      if (r.data && r.data.status === "ok") {
        st.textContent = "已备份到 " + r.data.backup_path;
        st.style.color = "var(--success)";
      } else {
        st.textContent = "备份失败: " + (r.data?.error || "unknown");
        st.style.color = "var(--error)";
      }
    } catch (e) {
      if (st) {
        st.textContent = "备份失败: " + e.message;
        st.style.color = "var(--error)";
      }
    }
  }

  // ── Block-2 A2: Persona (avatar + name) ──────────────

  _initPersonaControls() {
    const uploadBtn = document.getElementById("persona-avatar-upload");
    const fileInput = document.getElementById("persona-avatar-file");
    const saveBtn = document.getElementById("persona-save-btn");
    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", (e) => this._onAvatarPick(e));
    }
    if (saveBtn) saveBtn.addEventListener("click", () => this.savePersona());
    this.loadPersona();
    // R7.5: user-side avatar + name. Pure localStorage, no backend.
    this._initUserControls();
  }

  _initUserControls() {
    const uploadBtn = document.getElementById("user-avatar-upload");
    const fileInput = document.getElementById("user-avatar-file");
    const saveBtn = document.getElementById("user-save-btn");
    const nameInput = document.getElementById("user-name");
    const preview = document.getElementById("user-avatar-preview");
    // Pull cached state into the form fields.
    if (nameInput && window._chat) {
      const cached = (window._chat._userName || "").trim();
      if (cached) nameInput.value = cached === "你" ? "" : cached;
    }
    if (preview && window._chat && window._chat._userDataurl) {
      preview.src = window._chat._userDataurl;
    }
    if (uploadBtn && fileInput) {
      uploadBtn.addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", (e) => this._onUserAvatarPick(e));
    }
    if (saveBtn) saveBtn.addEventListener("click", () => this._saveUser());
  }

  _setUserStatus(text, ok = true) {
    const st = document.getElementById("user-status");
    if (!st) return;
    st.textContent = text;
    st.style.color = ok ? "var(--success)" : "var(--error)";
    if (text) setTimeout(() => { if (st.textContent === text) st.textContent = ""; }, 4000);
  }

  async _onUserAvatarPick(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    if (file.size > 2 * 1024 * 1024) {
      this._setUserStatus("文件过大（>2MB）", false);
      e.target.value = "";
      return;
    }
    if (!/^image\/(png|jpeg)$/.test(file.type)) {
      this._setUserStatus("只支持 PNG / JPG", false);
      e.target.value = "";
      return;
    }
    this._setUserStatus("设置中… / Setting…", true);
    // Read as dataURL and push straight into the chat cache.
    const dataurl = await new Promise((resolve) => {
      try {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result || ""));
        r.onerror = () => resolve("");
        r.readAsDataURL(file);
      } catch (_) { resolve(""); }
    });
    if (!dataurl) {
      this._setUserStatus("读取失败 / Read failed", false);
      e.target.value = "";
      return;
    }
    const preview = document.getElementById("user-avatar-preview");
    if (preview) preview.src = dataurl;
    if (window._chat && typeof window._chat.setUserAvatar === "function") {
      window._chat.setUserAvatar(dataurl);
    }
    this._setUserStatus("头像已更新 · Avatar updated", true);
    e.target.value = "";
  }

  _saveUser() {
    const nameInput = document.getElementById("user-name");
    const raw = (nameInput && nameInput.value || "").trim();
    if (window._chat && typeof window._chat.setUserName === "function") {
      window._chat.setUserName(raw);
    }
    this._setUserStatus("已记住你 · She'll remember you", true);
  }

  _setPersonaStatus(text, ok = true) {
    const st = document.getElementById("persona-status");
    if (!st) return;
    st.textContent = text;
    st.style.color = ok ? "var(--success)" : "var(--error)";
    if (text) setTimeout(() => { if (st.textContent === text) st.textContent = ""; }, 4000);
  }

  async loadPersona() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/persona" });
      const s = (r.data && !r.data.error) ? r.data : {};
      const nameEl = document.getElementById("persona-name");
      const enEl = document.getElementById("persona-english-name");
      if (nameEl) nameEl.value = s.name || "Aerie Companion";
      if (enEl) enEl.value = s.english_name || "Aerie";
      this._applyPersonaPronoun(s.gender || "");
      const img = document.getElementById("persona-avatar-preview");
      if (img) {
        // 角色级隔离：后端按激活角色返回独立 avatar_dataurl；
        // Electron file:// 下相对路径 /api/... 会 404，优先用 inline dataURL。
        if (s.avatar_dataurl) {
          img.src = s.avatar_dataurl;
        } else if (s.avatar_url) {
          // append a cache-buster so re-uploads show
          img.src = s.avatar_url + (s.avatar_url.indexOf("?") >= 0 ? "&_t=" : "?_t=") + Date.now();
        } else {
          const fallback = img.getAttribute("data-default-src") || "assets/avatar_default.svg";
          img.src = fallback;
        }
      }
    } catch (e) {
      this._setPersonaStatus("加载失败: " + e.message, false);
    }
  }

  // Pronoun-aware labels for the persona panel (她/他/TA), driven by the
  // currently-active persona's gender.
  _applyPersonaPronoun(gender) {
    this._personaPronoun = gender === "male" ? "他" : gender === "other" ? "TA" : "她";
    const ids = ["persona-pronoun-title", "persona-pronoun-subj", "persona-pronoun-obj", "persona-pronoun-save"];
    ids.forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.textContent = this._personaPronoun;
    });
  }

  async _onAvatarPick(e) {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    // Client-side cap (2 MB) — matches server
    if (file.size > 2 * 1024 * 1024) {
      this._setPersonaStatus("文件过大（>2MB）", false);
      e.target.value = "";
      return;
    }
    if (!/^image\/(png|jpeg)$/.test(file.type)) {
      this._setPersonaStatus("只支持 PNG / JPG", false);
      e.target.value = "";
      return;
    }
    this._setPersonaStatus("上传中… / Uploading…", true);
    // R7.5 fix: read the file as dataURL RIGHT NOW so the preview
    // updates immediately — the previous version only set
    // `img.src = data.url` which is a relative HTTP path that
    // Electron's file:// cannot resolve, producing a broken-image
    // icon in the settings panel even after a successful upload.
    const localDataUrl = await new Promise((resolve) => {
      try {
        const r = new FileReader();
        r.onload = () => resolve(String(r.result || ""));
        r.onerror = () => resolve("");
        r.readAsDataURL(file);
      } catch (_) { resolve(""); }
    });
    // R7.0 双通道：先走 IPC，失败再降级到 fetch。
    // IPC 路径由 main.js 的 ipcMain.handle("api:upload") 实现，
    // 它会把 multipart bytes 直发到 Python /api/persona/avatar，
    // 完全绕开 file:// + CORS。
    let r = null;
    try {
      if (window.aerie && window.aerie.api && window.aerie.api.upload) {
        const buf = new Uint8Array(await file.arrayBuffer());
        r = await window.aerie.api.upload({
          path: "/api/persona/avatar",
          filename: file.name || "avatar.png",
          contentType: file.type,
          bytes: Array.from(buf),
        });
        if (r && r.status && r.status >= 200 && r.status < 300) {
          const data = r.data || {};
          // R7.5 fix: prefer the inline dataURL from the response
          // (server now returns it). Fall back to our locally-read
          // dataURL, then to the HTTP URL (which only works in
          // non-Electron contexts).
          const finalSrc = data.avatar_dataurl || localDataUrl || data.url;
          const img = document.getElementById("persona-avatar-preview");
          if (img) img.src = finalSrc;
          // Cache the dataURL locally so the chat view picks it up
          // instantly (no /api/persona round-trip) and so a reload
          // shows the same image before the backend responds.
          if (data.avatar_dataurl && window._chat
              && typeof window._chat._writeLocalAvatar === "function") {
            window._chat._writeLocalAvatar("persona", data.avatar_dataurl, window._chat._personaId || undefined);
          } else if (localDataUrl && window._chat
              && typeof window._chat._writeLocalAvatar === "function") {
            window._chat._writeLocalAvatar("persona", localDataUrl, window._chat._personaId || undefined);
          }
          this._setPersonaStatus("头像已更新 · Avatar updated", true);
          // R7.5 fix: ship the dataURL in the event detail so chat.js
          // can update its cache + DOM in one frame, without waiting
          // for the next 30s poll. 角色级隔离：带归属角色，聊天窗口据此判断是否采纳。
          window.dispatchEvent(new CustomEvent("aerie:persona-updated", {
            detail: {
              avatar_url: data.url,
              avatar_dataurl: data.avatar_dataurl || localDataUrl,
              persona_id: (window._chat && window._chat._personaId) || "",
              source: "settings",
            },
          }));
          // 灵动岛头像同步：让主进程刷新绝对头像 URL 并广播到灵动岛窗口
          try { window.aerie?.islandControl?.refreshAvatar?.(); } catch (_) {}
          return;
        }
      }
    } catch (ipcErr) {
      // IPC 路径异常 → 落到 fetch 兜底
      console.warn("[avatar] IPC upload failed, falling back to fetch:", ipcErr && ipcErr.message);
    }
    // 兜底：直接 fetch。在 Electron 渲染进程里 file:// 通常被 CORS 拒，
    // 但 preload 暴露的同源代理有时候能通过。失败时给明确提示。
    try {
      const form = new FormData();
      form.append("file", file);
      const resp = await fetch((window.__API_BASE__ || "http://127.0.0.1:7890") + "/api/persona/avatar", {
        method: "POST",
        body: form,
      });
      const data = await resp.json().catch(() => ({}));
      if (resp.ok && data && data.status === "ok") {
        const finalSrc = data.avatar_dataurl || localDataUrl || data.url;
        const img = document.getElementById("persona-avatar-preview");
        if (img) img.src = finalSrc;
        if (data.avatar_dataurl && window._chat
            && typeof window._chat._writeLocalAvatar === "function") {
          window._chat._writeLocalAvatar("persona", data.avatar_dataurl, window._chat._personaId || undefined);
        } else if (localDataUrl && window._chat
            && typeof window._chat._writeLocalAvatar === "function") {
          window._chat._writeLocalAvatar("persona", localDataUrl, window._chat._personaId || undefined);
        }
        this._setPersonaStatus("头像已更新 · Avatar updated (fallback)", true);
        // R7.5 fix: same as the IPC path. 角色级隔离：带归属角色。
        window.dispatchEvent(new CustomEvent("aerie:persona-updated", {
          detail: {
            avatar_url: data.url,
            avatar_dataurl: data.avatar_dataurl || localDataUrl,
            persona_id: (window._chat && window._chat._personaId) || "",
            source: "settings-fallback",
          },
        }));
        return;
      }
      this._setPersonaStatus(
        "上传失败: " + ((data && (data.error || data.detail)) || ("HTTP " + resp.status))
        + " / 请确认后端已重启并点设置页右下角「重启后端」",
        false
      );
    } catch (err) {
      this._setPersonaStatus(
        "上传失败: " + err.message
        + " / 跨域被拦截，请点设置页「重启后端」后再试",
        false
      );
    } finally {
      e.target.value = "";
    }
  }

  async savePersona() {
    const nameEl = document.getElementById("persona-name");
    const enEl = document.getElementById("persona-english-name");
    const body = {
      name: (nameEl && nameEl.value || "").trim() || "Aerie Companion",
      english_name: (enEl && enEl.value || "").trim() || "Aerie",
    };
    this._setPersonaStatus("保存中… / Saving…", true);
    try {
      const r = await window.aerie.api.request({
        method: "PUT", path: "/api/persona", body,
      });
      if (r.data && r.data.status === "ok") {
        this._setPersonaStatus((this._personaPronoun || "她") + "记住了 · Saved", true);
        // Notify chat to refresh persona cache
        if (window._chat && typeof window._chat._loadPersona === "function") {
          window._chat._loadPersona();
        }
        // R6.4: also refresh the emotion dashboard's persona-derived
        // defaults so PAD + threshold bars reflect the new persona.
        if (window.emotionDashboard
          && typeof window.emotionDashboard._loadPersonaForDefaults === "function") {
          window.emotionDashboard._loadPersonaForDefaults();
        }
      } else {
        this._setPersonaStatus("保存失败: " + (r.data && (r.data.error || r.data.detail) || "unknown"), false);
      }
    } catch (e) {
      this._setPersonaStatus("保存失败: " + e.message, false);
    }
  }

  /* ── Dynamic Island Settings ────────────────── */
  _initIslandSettings() {
    const applyBtn = document.getElementById("di-settings-apply");
    const resetBtn = document.getElementById("di-settings-reset");
    const preview = document.getElementById("di-preview");
    const masterCheckbox = document.getElementById("di-master-enabled");
    const masterStatusEl = document.getElementById("di-master-status");
    const groupEl = document.querySelector(".settings-group--dynamic-island");

    if (!applyBtn || !preview) return;

    document.querySelectorAll('input[name="di-theme"]').forEach((radio) => {
      radio.addEventListener("change", (e) => {
        preview.classList.remove("theme-dark", "theme-pink", "theme-light");
        preview.classList.add(`theme-${e.target.value}`);
      });
    });

    applyBtn.addEventListener("click", () => this._applyIslandSettings());
    resetBtn.addEventListener("click", () => this._resetIslandSettings());

    // R8.1: master enable slider.
    //
    // State sync strategy:
    //   (1) On init: read getEnabled() once to set the slider to the REAL
    //       current state of the world, not just a hardcoded "checked".
    //   (2) On slider change: call setEnabled() → wait for Electron to
    //       actually confirm (ok=true) before treating it as committed.
    //       This avoids the classic "UI toggled but backend ignore" bug.
    //   (3) On enabled-change event: apply state unconditionally. This
    //       keeps the UI in sync if the user toggles on another window.
    if (masterCheckbox) {
      let internalSet = false;
      const setCheckedSafely = (val) => {
        internalSet = true;
        try {
          if (masterCheckbox.checked !== !!val) masterCheckbox.checked = !!val;
          if (groupEl) {
            groupEl.classList.toggle("di-disabled", !val);
          }
        } finally {
          internalSet = false;
        }
      };
      const setStatus = (text, cls) => {
        if (!masterStatusEl) return;
        if (!text) {
          masterStatusEl.style.display = "none";
          masterStatusEl.textContent = "";
          masterStatusEl.classList.remove("is-ok", "is-err");
          return;
        }
        masterStatusEl.textContent = text;
        masterStatusEl.style.display = "block";
        masterStatusEl.classList.remove("is-ok", "is-err");
        if (cls) masterStatusEl.classList.add(cls);
      };

      if (window.aerie?.islandControl) {
        window.aerie.islandControl.getEnabled?.().then((r) => {
          if (r && typeof r.enabled === "boolean") setCheckedSafely(r.enabled);
        }).catch(() => {});

        window.aerie.islandControl.onEnabledChange?.((data) => {
          if (data && typeof data.enabled === "boolean") setCheckedSafely(data.enabled);
        });
      }

      masterCheckbox.addEventListener("change", async (ev) => {
        if (internalSet) return;
        if (!window.aerie?.islandControl) {
          setStatus("Electron IPC 不可用，请重启应用", "is-err");
          ev.target.checked = !ev.target.checked;
          return;
        }
        const wanted = !!ev.target.checked;
        masterCheckbox.disabled = true;
        setStatus(wanted ? "正在开启灵动岛…" : "正在关闭灵动岛…");
        try {
          const r = await window.aerie.islandControl.setEnabled(wanted);
          if (!r || !r.ok) {
            setCheckedSafely(!wanted);
            const msg = (r && r.error) ? (r.error + "") : "未知错误";
            setStatus("切换失败：" + msg.slice(0, 120), "is-err");
            return;
          }
          setCheckedSafely(Boolean(r.enabled));
          const hint = r.prefsPath ? `（保存在 ${r.prefsPath}）` : "";
          setStatus(
            (r.enabled ? "灵动岛已开启" : "灵动岛已关闭") + (r.saved ? hint : "（设置未持久化）"),
            "is-ok"
          );
          setTimeout(() => setStatus(""), 3500);
        } catch (e) {
          setCheckedSafely(!wanted);
          setStatus("切换异常：" + (e.message || String(e)).slice(0, 120), "is-err");
        } finally {
          masterCheckbox.disabled = false;
        }
      });
    }

    this._loadIslandSettings();
  }

  /* ── 消息提醒总开关 ───────────────── */
  // 状态在 main 进程（notif_prefs.json）持久化；这里负责把滑块与真实状态
  // 双向同步，策略与灵动岛主开关一致：init 读取真实值、change 等 Electron
  // 确认后才算提交、enabled-change 事件无条件跟随。
  _initNotifSettings() {
    const masterCheckbox = document.getElementById("notif-master-enabled");
    const masterStatusEl = document.getElementById("notif-master-status");
    if (!masterCheckbox) return;

    let internalSet = false;
    const setCheckedSafely = (val) => {
      internalSet = true;
      try {
        if (masterCheckbox.checked !== !!val) masterCheckbox.checked = !!val;
      } finally {
        internalSet = false;
      }
    };
    const setStatus = (text, cls) => {
      if (!masterStatusEl) return;
      if (!text) {
        masterStatusEl.style.display = "none";
        masterStatusEl.textContent = "";
        masterStatusEl.classList.remove("is-ok", "is-err");
        return;
      }
      masterStatusEl.textContent = text;
      masterStatusEl.style.display = "block";
      masterStatusEl.classList.remove("is-ok", "is-err");
      if (cls) masterStatusEl.classList.add(cls);
    };

    if (window.aerie?.notifControl) {
      window.aerie.notifControl.getEnabled?.().then((r) => {
        if (r && typeof r.enabled === "boolean") setCheckedSafely(r.enabled);
      }).catch(() => {});
      window.aerie.notifControl.onEnabledChange?.((data) => {
        if (data && typeof data.enabled === "boolean") setCheckedSafely(data.enabled);
      });
    }

    masterCheckbox.addEventListener("change", async (ev) => {
      if (internalSet) return;
      if (!window.aerie?.notifControl) {
        setStatus("Electron IPC 不可用，请重启应用", "is-err");
        ev.target.checked = !ev.target.checked;
        return;
      }
      const wanted = !!ev.target.checked;
      masterCheckbox.disabled = true;
      setStatus(wanted ? "正在开启消息提醒…" : "正在关闭消息提醒…");
      try {
        const r = await window.aerie.notifControl.setEnabled(wanted);
        if (!r || !r.ok) {
          setCheckedSafely(!wanted);
          setStatus("切换失败：" + (((r && r.error) || "未知错误") + "").slice(0, 120), "is-err");
          return;
        }
        setCheckedSafely(Boolean(r.enabled));
        const hint = r.prefsPath ? `（保存在 ${r.prefsPath}）` : "";
        setStatus(
          (r.enabled ? "消息提醒已开启" : "消息提醒已关闭") + (r.saved ? hint : "（设置未持久化）"),
          "is-ok"
        );
        setTimeout(() => setStatus(""), 3500);
      } catch (e) {
        setCheckedSafely(!wanted);
        setStatus("切换异常：" + (e.message || String(e)).slice(0, 120), "is-err");
      } finally {
        masterCheckbox.disabled = false;
      }
    });
  }

  async _loadIslandSettings() {
    try {
      if (!window.aerie?.islandControl) return;
      const r = await window.aerie.islandControl.getConfig();
      if (!r || !r.ok) return;
      const cfg = r.config || {};

      const themeRadio = document.querySelector(`input[name="di-theme"][value="${cfg.theme || "dark"}"]`);
      if (themeRadio) themeRadio.checked = true;

      const preview = document.getElementById("di-preview");
      if (preview) {
        preview.classList.remove("theme-dark", "theme-pink", "theme-light");
        preview.classList.add(`theme-${cfg.theme || "dark"}`);
      }

      const interactionSel = document.getElementById("di-interaction");
      if (interactionSel) interactionSel.value = cfg.interaction || "click";

      if (cfg.capsuleComponents) {
        document.querySelectorAll('.di-comp-check input[data-comp]').forEach((cb) => {
          cb.checked = cfg.capsuleComponents.includes(cb.dataset.comp);
        });
      }

      if (cfg.expandedComponents) {
        document.querySelectorAll('.di-comp-check input[data-excomp]').forEach((cb) => {
          cb.checked = cfg.expandedComponents.includes(cb.dataset.excomp);
        });
      }
    } catch (e) {
      console.warn("load island settings failed", e);
    }
  }

  async _applyIslandSettings() {
    try {
      if (!window.aerie?.islandControl) return;

      const theme = document.querySelector('input[name="di-theme"]:checked')?.value || "dark";
      const interaction = document.getElementById("di-interaction")?.value || "click";

      const capsuleComponents = [];
      document.querySelectorAll('.di-comp-check input[data-comp]:checked').forEach((cb) => {
        capsuleComponents.push(cb.dataset.comp);
      });

      const expandedComponents = [];
      document.querySelectorAll('.di-comp-check input[data-excomp]:checked').forEach((cb) => {
        expandedComponents.push(cb.dataset.excomp);
      });

      const cfg = {
        theme,
        interaction,
        capsuleComponents: capsuleComponents.length > 0 ? capsuleComponents : ["companion", "status", "notifications"],
        expandedComponents: expandedComponents.length > 0 ? expandedComponents : ["quickActions", "notifList"],
      };

      const r = await window.aerie.islandControl.setConfig(cfg);
      if (r && r.ok) {
        const btn = document.getElementById("di-settings-apply");
        if (btn) {
          const origText = btn.textContent;
          btn.innerHTML = '<svg class="icon icon--14" style="margin-right:4px;vertical-align:-1px;color: var(--color-success, #10b981);"><use href="#icon-ui-check"/></svg>已应用';
          setTimeout(() => { btn.textContent = origText; }, 1500);
        }
      }
    } catch (e) {
      console.warn("apply island settings failed", e);
    }
  }

  async _resetIslandSettings() {
    const defaults = {
      theme: "dark",
      interaction: "click",
      capsuleComponents: ["companion", "status", "notifications"],
      expandedComponents: ["quickActions", "notifList"],
    };

    const preview = document.getElementById("di-preview");
    if (preview) {
      preview.classList.remove("theme-dark", "theme-pink", "theme-light");
      preview.classList.add("theme-dark");
    }

    const darkRadio = document.querySelector('input[name="di-theme"][value="dark"]');
    if (darkRadio) darkRadio.checked = true;

    const interactionSel = document.getElementById("di-interaction");
    if (interactionSel) interactionSel.value = "click";

    document.querySelectorAll('.di-comp-check input[data-comp]').forEach((cb) => {
      cb.checked = defaults.capsuleComponents.includes(cb.dataset.comp);
    });

    document.querySelectorAll('.di-comp-check input[data-excomp]').forEach((cb) => {
      cb.checked = defaults.expandedComponents.includes(cb.dataset.excomp);
    });

    try {
      if (window.aerie?.islandControl) {
        await window.aerie.islandControl.setConfig(defaults);
      }
    } catch (_) {}
  }

  // ── 办公模式：文件保存位置 ──────────────────────────

  async _initOfficeDir() {
    const input = document.getElementById("office-dir-input");
    const browseBtn = document.getElementById("office-dir-browse");
    const openBtn = document.getElementById("office-dir-open");
    const saveBtn = document.getElementById("office-dir-save");
    const resetBtn = document.getElementById("office-dir-reset");
    const status = document.getElementById("office-dir-status");
    if (!input || !browseBtn || !openBtn || !saveBtn || !resetBtn || !status) return;

    // 加载当前路径
    await this._loadOfficeDir();

    browseBtn.addEventListener("click", async () => {
      try {
        const current = input.value || "";
        let selected = null;
        if (window.aerie?.electron?.dialog?.openDirectory) {
          selected = await window.aerie.electron.dialog.openDirectory({
            title: "选择办公文件保存位置",
            defaultPath: current,
          });
        }
        if (selected) {
          input.value = selected;
          status.textContent = "";
          status.className = "settings-hint";
        }
      } catch (e) {
        status.textContent = "选择文件夹失败：" + (e.message || e);
        status.className = "settings-hint office-dir-status--error";
      }
    });

    openBtn.addEventListener("click", async () => {
      const path = input.value;
      if (!path) return;
      try {
        if (window.aerie?.electron?.shell?.openPath) {
          await window.aerie.electron.shell.openPath(path);
        }
      } catch (e) {
        status.textContent = "打开文件夹失败：" + (e.message || e);
        status.className = "settings-hint office-dir-status--error";
      }
    });

    saveBtn.addEventListener("click", async () => {
      const path = input.value.trim();
      if (!path) {
        status.textContent = "请选择或输入一个路径";
        status.className = "settings-hint office-dir-status--error";
        return;
      }
      saveBtn.disabled = true;
      const original = saveBtn.textContent;
      saveBtn.textContent = "保存中...";
      try {
        const result = await this._apiRequest({
          method: "PUT",
          path: "/api/office/dir",
          body: { path },
        });
        if (result?.success) {
          status.textContent = "保存成功，新文件将保存到 " + result.path;
          status.className = "settings-hint office-dir-status--success";
          input.value = result.path;
        } else {
          status.textContent = "保存失败：" + (result?.error || "未知错误");
          status.className = "settings-hint office-dir-status--error";
        }
      } catch (e) {
        status.textContent = "保存失败：" + (e.message || e);
        status.className = "settings-hint office-dir-status--error";
      } finally {
        saveBtn.disabled = false;
        saveBtn.textContent = original;
      }
    });

    resetBtn.addEventListener("click", async () => {
      resetBtn.disabled = true;
      const original = resetBtn.textContent;
      resetBtn.textContent = "恢复中...";
      try {
        const result = await this._apiRequest({
          method: "PUT",
          path: "/api/office/dir",
          body: { path: "~/AerieOffice" },
        });
        if (result?.success) {
          status.textContent = "已恢复默认位置：" + result.path;
          status.className = "settings-hint office-dir-status--success";
          input.value = result.path;
        } else {
          status.textContent = "恢复失败：" + (result?.error || "未知错误");
          status.className = "settings-hint office-dir-status--error";
        }
      } catch (e) {
        status.textContent = "恢复失败：" + (e.message || e);
        status.className = "settings-hint office-dir-status--error";
      } finally {
        resetBtn.disabled = false;
        resetBtn.textContent = original;
      }
    });
  }

  async _loadOfficeDir() {
    const input = document.getElementById("office-dir-input");
    if (!input) return;
    try {
      const result = await this._apiRequest({
        method: "GET",
        path: "/api/office/dir",
      });
      if (result?.success) {
        input.value = result.path;
      }
    } catch (_) {
      // 静默失败，保持默认 placeholder
    }
  }

  // ── 诊断数据：累计时长 + 手动打包/上传 ──────────────

  _initDiagnostics() {
    const exportBtn = document.getElementById("diag-export-btn");
    const uploadBtn = document.getElementById("diag-upload-btn");
    if (exportBtn) exportBtn.addEventListener("click", () => this._diagExport());
    if (uploadBtn) uploadBtn.addEventListener("click", () => this._diagUpload());
    this._refreshDiagnostics();
  }

  _diagStatus(text, ok = true) {
    const st = document.getElementById("diag-status");
    if (!st) return;
    st.textContent = text || "";
    st.classList.remove("is-ok", "is-err");
    if (text && ok) st.classList.add("is-ok");
    if (text && !ok) st.classList.add("is-err");
  }

  _formatBytes(bytes) {
    const n = Number(bytes) || 0;
    if (n < 1024) return n + " B";
    if (n < 1024 * 1024) return (n / 1024).toFixed(1) + " KB";
    return (n / 1024 / 1024).toFixed(1) + " MB";
  }

  async _refreshDiagnostics() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/diagnostics/status" });
      const d = (r && r.data && !r.data.error) ? r.data : null;
      if (!d) return;

      const runtimeEl = document.getElementById("diag-runtime");
      if (runtimeEl) runtimeEl.textContent = d.total_runtime_human + "（" + d.total_runtime_seconds + " 秒）";

      const milestonesEl = document.getElementById("diag-milestones");
      if (milestonesEl) {
        const parts = (d.milestones || []).map((m) => {
          return (m.triggered ? "已触发 " : "未触发 ") + m.key + "（" + (m.seconds / 3600 >= 24 ? (m.seconds / 86400) + "天" : (m.seconds / 3600) + "小时") + "）";
        });
        milestonesEl.textContent = parts.length ? parts.join("  ·  ") : "—";
      }

      const endpointEl = document.getElementById("diag-endpoint");
      if (endpointEl) {
        endpointEl.textContent = d.upload_configured
          ? ("已配置 · " + d.upload_url_masked)
          : "未配置（仅本地打包，不自动上传）";
      }

      this._lastDiagPackages = d.packages || [];
      this._renderDiagPackages();
    } catch (e) {
      this._diagStatus("加载诊断状态失败：" + e.message, false);
    }
  }

  _renderDiagPackages() {
    const list = document.getElementById("diag-package-list");
    if (!list) return;
    const packages = this._lastDiagPackages || [];
    list.innerHTML = "";
    if (!packages.length) {
      list.innerHTML = '<span class="settings-hint">暂无诊断包，点击「手动打包」生成。</span>';
      return;
    }
    packages.forEach((p) => {
      const item = document.createElement("div");
      item.className = "diag-package-item";
      const meta = document.createElement("span");
      meta.className = "diag-package-meta";
      meta.textContent = p.filename;
      const size = document.createElement("span");
      size.className = "diag-package-size";
      size.textContent = this._formatBytes(p.size_bytes);
      meta.appendChild(size);

      const dl = document.createElement("button");
      dl.type = "button";
      dl.className = "diag-download-link";
      dl.textContent = "下载";
      dl.addEventListener("click", () => this._diagDownload(p.filename));

      item.appendChild(meta);
      item.appendChild(dl);
      list.appendChild(item);
    });
  }

  _diagDownload(filename) {
    const url = (window.__API_BASE__ || "http://127.0.0.1:7890")
      + "/api/diagnostics/download/" + encodeURIComponent(filename);
    if (window.aerie?.electron?.shell?.openExternal) {
      window.aerie.electron.shell.openExternal(url);
    } else {
      window.open(url, "_blank", "noopener");
    }
  }

  async _diagExport() {
    const btn = document.getElementById("diag-export-btn");
    if (btn) btn.disabled = true;
    this._diagStatus("正在打包…");
    try {
      const r = await window.aerie.api.request({
        method: "POST",
        path: "/api/diagnostics/export",
        body: { reason: "manual" },
      });
      const d = (r && r.data) || {};
      if (d.error) throw new Error(d.error);
      this._diagStatus("已打包：" + d.filename + "（" + this._formatBytes(d.size_bytes) + "）", true);
      await this._refreshDiagnostics();
    } catch (e) {
      this._diagStatus("打包失败：" + e.message, false);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async _diagUpload() {
    const packages = this._lastDiagPackages || [];
    if (!packages.length) {
      this._diagStatus("暂无诊断包，请先点击「手动打包」。", false);
      return;
    }
    const latest = packages[0].filename;
    const btn = document.getElementById("diag-upload-btn");
    if (btn) btn.disabled = true;
    this._diagStatus("正在上传 " + latest + " …");
    try {
      const r = await window.aerie.api.request({
        method: "POST",
        path: "/api/diagnostics/upload",
        body: { filename: latest },
      });
      const d = (r && r.data) || {};
      if (d.ok) {
        this._diagStatus("上传成功 · " + latest, true);
      } else {
        this._diagStatus("上传失败：" + (d.error || "unknown"), false);
      }
    } catch (e) {
      this._diagStatus("上传失败：" + e.message, false);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  async _apiRequest({ method = "GET", path = "", body = null } = {}) {
    if (window.aerie?.api?.request) {
      const r = await window.aerie.api.request({
        method,
        path,
        body,
      });
      return (r && r.data) ? r.data : r;
    }
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body && method !== "GET") opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    return await resp.json();
  }
}

window.settingsPanel = new SettingsPanel();
