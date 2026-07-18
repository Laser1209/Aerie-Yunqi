"use strict";
/* Settings panel — Phase 9 Batch 3: dual mode (form + YAML editor) */

class SettingsPanel {
  constructor() {
    this._currentMode = "form"; // "form" | "yaml"
    this._currentYamlFile = "settings.yaml";
  }

  init() {
    this.load();
    this._initIslandSettings();
    this._initOfficeDir();
    // Form view
    document.getElementById("settings-save-btn").addEventListener("click", () => this.save());
    document.getElementById("settings-reset-btn").addEventListener("click", () => this.reset());
    // R6.6: one-click backend restart. Schedules main.py to exit and
    // respawn; the Electron window stays open and the renderer keeps
    // polling /api/health until the new backend is up.
    const restartBtn = document.getElementById("settings-restart-btn");
    if (restartBtn) {
      // R7.0: preserve the original title so app.js can toggle a stale
      // hint without losing the base tooltip.
      if (!restartBtn.getAttribute("data-original-title")) {
        restartBtn.setAttribute("data-original-title", restartBtn.title || "");
      }
      restartBtn.addEventListener("click", () => this.restartBackend());
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

  async restartBackend() {
    const st = document.getElementById("settings-status");
    const btn = document.getElementById("settings-restart-btn");
    // v2.2: was `!window.aerie.invoke` which always triggered because
    // preload.js never exposed a top-level `invoke`. The real bridge
    // lives at window.aerie.electron.system.restartBackend
    // (preload.js → ipcRenderer.invoke("system:restart-backend")
    //  → main.js ipcMain.handle → POST /api/system/restart).
    if (!window.aerie || !window.aerie.electron || !window.aerie.electron.system || !window.aerie.electron.system.restartBackend) {
      if (st) st.textContent = "IPC 不可用";
      return;
    }
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
      const weather = s.weather || {};

      document.getElementById("setting-theme").value = theme.current || "yita-pink";
      document.getElementById("setting-auto-start").checked = startup.auto_start === true;
      document.getElementById("setting-start-minimized").checked = startup.start_minimized === true;
      document.getElementById("setting-proactive").checked = proactive.enabled !== false;

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
    } catch (e) {
      console.warn("settings load failed", e);
    }
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
      },
      // R7.1: empty string ⇒ resolver falls back to IP auto-detect.
      weather: {
        city: cityRaw,
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
      if (nameEl) nameEl.value = s.name || "伊塔";
      if (enEl) enEl.value = s.english_name || "Ita";
      const img = document.getElementById("persona-avatar-preview");
      if (img) {
        if (s.avatar_url) {
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
            window._chat._writeLocalAvatar("persona", data.avatar_dataurl);
          } else if (localDataUrl && window._chat
              && typeof window._chat._writeLocalAvatar === "function") {
            window._chat._writeLocalAvatar("persona", localDataUrl);
          }
          this._setPersonaStatus("头像已更新 · Avatar updated", true);
          // R7.5 fix: ship the dataURL in the event detail so chat.js
          // can update its cache + DOM in one frame, without waiting
          // for the next 30s poll.
          window.dispatchEvent(new CustomEvent("aerie:persona-updated", {
            detail: {
              avatar_url: data.url,
              avatar_dataurl: data.avatar_dataurl || localDataUrl,
              source: "settings",
            },
          }));
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
      const resp = await fetch("http://127.0.0.1:7890/api/persona/avatar", {
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
          window._chat._writeLocalAvatar("persona", data.avatar_dataurl);
        } else if (localDataUrl && window._chat
            && typeof window._chat._writeLocalAvatar === "function") {
          window._chat._writeLocalAvatar("persona", localDataUrl);
        }
        this._setPersonaStatus("头像已更新 · Avatar updated (fallback)", true);
        // R7.5 fix: same as the IPC path
        window.dispatchEvent(new CustomEvent("aerie:persona-updated", {
          detail: {
            avatar_url: data.url,
            avatar_dataurl: data.avatar_dataurl || localDataUrl,
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

    if (!applyBtn || !preview) return;

    document.querySelectorAll('input[name="di-theme"]').forEach((radio) => {
      radio.addEventListener("change", (e) => {
        preview.classList.remove("theme-dark", "theme-pink", "theme-light");
        preview.classList.add(`theme-${e.target.value}`);
      });
    });

    applyBtn.addEventListener("click", () => this._applyIslandSettings());
    resetBtn.addEventListener("click", () => this._resetIslandSettings());

    this._loadIslandSettings();
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

  async _apiRequest({ method = "GET", path = "", body = null } = {}) {
    if (window.aerie?.api?.request) {
      return await window.aerie.api.request({
        method,
        path,
        body,
      });
    }
    // Fallback: fetch
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body && method !== "GET") opts.body = JSON.stringify(body);
    const resp = await fetch(path, opts);
    return await resp.json();
  }
}

window.settingsPanel = new SettingsPanel();
