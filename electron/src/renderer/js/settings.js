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

    // Block-2 A2: persona block controls
    this._initPersonaControls();

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
      if (nameEl) nameEl.value = s.name || "伊塔";
      if (enEl) enEl.value = s.english_name || "Ita";
      const img = document.getElementById("persona-avatar-preview");
      if (img) {
        if (s.avatar_url) {
          // append a cache-buster so re-uploads show
          img.src = s.avatar_url + (s.avatar_url.indexOf("?") >= 0 ? "&_t=" : "?_t=") + Date.now();
        } else {
          const fallback = img.getAttribute("data-default-src") || "/assets/avatar_ita_default.png";
          img.src = fallback;
        }
      }
    } catch (e) {
      this._setPersonaStatus("加载失败: " + e.message, false);
    }
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
    try {
      // Upload as multipart using fetch directly (window.aerie.api.request only does JSON)
      const form = new FormData();
      form.append("file", file);
      const r = await fetch("http://127.0.0.1:7890/api/persona/avatar", {
        method: "POST",
        body: form,
      });
      const data = await r.json().catch(() => ({}));
      if (r.ok && data && data.status === "ok") {
        const img = document.getElementById("persona-avatar-preview");
        if (img) img.src = data.url + (data.url.indexOf("?") >= 0 ? "&_t=" : "?_t=") + Date.now();
        this._setPersonaStatus("头像已更新 · Avatar updated", true);
      } else {
        this._setPersonaStatus("上传失败: " + (data && (data.error || data.detail)) || ("HTTP " + r.status), false);
      }
    } catch (err) {
      this._setPersonaStatus("上传失败: " + err.message, false);
    } finally {
      e.target.value = "";
    }
  }

  async savePersona() {
    const nameEl = document.getElementById("persona-name");
    const enEl = document.getElementById("persona-english-name");
    const body = {
      name: (nameEl && nameEl.value || "").trim() || "伊塔",
      english_name: (enEl && enEl.value || "").trim() || "Ita",
    };
    this._setPersonaStatus("保存中… / Saving…", true);
    try {
      const r = await window.aerie.api.request({
        method: "PUT", path: "/api/persona", body,
      });
      if (r.data && r.data.status === "ok") {
        this._setPersonaStatus("她记住了 · She remembers now", true);
        // Notify chat to refresh persona cache
        if (window._chat && typeof window._chat._loadPersona === "function") {
          window._chat._loadPersona();
        }
      } else {
        this._setPersonaStatus("保存失败: " + (r.data && (r.data.error || r.data.detail) || "unknown"), false);
      }
    } catch (e) {
      this._setPersonaStatus("保存失败: " + e.message, false);
    }
  }
}

window.settingsPanel = new SettingsPanel();
