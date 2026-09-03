"use strict";
/* Settings panel — Phase 9 Batch 3: dual mode (form + YAML editor) */

class SettingsPanel {
  constructor() {
    this._currentMode = "form"; // "form" | "apikey" | "yaml"
    this._currentYamlFile = "settings.yaml";
    this._apikeyProviders = [];
    this._addedProviderKeys = new Set();
    this._customProviders = [];
    this._activeMenuTab = null;
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
    if (reloadApiBtn) reloadApiBtn.addEventListener("click", () => { this.loadEntitlement(); this.loadApiKeys(); this.loadBaiduMap(); this.loadModelRoles(); });
    const baiduSaveBtn = document.getElementById("baidu-map-save-btn");
    if (baiduSaveBtn) baiduSaveBtn.addEventListener("click", () => this.saveBaiduMap());
    const customApiToggle = document.getElementById("custom-api-toggle-btn");
    if (customApiToggle) customApiToggle.addEventListener("click", () => this.toggleCustomApi());
    const customApiSave = document.getElementById("custom-api-save-btn");
    if (customApiSave) customApiSave.addEventListener("click", () => this.saveModelRoles());
    const addBtn = document.getElementById("apikey-add-btn");
    if (addBtn) addBtn.addEventListener("click", () => this.toggleAddMenu());
    const customProviderSave = document.getElementById("custom-provider-save-btn");
    if (customProviderSave) customProviderSave.addEventListener("click", () => this.saveCustomProvider());
    const featureReloadBtn = document.getElementById("feature-api-reload-btn");
    if (featureReloadBtn) featureReloadBtn.addEventListener("click", () => this.loadFeatureApis());

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
    const yamlView = document.getElementById("settings-yaml-view");
    if (formView) formView.style.display = mode === "form" ? "" : "none";
    if (apikeyView) apikeyView.style.display = mode === "apikey" ? "" : "none";
    if (featureView) featureView.style.display = mode === "feature" ? "" : "none";
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
      this.loadModelRoles();
    } else if (mode === "feature") {
      this.loadFeatureApis();
    }
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

