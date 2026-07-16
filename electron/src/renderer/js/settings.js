"use strict";
/* Settings panel */
class SettingsPanel {
  init() {
    this.load();
    document.getElementById("settings-save-btn").addEventListener("click", () => this.save());
    document.getElementById("settings-reset-btn").addEventListener("click", () => this.reset());
    document.getElementById("setting-theme").addEventListener("change", (e) => {
      if (window.themeSwitcher) {
        window.themeSwitcher.apply(e.target.value);
      }
    });
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
}

window.settingsPanel = new SettingsPanel();
