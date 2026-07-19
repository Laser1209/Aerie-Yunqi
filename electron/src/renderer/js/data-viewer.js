"use strict";
/* Data viewer panel */
class DataViewer {
  constructor() {
    this.activeSub = "chat";
    this.visible = false;
    this.pages = { chat: 1, knowledge: 1 };
    this.limits = { chat: 20, knowledge: 10 };
    this.meta = { chat: { total: 0 }, knowledge: { total: 0 } };
    this.locks = { chat: false, knowledge: false, system: false, save: false, delete: false };
    this.refreshTimer = null;
    this.searchTimer = null;
    this.editingId = null;
    this.knowledgeModalOpen = false;
    this.deleteId = null;
  }

  init() {
    document.querySelectorAll(".data-subtab").forEach((btn) => btn.addEventListener("click", () => {
      document.querySelectorAll(".data-subtab").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      this.showView(btn.getAttribute("data-sub"));
    }));
    document.getElementById("data-prev-btn").addEventListener("click", () => this.changePage("chat", -1));
    document.getElementById("data-next-btn").addEventListener("click", () => this.changePage("chat", 1));
    document.getElementById("knowledge-prev-btn").addEventListener("click", () => this.changePage("knowledge", -1));
    document.getElementById("knowledge-next-btn").addEventListener("click", () => this.changePage("knowledge", 1));
    const search = document.getElementById("knowledge-search");
    const category = document.getElementById("knowledge-category-filter");
    search.addEventListener("input", () => this.scheduleKnowledgeSearch());
    category.addEventListener("change", () => { clearTimeout(this.searchTimer); this.pages.knowledge = 1; this.loadKnowledge(); });
    document.getElementById("knowledge-add-btn").addEventListener("click", () => this.openKnowledgeModal());
    document.getElementById("knowledge-save-btn").addEventListener("click", () => this.saveKnowledge());
    document.querySelectorAll("[data-knowledge-close]").forEach((el) => el.addEventListener("click", () => this.closeKnowledgeModal()));
    document.querySelectorAll("[data-delete-close]").forEach((el) => el.addEventListener("click", () => this.closeDeleteModal()));
    document.getElementById("knowledge-delete-confirm").addEventListener("click", () => this.deleteKnowledge());
    this.showView("chat");
  }

  setVisible(visible) {
    this.visible = !!visible;
    if (this.refreshTimer) clearTimeout(this.refreshTimer);
    this.refreshTimer = null;
    if (this.visible) {
      this.refreshActive();
      this.scheduleRefresh();
    }
  }

  scheduleRefresh() {
    if (!this.visible) return;
    const delay = this.activeSub === "knowledge" ? 5000 : 3000;
    this.refreshTimer = setTimeout(async () => {
      await this.refreshActive();
      this.scheduleRefresh();
    }, delay);
  }

  async refreshActive() {
    if (this.activeSub === "chat") return this.loadChatLogs();
    if (this.activeSub === "knowledge" && !this.knowledgeModalOpen) return this.loadKnowledge();
    if (this.activeSub === "system") return this.loadSystem();
  }

  showView(sub) {
    this.activeSub = sub;
    document.querySelectorAll(".data-view").forEach((v) => { v.style.display = "none"; });
    const view = document.getElementById(`data-${sub}-view`);
    if (view) view.style.display = "block";
    this.refreshActive();
    if (this.visible) { if (this.refreshTimer) clearTimeout(this.refreshTimer); this.scheduleRefresh(); }
  }

  changePage(kind, delta) {
    if (this.locks[kind]) return;
    const totalPages = this.totalPages(kind);
    const next = Math.max(1, Math.min(totalPages, this.pages[kind] + delta));
    if (next === this.pages[kind]) return;
    this.pages[kind] = next;
    kind === "chat" ? this.loadChatLogs() : this.loadKnowledge();
  }

  totalPages(kind) { return Math.max(1, Math.ceil(this.meta[kind].total / this.limits[kind])); }