  async loadApiKeys() {
    const st = document.getElementById("apikey-status");
    try {
      if (st) { st.textContent = "加载中…"; st.style.color = "var(--text-muted, #999)"; }
      const r = await window.aerie.api.request({ method: "GET", path: "/api/env/providers" });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      this._apikeyProviders = (r && r.data && r.data.providers) || [];
      this._apikeyProviders.forEach((p) => {
        if (p.configured) this._addedProviderKeys.add(p.key);
      });
      await this._loadCustomProviders();
      this._renderApiKeyList();
      this._renderAddBadge();
      if (st) { st.textContent = ""; }
    } catch (e) {
      if (st) { st.textContent = "加载失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    }
  }

  _renderApiKeyList() {
    const list = document.getElementById("apikey-provider-list");
    if (!list) return;
    list.innerHTML = "";

    // 只渲染用户已添加的固定厂商（configured 或通过下拉菜单主动添加）
    const added = this._apikeyProviders.filter((p) => this._addedProviderKeys.has(p.key));
    added.forEach((p) => {
      let statusText = p.configured ? "已配置" : "未配置";
      let statusCls = "";
      if (p.health_status === "banned") {
        statusText = "余额耗尽";
        statusCls = "danger";
      } else if (p.health_status === "cooldown") {
        statusText = "限流冷却";
        statusCls = "warning";
      } else if (p.balance != null && p.balance !== "") {
        statusText = "余额 ¥" + p.balance;
        statusCls = "success";
      }
      const card = document.createElement("div");
      card.className = "apikey-provider-card" + (p.configured ? " configured" : "");
      card.innerHTML = `
        <div class="apikey-provider-header">
          <div class="apikey-provider-name">
            <span class="apikey-provider-dot" style="background: ${p.configured ? 'var(--success, #2ecc71)' : 'var(--text-muted, #999)'}"></span>
            ${p.name}
          </div>
          <div class="apikey-provider-status" style="${statusCls === 'danger' ? 'color:var(--danger,#e74c3c);' : statusCls === 'success' ? 'color:var(--success,#2ecc71);' : statusCls === 'warning' ? 'color:var(--warning,#f39c12);' : ''}">${statusText}</div>
        </div>
        <div class="apikey-provider-fields">
          <label class="apikey-field">
            <span>API Key</span>
            <div class="apikey-input-row">
              <input type="password" class="apikey-input" data-provider="${p.key}" data-field="api_key"
                     value="${p.configured ? p.api_key_masked : ''}" placeholder="请输入 API Key">
              <button type="button" class="apikey-toggle-btn" data-provider="${p.key}" title="显示/隐藏">
                <svg class="icon icon--14" aria-hidden="true"><use href="#icon-ui-eye"/></svg>
              </button>
            </div>
          </label>
          <label class="apikey-field">
            <span>Base URL</span>
            <input type="text" class="apikey-input" data-provider="${p.key}" data-field="base_url"
                   value="${p.base_url || ''}" placeholder="${p.default_url}">
          </label>
          <label class="apikey-field">
            <span>模型 · Model</span>
            <input type="text" class="apikey-input" data-provider="${p.key}" data-field="model"
                   value="${p.model || ''}" placeholder="${p.default_model}">
          </label>
        </div>
        <div class="apikey-provider-actions">
          <button type="button" class="btn btn-primary btn-sm apikey-save-btn" data-provider="${p.key}">
            保存 · Save
          </button>
          <button type="button" class="btn btn-secondary btn-sm apikey-default-btn" data-provider="${p.key}">
            恢复默认 URL/模型
          </button>
          <button type="button" class="btn btn-secondary btn-sm apikey-remove-btn" data-provider="${p.key}">
            移除
          </button>
        </div>
      `;
      list.appendChild(card);
    });

    // 渲染自定义 API（用户添加的任意 OpenAI 兼容 API）
    this._customProviders.forEach((cp) => {
      const card = document.createElement("div");
      card.className = "apikey-provider-card configured";
      card.innerHTML = `
        <div class="apikey-provider-header">
          <div class="apikey-provider-name">
            <span class="apikey-provider-dot" style="background: var(--accent, #ff5b9c)"></span>
            ${cp.name || "自定义 API"}
          </div>
          <div class="apikey-provider-status" style="color:var(--success,#2ecc71);">已添加</div>
        </div>
        <div style="font-size:12px;color:var(--text-muted,#999);line-height:1.7;margin:0 0 8px;">
          Base URL：${cp.base_url || "-"}<br>
          模型：${cp.model || "-"}<br>
          工具调用上限：${cp.max_tool_calls || 8}
        </div>
        <div class="apikey-provider-actions">
          <button type="button" class="btn btn-secondary btn-sm custom-provider-remove-btn" data-id="${cp.id}">移除</button>
        </div>
      `;
      list.appendChild(card);
    });

    if (!added.length && !this._customProviders.length) {
      list.innerHTML = '<div style="font-size:12px;color:var(--text-muted,#999);padding:12px 0;">尚未添加任何 AI 厂商，点击上方「＋ 添加模型」开始。</div>';
    }

    // Bind events
    list.querySelectorAll(".apikey-save-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const provider = e.target.getAttribute("data-provider");
        this._saveApiKey(provider);
      });
    });
    list.querySelectorAll(".apikey-default-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const provider = e.target.getAttribute("data-provider");
        this._resetToDefault(provider);
      });
    });
    list.querySelectorAll(".apikey-toggle-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const provider = e.target.getAttribute("data-provider");
        const input = list.querySelector(`.apikey-input[data-provider="${provider}"][data-field="api_key"]`);
        if (input) {
          input.type = input.type === "password" ? "text" : "password";
        }
      });
    });
    list.querySelectorAll(".apikey-remove-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        const provider = e.target.getAttribute("data-provider");
        this._addedProviderKeys.delete(provider);
        this._renderApiKeyList();
      });
    });
    list.querySelectorAll(".custom-provider-remove-btn").forEach((btn) => {
      btn.addEventListener("click", async (e) => {
        const id = e.target.getAttribute("data-id");
        this._customProviders = this._customProviders.filter((c) => c.id !== id);
        await this._saveCustomProviders();
        this._renderApiKeyList();
      });
    });

    this._renderApiKeyCountReminder();
    this._renderAddBadge();
  }

  // ── 添加模型下拉菜单 ────────────────────────────────
  toggleAddMenu() {
    const menu = document.getElementById("apikey-add-menu");
    if (!menu) return;
    const willShow = menu.style.display === "none";
    if (willShow) {
      this._renderAddMenu();
      menu.style.display = "";
    } else {
      menu.style.display = "none";
    }
  }

  _renderAddMenu() {
    const tabsEl = document.getElementById("apikey-menu-tabs");
    const panelEl = document.getElementById("apikey-menu-panel");
    if (!tabsEl || !panelEl) return;
    tabsEl.innerHTML = "";

    const tabs = [
      ...this._apikeyProviders.map((p) => ({ type: "provider", key: p.key, name: p.name })),
      { type: "custom", key: "__custom__", name: "自定义 API" },
    ];
    if (!this._activeMenuTab) this._activeMenuTab = tabs[0].key;

    tabs.forEach((t) => {
      const active = t.key === this._activeMenuTab;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = t.name;
      btn.style.cssText =
        "text-align:left;padding:8px 10px;border-radius:8px;border:none;background:" +
        (active ? "var(--accent,#ff5b9c)" : "transparent") +
        ";color:" +
        (active ? "#fff" : "var(--text,#333)") +
        ";font-size:13px;cursor:pointer;";
      btn.addEventListener("click", () => {
        this._activeMenuTab = t.key;
        this._renderAddMenu();
      });
      tabsEl.appendChild(btn);
    });

    this._renderMenuPanel(panelEl);
  }

  _renderMenuPanel(panelEl) {
    panelEl.innerHTML = "";
    if (this._activeMenuTab === "__custom__") {
      this._openCustomProviderPanel();
      const hint = document.createElement("div");
      hint.style.cssText = "font-size:12px;color:var(--text-muted,#999);line-height:1.6;";
      hint.textContent = "已打开下方「自定义 API」配置面板，可添加任意 OpenAI 兼容 API（如 TokenDance）。";
      panelEl.appendChild(hint);
      return;
    }
    const p = this._apikeyProviders.find((x) => x.key === this._activeMenuTab);
    if (!p) return;
    const models = (p.models && p.models.length) ? p.models : [p.default_model];
    models.forEach((m) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = m;
      btn.style.cssText =
        "display:block;width:100%;text-align:left;padding:8px 10px;margin:0 0 6px;border-radius:8px;border:1px solid var(--border,rgba(0,0,0,0.08));background:transparent;color:var(--text,#333);font-size:12px;cursor:pointer;";
      btn.addEventListener("click", () => this._addProvider(p.key, m));
      panelEl.appendChild(btn);
    });
  }

  _addProvider(key, model) {
    this._addedProviderKeys.add(key);
    this._activeMenuTab = null;
    const menu = document.getElementById("apikey-add-menu");
    if (menu) menu.style.display = "none";
    this._renderApiKeyList();
    if (model) {
      const input = document.querySelector(`.apikey-input[data-provider="${key}"][data-field="model"]`);
      if (input) input.value = model;
    }
  }

  _renderAddBadge() {
    const badge = document.getElementById("apikey-add-badge");
    if (!badge) return;
    badge.textContent = String(this._addedProviderKeys.size + this._customProviders.length);
  }

  // ── 自定义 API（添加任意 OpenAI 兼容 API）────────────
  async _loadCustomProviders() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/env/custom-providers" });
      this._customProviders = (r && r.data && r.data.providers) || [];
    } catch (e) {
      this._customProviders = [];
    }
  }

  _openCustomProviderPanel() {
    const panel = document.getElementById("custom-provider-panel");
    if (!panel) return;
    panel.style.display = "";
    this._renderCustomProviderForm();
  }

  _renderCustomProviderForm() {
    const form = document.getElementById("custom-provider-form");
    if (!form) return;
    form.innerHTML = `
      <label class="apikey-field">
        <span>名称 · Name</span>
        <input type="text" id="custom-provider-name" class="apikey-input" placeholder="例如 TokenDance">
      </label>
      <label class="apikey-field">
        <span>Base URL</span>
        <input type="text" id="custom-provider-base-url" class="apikey-input" placeholder="例如 https://tokendance.space/v1">
      </label>
      <label class="apikey-field">
        <span>API Key</span>
        <input type="password" id="custom-provider-api-key" class="apikey-input" placeholder="sk-...">
      </label>
      <label class="apikey-field">
        <span>模型 · Model</span>
        <input type="text" id="custom-provider-model" class="apikey-input" placeholder="例如 gpt-4o">
      </label>
      <label class="apikey-field">
        <span>上下文 KV 键值对（可选，每行一个 key=value）</span>
        <textarea id="custom-provider-kv" class="apikey-input" rows="3" placeholder="temperature=0.7&#10;max_tokens=4096" style="resize:vertical;"></textarea>
      </label>
      <label class="apikey-field">
        <span>工具调用次数上限（默认 8）</span>
        <input type="number" id="custom-provider-max-tool-calls" class="apikey-input" value="8" min="1" max="50">
      </label>
    `;
  }

  async saveCustomProvider() {
    const st = document.getElementById("custom-provider-status");
    const btn = document.getElementById("custom-provider-save-btn");
    const name = (document.getElementById("custom-provider-name") || {}).value || "";
    const baseUrl = (document.getElementById("custom-provider-base-url") || {}).value || "";
    const apiKey = (document.getElementById("custom-provider-api-key") || {}).value || "";
    const model = (document.getElementById("custom-provider-model") || {}).value || "";
    const kvText = (document.getElementById("custom-provider-kv") || {}).value || "";
    const maxToolCalls = parseInt((document.getElementById("custom-provider-max-tool-calls") || {}).value || "8", 10);

    if (!name.trim() || !baseUrl.trim()) {
      if (st) { st.textContent = "请至少填写名称和 Base URL"; st.style.color = "var(--warning,#f39c12)"; }
      return;
    }
    const extraKv = {};
    kvText.split("\n").forEach((line) => {
      const s = line.trim();
      if (!s || s.indexOf("=") < 0) return;
      const idx = s.indexOf("=");
      const k = s.slice(0, idx).trim();
      const v = s.slice(idx + 1).trim();
      if (k) extraKv[k] = v;
    });

    const merged = this._customProviders.map((c) => ({
      id: c.id, name: c.name, base_url: c.base_url, api_key: "",
      model: c.model, extra_kv: c.extra_kv, max_tool_calls: c.max_tool_calls,
    }));
    merged.push({
      id: "", name: name.trim(), base_url: baseUrl.trim(), api_key: apiKey.trim(),
      model: model.trim(), extra_kv: extraKv, max_tool_calls: isNaN(maxToolCalls) ? 8 : maxToolCalls,
    });

    if (btn) btn.disabled = true;
    if (st) { st.textContent = "保存中…"; st.style.color = "var(--text-muted,#999)"; }
    try {
      const r = await window.aerie.api.request({ method: "POST", path: "/api/env/custom-providers", body: { providers: merged } });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      if (st) { st.textContent = "保存成功"; st.style.color = "var(--success,#2ecc71)"; }
      await this._loadCustomProviders();
      this._renderApiKeyList();
      const panel = document.getElementById("custom-provider-panel");
      if (panel) panel.style.display = "none";
      const menu = document.getElementById("apikey-add-menu");
      if (menu) menu.style.display = "none";
    } catch (e) {
      if (st) { st.textContent = "保存失败: " + e.message; st.style.color = "var(--danger,#e74c3c)"; }
    } finally {
      if (btn) btn.disabled = false;
      setTimeout(() => { if (st) st.textContent = ""; }, 5000);
    }
  }

  async _saveCustomProviders() {
    try {
      const body = this._customProviders.map((c) => ({
        id: c.id, name: c.name, base_url: c.base_url, api_key: "",
        model: c.model, extra_kv: c.extra_kv, max_tool_calls: c.max_tool_calls,
      }));
      await window.aerie.api.request({ method: "POST", path: "/api/env/custom-providers", body: { providers: body } });
    } catch (_) {}
  }

  // 配置数量提醒：少于 2 个 AI 厂商时提示主备容灾风险；
  // 达到 2 个及以上时切换为正常状态。loadApiKeys 与 _saveApiKey 保存后
  // 都会经 _renderApiKeyList 触发本方法，实现实时刷新。
  _renderApiKeyCountReminder() {
    const el = document.getElementById("apikey-count-reminder");
    if (!el) return;
    const count = this._apikeyProviders.filter((p) => p.configured === true).length;
    const ok = count >= 2;
    const accent = ok ? "var(--success, #2ecc71)" : "var(--warning, #f39c12)";

    el.style.display = "flex";
    el.style.alignItems = "flex-start";
    el.style.gap = "8px";
    el.style.margin = "0 0 14px";
    el.style.padding = "10px 12px";
    el.style.borderRadius = "10px";
    el.style.fontSize = "12px";
    el.style.lineHeight = "1.6";
    el.style.color = "var(--text-muted, #999)";
    el.style.background = ok ? "rgba(46, 204, 113, 0.10)" : "rgba(243, 156, 18, 0.12)";
    el.style.border = "1px solid " + (ok ? "rgba(46, 204, 113, 0.30)" : "rgba(243, 156, 18, 0.35)");

    const dot = '<span style="flex:0 0 auto;width:8px;height:8px;border-radius:50%;background:' + accent + ';margin-top:5px;"></span>';
    const countHtml = '<span style="color:' + accent + ';font-weight:600;">' + count + '</span>';
    const text = ok
      ? "已配置 " + countHtml + " 个 AI 厂商，主备容灾已就绪。"
      : "当前仅配置了 " + countHtml + " 个 AI 厂商。为保证对话稳定（主模型 + 备用模型容灾），建议至少配置 2 个 AI API。推荐：TokenDance（tokendance.space）或阿里云 DashScope（百炼），两者注册均有免费额度。";
    el.innerHTML = dot + "<span>" + text + "</span>";
  }

  async _saveApiKey(providerKey) {
    const st = document.getElementById("apikey-status");
    const list = document.getElementById("apikey-provider-list");
    const saveBtn = list.querySelector(`.apikey-save-btn[data-provider="${providerKey}"]`);
    const p = this._apikeyProviders.find((x) => x.key === providerKey);
    if (!p) return;

    const apiKeyInput = list.querySelector(`.apikey-input[data-provider="${providerKey}"][data-field="api_key"]`);
    const baseUrlInput = list.querySelector(`.apikey-input[data-provider="${providerKey}"][data-field="base_url"]`);
    const modelInput = list.querySelector(`.apikey-input[data-provider="${providerKey}"][data-field="model"]`);

    const apiKeyVal = apiKeyInput ? apiKeyInput.value.trim() : "";
    const baseUrlVal = baseUrlInput ? baseUrlInput.value.trim() : "";
    const modelVal = modelInput ? modelInput.value.trim() : "";

    if (!apiKeyVal && !p.configured) {
      if (st) { st.textContent = "请输入 API Key"; st.style.color = "var(--warning, #f39c12)"; }
      return;
    }

    if (saveBtn) saveBtn.disabled = true;
    if (st) { st.textContent = "保存中…"; st.style.color = "var(--text-muted, #999)"; }

    try {
      const body = { provider_key: providerKey };
      if (apiKeyVal && apiKeyVal !== p.api_key_masked) {
        body.api_key = apiKeyVal;
      }
      if (baseUrlVal) body.base_url = baseUrlVal;
      if (modelVal) body.model = modelVal;

      const r = await window.aerie.api.request({
        method: "POST",
        path: "/api/env/save",
        body,
      });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      if (st) { st.textContent = "保存成功，已生效"; st.style.color = "var(--success, #2ecc71)"; }
      await this.loadApiKeys();
    } catch (e) {
      if (st) { st.textContent = "保存失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    } finally {
      if (saveBtn) saveBtn.disabled = false;
    }
  }

  _resetToDefault(providerKey) {
    const list = document.getElementById("apikey-provider-list");
    const p = this._apikeyProviders.find((x) => x.key === providerKey);
    if (!p) return;
    const baseUrlInput = list.querySelector(`.apikey-input[data-provider="${providerKey}"][data-field="base_url"]`);
    const modelInput = list.querySelector(`.apikey-input[data-provider="${providerKey}"][data-field="model"]`);
    if (baseUrlInput) baseUrlInput.value = p.default_url;
    if (modelInput) modelInput.value = p.default_model;
  }

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

  // ── 自定义 API：模型功能点配置面板 ────────────────────
  toggleCustomApi() {
    const panel = document.getElementById("custom-api-panel");
    if (!panel) return;
    const willShow = panel.style.display === "none";
    panel.style.display = willShow ? "" : "none";
    if (willShow) this.loadModelRoles();
  }

  async loadModelRoles() {
    const list = document.getElementById("custom-api-role-list");
    if (!list) return;
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/env/model-roles" });
      const roles = (r && r.data && r.data.roles) || [];
      list.innerHTML = "";
      roles.forEach((role) => {
        const label = document.createElement("label");
        label.className = "apikey-field";
        const name = document.createElement("span");
        name.textContent = role.name + " · " + role.desc;
        const input = document.createElement("input");
        input.type = "text";
        input.className = "apikey-input";
        input.dataset.role = role.key;
        input.value = role.model || "";
        input.placeholder = "模型名 / model";
        label.appendChild(name);
        label.appendChild(input);
        list.appendChild(label);
      });
    } catch (e) {
      list.innerHTML = "<span style='font-size:12px;color:var(--danger,#e74c3c);'>加载失败: " + e.message + "</span>";
    }
  }

  async saveModelRoles() {
    const st = document.getElementById("custom-api-status");
    const btn = document.getElementById("custom-api-save-btn");
    const list = document.getElementById("custom-api-role-list");
    if (!list) return;
    const roles = [];
    list.querySelectorAll("input[data-role]").forEach((input) => {
      const v = input.value.trim();
      if (v) roles.push({ key: input.dataset.role, model: v });
    });
    if (!roles.length) {
      if (st) { st.textContent = "请至少填写一个模型"; st.style.color = "var(--warning,#f39c12)"; }
      return;
    }
    if (btn) btn.disabled = true;
    if (st) { st.textContent = "保存并热加载中…"; st.style.color = "var(--text-muted,#999)"; }
    try {
      const r = await window.aerie.api.request({ method: "POST", path: "/api/env/model-roles", body: { roles } });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      // 热加载：触发后端重载配置（无需整机重启）
      if (window.aerie && window.aerie.electron && window.aerie.electron.system && window.aerie.electron.system.reloadConfig) {
        try { await window.aerie.electron.system.reloadConfig(); } catch (_) {}
      }
      if (st) { st.textContent = "已保存并热加载"; st.style.color = "var(--success,#2ecc71)"; }
    } catch (e) {
      if (st) { st.textContent = "保存失败: " + e.message; st.style.color = "var(--danger,#e74c3c)"; }
    } finally {
      if (btn) btn.disabled = false;
      setTimeout(() => { if (st) st.textContent = ""; }, 5000);
    }
  }

  // ── 功能 API 配置：搜索 / 天气 / 位置等外部服务 ──────────
  async loadFeatureApis() {
    const list = document.getElementById("feature-api-list");
    if (!list) return;
    const st = document.getElementById("feature-api-status");
    try {
      if (st) { st.textContent = "加载中…"; st.style.color = "var(--text-muted, #999)"; }
      const r = await window.aerie.api.request({ method: "GET", path: "/api/env/feature-apis" });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      const features = (r && r.data && r.data.features) || [];
      this._renderFeatureApis(features);
      if (st) { st.textContent = ""; }
    } catch (e) {
      if (st) { st.textContent = "加载失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    }
  }

  _renderFeatureApis(features) {
    const list = document.getElementById("feature-api-list");
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
    const st = document.getElementById("feature-api-status");
    const list = document.getElementById("feature-api-list");
    if (!list) return;
    const fields = {};
    list.querySelectorAll(`input[data-feature="${featureKey}"]`).forEach((input) => {
      fields[input.dataset.env] = input.value.trim();
    });
    const btn = list.querySelector(`.feature-save-btn[data-feature="${featureKey}"]`);
    if (btn) btn.disabled = true;
    if (st) { st.textContent = "保存并热加载中…"; st.style.color = "var(--text-muted, #999)"; }
    try {
      const r = await window.aerie.api.request({ method: "POST", path: "/api/env/feature-apis", body: { feature_key: featureKey, fields } });
      if (r && r.data && r.data.error) throw new Error(r.data.error);
      await this.loadFeatureApis();
      if (st) { st.textContent = "已保存并热加载"; st.style.color = "var(--success, #2ecc71)"; }
    } catch (e) {
      if (st) { st.textContent = "保存失败: " + e.message; st.style.color = "var(--danger, #e74c3c)"; }
    } finally {
      if (btn) btn.disabled = false;
      setTimeout(() => { if (st) st.textContent = ""; }, 5000);
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

      // DSH work-mode delegation toggle — read back from dsh.enabled.
      const dshEl = document.getElementById("setting-dsh-enabled");
      if (dshEl) {
        dshEl.checked = ((s.dsh || {}).enabled) === true;
      }

      // DSH session window — read back from dsh.session_window_sec.
      const dshWinEl = document.getElementById("setting-dsh-session-window");
      if (dshWinEl) {
        const win = (s.dsh || {}).session_window_sec;
        if (win != null) dshWinEl.value = String(win);
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
      // DSH work-mode delegation toggle — persists into dsh.enabled + session window.
      dsh: {
        enabled: document.getElementById("setting-dsh-enabled")?.checked === true,
        session_window_sec: parseInt(document.getElementById("setting-dsh-session-window")?.value || "30", 10),
      },
    };
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
