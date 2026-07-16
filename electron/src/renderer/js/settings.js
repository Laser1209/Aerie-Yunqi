"use strict";
/* Settings panel — Phase 9 Batch 3: dual mode (form + YAML editor) */

class SettingsPanel {
  constructor() {
    this._currentMode = "form"; // "form" | "yaml"
    this._currentYamlFile = "settings.yaml";
  }

  init() {
    this.load();
    // Form view
    document.getElementById("settings-save-btn").addEventListener("click", () => this.save());
    document.getElementById("settings-reset-btn").addEventListener("click", () => this.reset());
    const themeSel = document.getElementById("setting-theme");
    if (themeSel) {
      themeSel.addEventListener("change", (e) => {
        if (window.themeSwitcher) {
          window.themeSwitcher.apply(e.target.value);
        }
      });
    }

    // Mode tabs
    document.querySelectorAll(".settings-mode-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        const mode = btn.getAttribute("data-mode");
        this._switchMode(mode);
      });
    });

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
  }

  _switchMode(mode) {
    this._currentMode = mode;
    document.querySelectorAll(".settings-mode-tab").forEach((b) => {
      b.classList.toggle("active", b.getAttribute("data-mode") === mode);
    });
    const formView = document.getElementById("settings-form-view");
    const yamlView = document.getElementById("settings-yaml-view");
    if (formView) formView.style.display = mode === "form" ? "" : "none";
    if (yamlView) yamlView.style.display = mode === "yaml" ? "" : "none";
    if (mode === "yaml") {
      this.loadYaml();
    }
  }

  async load() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/settings" });
      const s = (r.data && !r.data.error) ? r.data : {};
      const theme = s.theme || {};
      const startup = s.startup || {};
      const proactive = s.proactive || {};

      document.getElementById("setting-theme").value = theme.current || "yita-pink";
      document.getElementById("setting-auto-start").checked = startup.auto_start === true;
      document.getElementById("setting-start-minimized").checked = startup.start_minimized === true;
      document.getElementById("setting-proactive").checked = proactive.enabled !== false;
    } catch (e) {
      console.warn("settings load failed", e);
    }
  }

  async save() {
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
      },
    };
    try {
      const r = await window.aerie.api.request({ method: "PUT", path: "/api/settings", body: data });
      const st = document.getElementById("settings-status");
      if (r.data && !r.data.error) {
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
      this.load();
      const st = document.getElementById("settings-status");
      st.textContent = "已恢复默认设置";
      st.style.color = "var(--success)";
      setTimeout(() => { st.textContent = ""; }, 3000);
    } catch (e) {
      console.warn("settings reset failed", e);
    }
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
        st.textContent = "已保存。她下次启动会用新配置。/ Saved. She'll use this next time.";
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
}

window.settingsPanel = new SettingsPanel();