  async loadChatLogs() {
    if (this.locks.chat) return;
    this.locks.chat = true;
    const page = this.pages.chat;
    const el = document.getElementById("chat-log-list");
    try {
      const r = await window.aerie.api.request({ method: "GET", path: `/api/chat/history?page=${page}&limit=${this.limits.chat}` });
      const data = r.data || {};
      if (data.error) throw new Error(data.error);
      this.meta.chat.total = Number(data.total) || 0;
      const pages = this.totalPages("chat");
      if (page > pages) {
        this.pages.chat = pages;
        this.locks.chat = false;
        return this.loadChatLogs();
      }
      const actualPage = Number(data.page) || page;
      this.pages.chat = Math.max(1, Math.min(actualPage, pages));
      const history = Array.isArray(data.history) ? data.history : [];
      if (!history.length) el.innerHTML = `<p class="data-empty">${this.meta.chat.total ? "当前页暂无记录" : "暂无聊天记录"}</p>`;
      else el.innerHTML = history.map((m) => `<div class="chat-log-item"><span class="log-role">${this.esc(m.role === "user" ? "你" : "伊塔")}</span><span class="log-content">${this.esc(m.content || "").slice(0, 160)}</span><span class="log-time">${this.esc(m.created_at ? m.created_at.slice(0, 19) : "")}</span></div>`).join("");
      this.updatePagination("chat");
    } catch (e) { el.innerHTML = `<p class="data-error">加载失败：${this.esc(e.message || "请求错误")}</p>`; }
    finally { this.locks.chat = false; }
  }

  scheduleKnowledgeSearch() {
    clearTimeout(this.searchTimer);
    this.searchTimer = setTimeout(() => { this.pages.knowledge = 1; this.loadKnowledge(); }, 250);
  }

  async loadKnowledge() {
    if (this.locks.knowledge || this.knowledgeModalOpen) return;
    this.locks.knowledge = true;
    const page = this.pages.knowledge;
    const list = document.getElementById("knowledge-list");
    const status = document.getElementById("knowledge-status");
    const params = new URLSearchParams({ page, limit: this.limits.knowledge, search: document.getElementById("knowledge-search").value.trim(), category: document.getElementById("knowledge-category-filter").value.trim() });
    try {
      const r = await window.aerie.api.request({ method: "GET", path: `/api/knowledge/list?${params}` });
      const data = r.data || {};
      if (data.error) throw new Error(data.error);
      this.meta.knowledge.total = Number(data.total) || 0;
      const pages = this.totalPages("knowledge");
      if (page > pages) {
        this.pages.knowledge = pages;
        this.locks.knowledge = false;
        return this.loadKnowledge();
      }
      this.pages.knowledge = Math.max(1, Math.min(Number(data.page) || page, pages));
      const items = Array.isArray(data.items) ? data.items : [];
      status.textContent = "";
      list.innerHTML = items.length ? items.map((item) => `<article class="knowledge-item"><div class="knowledge-item-main"><div class="knowledge-item-meta"><span class="knowledge-category">${this.esc(item.category || "未分类")}</span><span class="knowledge-time">${this.esc(item.updated_at || "")}</span></div><h3>${this.esc(item.title || "无标题")}</h3><p>${this.esc(item.content || "").slice(0, 180)}</p><div class="knowledge-tags">${this.esc(item.tags || "")}</div></div><div class="knowledge-actions"><button class="btn btn-secondary btn-sm" data-edit-id="${this.esc(String(item.id))}">编辑</button><button class="btn btn-secondary btn-sm" data-delete-id="${this.esc(String(item.id))}">删除</button></div></article>`).join("") : `<p class="data-empty">${this.meta.knowledge.total ? "当前筛选暂无条目" : "暂无知识库条目"}</p>`;
      list.querySelectorAll("[data-edit-id]").forEach((b) => b.addEventListener("click", () => this.openKnowledgeModal(Number(b.dataset.editId))));
      list.querySelectorAll("[data-delete-id]").forEach((b) => b.addEventListener("click", () => this.openDeleteModal(Number(b.dataset.deleteId), b.closest(".knowledge-item").querySelector("h3").textContent)));
      this.updatePagination("knowledge");
    } catch (e) { status.textContent = `加载失败：${e.message || "请求错误"}`; list.innerHTML = ""; }
    finally { this.locks.knowledge = false; }
  }

  updatePagination(kind) {
    const pages = this.totalPages(kind), page = this.pages[kind], total = this.meta[kind].total;
    const prefix = kind === "chat" ? "data" : "knowledge";
    document.getElementById(`${prefix}-page-info`).textContent = `第 ${page} / ${pages} 页 · 共 ${total} 条`;
    document.getElementById(`${prefix}-prev-btn`).disabled = page <= 1;
    document.getElementById(`${prefix}-next-btn`).disabled = page >= pages;
  }

