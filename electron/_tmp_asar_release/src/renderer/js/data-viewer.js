"use strict";
/* Data viewer panel */
class DataViewer {
  constructor() {
    this.page = 1;
    this.limit = 20;
  }

  init() {
    // Sub-tabs
    document.querySelectorAll(".data-subtab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".data-subtab").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        const sub = btn.getAttribute("data-sub");
        this.showView(sub);
      });
    });

    // Pagination
    document.getElementById("data-prev-btn").addEventListener("click", () => { this.page--; this.loadChatLogs(); });
    document.getElementById("data-next-btn").addEventListener("click", () => { this.page++; this.loadChatLogs(); });

    this.loadChatLogs();
  }

  showView(sub) {
    document.querySelectorAll(".data-view").forEach((v) => { v.style.display = "none"; });
    const view = document.getElementById(`data-${sub}-view`);
    if (view) view.style.display = "block";
    if (sub === "chat") this.loadChatLogs();
    else if (sub === "knowledge") this.loadKnowledge();
    else if (sub === "system") this.loadSystem();
  }

  async loadChatLogs() {
    const offset = (this.page - 1) * this.limit;
    try {
      const r = await window.aerie.api.request({ method: "GET", path: `/api/chat/history?page=${this.page}&limit=${this.limit}` });
      const history = r.data?.history || [];
      const el = document.getElementById("chat-log-list");
      if (history.length === 0) {
        el.innerHTML = "<p style='color:var(--color-text-muted);padding:16px 0;'>暂无聊天记录</p>";
      } else {
        let html = "";
        history.forEach((m) => {
          const roleIcon = m.role === "user" ? "你" : "伊塔";
          const time = m.created_at ? m.created_at.slice(0, 19) : "";
          html += `<div class="chat-log-item">
            <span class="log-role">${roleIcon}</span>
            <span class="log-content">${this.esc(m.content || "").slice(0, 80)}</span>
            <span class="log-time">${time}</span>
          </div>`;
        });
        el.innerHTML = html;
      }
      document.getElementById("data-page-info").textContent = `第 ${this.page} 页`;
      document.getElementById("data-prev-btn").disabled = this.page <= 1;
      document.getElementById("data-next-btn").disabled = history.length < this.limit;
    } catch (e) {
      document.getElementById("chat-log-list").innerHTML = "<p style='color:var(--error);'>加载失败</p>";
    }
  }

  async loadKnowledge() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/knowledge/list" });
      const items = r.data?.items || [];
      const el = document.getElementById("knowledge-list");
      if (items.length === 0) {
        el.innerHTML = "<p style='color:var(--color-text-muted);padding:16px 0;'>暂无知识库条目</p>";
      } else {
        let html = "";
        items.forEach((item) => {
          html += `<div class="chat-log-item">
            <span class="log-role" style="color:var(--color-primary);">${this.esc(item.category || "")}</span>
            <span class="log-content">${this.esc(item.title || "")}</span>
          </div>`;
        });
        el.innerHTML = html;
      }
    } catch (e) {
      document.getElementById("knowledge-list").innerHTML = "<p style='color:var(--error);'>加载失败</p>";
    }
  }

  async loadSystem() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/stats/system" });
      const d = r.data || {};
      document.getElementById("ds-uptime").textContent = d.uptime || "--";
      document.getElementById("ds-cpu").textContent = d.cpu || "--";
      document.getElementById("ds-memory").textContent = d.memory || "--";
      document.getElementById("ds-messages").textContent = d.message_count != null ? d.message_count : "--";
    } catch (e) {
      console.warn("system stats failed", e);
    }
  }

  esc(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
}

window.dataViewer = new DataViewer();
