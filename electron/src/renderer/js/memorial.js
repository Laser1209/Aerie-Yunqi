"use strict";
/* Memorial / Anniversary panel */
class MemorialPanel {
  constructor() {
    this.editingId = null;
  }

  init() {
    document.getElementById("mem-add-btn").addEventListener("click", () => this.showForm());
    document.getElementById("mem-cancel-btn").addEventListener("click", () => this.hideForm());
    document.getElementById("mem-save-btn").addEventListener("click", () => this.save());
    this.load();
  }

  async load() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/anniversary/list" });
      this.render(r.data || []);
    } catch (e) {
      document.getElementById("memorial-list").innerHTML = "<p style='color:var(--color-text-muted);'>加载失败</p>";
    }
  }

  render(items) {
    const el = document.getElementById("memorial-list");
    if (!items || items.length === 0) {
      el.innerHTML = "<p style='color:var(--color-text-muted);padding:16px 0;'>还没有纪念日，点击下方按钮添加～</p>";
      return;
    }
    let html = "";
    items.forEach((item) => {
      const days = item.days_since != null ? item.days_since : this.calcDays(item.date);
      html += `<div class="memorial-card">
        <div class="memorial-info">
          <div class="memorial-name">${this.esc(item.name)}</div>
          <div class="memorial-date">${item.date} · ${days} 天</div>
          ${item.description ? `<div class="memorial-desc">${this.esc(item.description)}</div>` : ""}
        </div>
        <div class="memorial-actions">
          <button class="btn btn-secondary btn-sm" data-edit="${item.id}">编辑</button>
          <button class="btn btn-secondary btn-sm" data-del="${item.id}" style="color:var(--error);">删除</button>
        </div>
      </div>`;
    });
    el.innerHTML = html;

    el.querySelectorAll("[data-edit]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const id = parseInt(btn.getAttribute("data-edit"));
        const item = items.find((i) => i.id === id);
        if (item) this.showForm(item);
      });
    });
    el.querySelectorAll("[data-del]").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const id = parseInt(btn.getAttribute("data-del"));
        if (confirm("确定删除这个纪念日吗？")) {
          await window.aerie.api.request({ method: "DELETE", path: `/api/anniversary/delete/${id}` });
          this.load();
        }
      });
    });
  }

  showForm(item) {
    const form = document.getElementById("memorial-form");
    const title = document.getElementById("memorial-form-title");
    if (item) {
      this.editingId = item.id;
      title.textContent = "编辑纪念日";
      document.getElementById("mem-name").value = item.name;
      document.getElementById("mem-date").value = item.date;
      document.getElementById("mem-type").value = item.type || "custom";
      document.getElementById("mem-desc").value = item.description || "";
    } else {
      this.editingId = null;
      title.textContent = "添加纪念日";
      document.getElementById("mem-name").value = "";
      document.getElementById("mem-date").value = "";
      document.getElementById("mem-type").value = "custom";
      document.getElementById("mem-desc").value = "";
    }
    form.style.display = "block";
    document.getElementById("mem-add-btn").style.display = "none";
  }

  hideForm() {
    document.getElementById("memorial-form").style.display = "none";
    document.getElementById("mem-add-btn").style.display = "";
    this.editingId = null;
  }

  async save() {
    const data = {
      name: document.getElementById("mem-name").value.trim(),
      date: document.getElementById("mem-date").value,
      type: document.getElementById("mem-type").value,
      description: document.getElementById("mem-desc").value.trim(),
    };
    if (!data.name || !data.date) {
      alert("名称和日期不能为空");
      return;
    }
    try {
      const path = this.editingId
        ? `/api/anniversary/update/${this.editingId}`
        : "/api/anniversary/add";
      const method = this.editingId ? "PUT" : "POST";
      await window.aerie.api.request({ method, path, body: data });
      this.hideForm();
      this.load();
    } catch (e) {
      alert("保存失败: " + e.message);
    }
  }

  calcDays(dateStr) {
    const d = new Date(dateStr);
    const now = new Date();
    const diff = Math.floor((now - d) / 86400000);
    return diff >= 0 ? diff : 0;
  }

  esc(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
}

window.memorialPanel = new MemorialPanel();