  openKnowledgeModal(id = null) {
    this.editingId = id;
    this.knowledgeModalOpen = true;
    document.getElementById("knowledge-modal-title").textContent = id ? "编辑知识" : "新增知识";
    document.getElementById("knowledge-form-error").textContent = "";
    ["category", "title", "content", "tags"].forEach((key) => { document.getElementById(`knowledge-form-${key}`).value = ""; });
    document.getElementById("knowledge-modal").classList.remove("hidden");
    if (id) this.loadKnowledgeDetail(id);
  }

  async loadKnowledgeDetail(id) {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: `/api/knowledge/${encodeURIComponent(id)}` });
      const item = r.data || {};
      ["category", "title", "content", "tags"].forEach((key) => { document.getElementById(`knowledge-form-${key}`).value = item[key] || ""; });
    } catch (e) { document.getElementById("knowledge-form-error").textContent = `加载失败：${e.message || "请求错误"}`; }
  }

  closeKnowledgeModal() { this.editingId = null; this.knowledgeModalOpen = false; document.getElementById("knowledge-modal").classList.add("hidden"); }

  async saveKnowledge() {
    if (this.locks.save) return;
    const body = {}; ["category", "title", "content", "tags"].forEach((key) => { body[key] = document.getElementById(`knowledge-form-${key}`).value.trim(); });
    if (!body.category || !body.title || !body.content) { document.getElementById("knowledge-form-error").textContent = "分类、标题和正文不能为空"; return; }
    this.locks.save = true;
    const button = document.getElementById("knowledge-save-btn"); button.disabled = true;
    try {
      await window.aerie.api.request({ method: this.editingId ? "PUT" : "POST", path: this.editingId ? `/api/knowledge/${encodeURIComponent(this.editingId)}` : "/api/knowledge", body });
      const wasNew = !this.editingId; this.closeKnowledgeModal(); if (wasNew) this.pages.knowledge = 1; await this.loadKnowledge();
    } catch (e) { document.getElementById("knowledge-form-error").textContent = `保存失败：${e.message || "请求错误"}`; }
    finally { this.locks.save = false; button.disabled = false; }
  }

  openDeleteModal(id, title) { this.deleteId = id; document.getElementById("knowledge-delete-message").textContent = `确定删除“${title}”吗？此操作不可撤销。`; document.getElementById("knowledge-delete-modal").classList.remove("hidden"); }
  closeDeleteModal() { this.deleteId = null; document.getElementById("knowledge-delete-modal").classList.add("hidden"); }

  async deleteKnowledge() {
    if (this.locks.delete || this.deleteId == null) return;
    this.locks.delete = true; const button = document.getElementById("knowledge-delete-confirm"); button.disabled = true;
    try { await window.aerie.api.request({ method: "DELETE", path: `/api/knowledge/${encodeURIComponent(this.deleteId)}` }); this.closeDeleteModal(); if (this.pages.knowledge > 1 && this.meta.knowledge.total - 1 <= (this.pages.knowledge - 1) * this.limits.knowledge) this.pages.knowledge--; await this.loadKnowledge(); }
    catch (e) { document.getElementById("knowledge-status").textContent = `删除失败：${e.message || "请求错误"}`; }
    finally { this.locks.delete = false; button.disabled = false; }
  }

  async loadSystem() {
    if (this.locks.system) return;
    this.locks.system = true;
    try { const r = await window.aerie.api.request({ method: "GET", path: "/api/stats/system" }); const d = r.data || {}; if (d.error) throw new Error(d.error); document.getElementById("ds-uptime").textContent = d.uptime || "--"; document.getElementById("ds-cpu").textContent = d.cpu || "--"; document.getElementById("ds-memory").textContent = d.memory || "--"; document.getElementById("ds-messages").textContent = d.message_count != null ? d.message_count : "--"; }
    catch (e) { ["ds-uptime", "ds-cpu", "ds-memory", "ds-messages"].forEach((id) => { document.getElementById(id).textContent = "加载失败"; }); }
    finally { this.locks.system = false; }
  }

  esc(value) { const div = document.createElement("div"); div.textContent = String(value == null ? "" : value); return div.innerHTML; }
}
window.dataViewer = new DataViewer();