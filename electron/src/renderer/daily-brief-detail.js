"use strict";
/* Aerie · 云栖 v9.0 — Daily Brief detail window (Block-5A · 1280×800).
 *
 * 独立 BrowserWindow；查询 ?date=YYYY-MM-DD 或回退到今天。
 * - GET /api/brief/html?date=... → 渲染整页；fallback 到 /api/brief/today
 * - 导出按钮：触发浏览器下载当前 HTML
 */

const API_BASE = "http://127.0.0.1:7890";

class DailyBriefDetail {
  constructor() {
    this._date = this._parseDateFromURL() || this._todayStr();
    this._data = null;
    this._init();
  }

  _parseDateFromURL() {
    try {
      const u = new URL(window.location.href);
      const d = u.searchParams.get("date");
      if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) return d;
    } catch (_) {}
    return null;
  }

  _todayStr() {
    const d = new Date();
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
  }

  _formatDate(dateStr) {
    if (!dateStr || !/^\d{4}-\d{2}-\d{2}$/.test(dateStr)) return "—";
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
    const dt = new Date(+m[1], +m[2] - 1, +m[3]);
    const y = dt.getFullYear();
    const mo = dt.getMonth() + 1;
    const day = dt.getDate();
    const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    return `${y}年${mo}月${day}日 · ${weekdays[dt.getDay()]}`;
  }

  _init() {
    const dateEl = document.getElementById("detail-date");
    if (dateEl) dateEl.textContent = this._formatDate(this._date);

    const closeBtn = document.getElementById("detail-close");
    if (closeBtn) closeBtn.addEventListener("click", () => this.close());

    const refreshBtn = document.getElementById("detail-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => this.load());

    const exportBtn = document.getElementById("detail-export");
    if (exportBtn) exportBtn.addEventListener("click", () => this.exportHtml());

    this.load();
  }

  async load() {
    const main = document.getElementById("detail-main");
    if (main) main.classList.add("is-loading");
    try {
      const resp = await fetch(`${API_BASE}/api/brief/today`);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      this._data = data;
      this._date = (data && data.date) || this._date;
      const dateEl = document.getElementById("detail-date");
      if (dateEl) dateEl.textContent = this._formatDate(this._date);
      this.render(data);
    } catch (e) {
      console.warn("detail brief load failed:", e);
      this._renderEmpty();
    } finally {
      if (main) main.classList.remove("is-loading");
    }
  }

  render(data) {
    this._renderList("ai_news",   data && data.ai_news);
    this._renderList("it_news",   data && data.it_news);
    this._renderList("intl_news", data && data.intl_news);
    this._renderList("cn_news",   data && data.cn_news);
    this._renderWeather(data && data.weather);
  }

  _renderList(key, items) {
    const targetId = `detail-${key.replace("_", "-")}`;
    const ul = document.getElementById(targetId);
    const countEl = document.getElementById(`${targetId}-count`);
    if (!ul) return;
    if (!Array.isArray(items) || items.length === 0) {
      ul.innerHTML = '<li class="detail-empty">（暂无）</li>';
      if (countEl) countEl.textContent = "0";
      return;
    }
    if (countEl) countEl.textContent = String(items.length);
    ul.innerHTML = items.map((it, idx) => {
      const title = this._escapeHTML((it.title || "").trim());
      const summary = this._escapeHTML((it.summary || "").trim());
      const url = this._escapeAttr(it.url || "");
      const source = this._escapeHTML(it.source || "");
      const linkOpen = url ? `<a href="${url}" target="_blank" rel="noopener">` : "";
      const linkClose = url ? `</a>` : "";
      return `
        <li class="detail-item">
          <span class="detail-item__index">${String(idx + 1).padStart(2, "0")}</span>
          <div class="detail-item__body">
            <h3 class="detail-item__title">${linkOpen}${title}${linkClose}</h3>
            ${summary ? `<p class="detail-item__summary">${summary}</p>` : ""}
            <span class="detail-item__source">${source}</span>
          </div>
        </li>`;
    }).join("");
  }

  _renderWeather(w) {
    const cityEl = document.getElementById("detail-weather-city");
    const descEl = document.getElementById("detail-weather-desc");
    const hintEl = document.getElementById("detail-weather-hint");
    if (!cityEl || !descEl) return;
    if (!w) {
      cityEl.textContent = "—";
      descEl.textContent = "（暂无）";
      if (hintEl) hintEl.textContent = "";
      return;
    }
    cityEl.textContent = w.city || "—";
    const t = w.temp || "—";
    const d = w.desc || "—";
    descEl.textContent = `${d} · ${t}℃`;
    if (hintEl) hintEl.textContent = w.suggestion || "";
  }

  _renderEmpty() {
    ["ai_news", "it_news", "intl_news", "cn_news"].forEach((k) => {
      const targetId = `detail-${k.replace("_", "-")}`;
      const ul = document.getElementById(targetId);
      if (ul) ul.innerHTML = '<li class="detail-empty">（暂无）</li>';
    });
  }

  exportHtml() {
    if (!this._data) {
      this._notifyMain("brief:export-failed", { reason: "no_data" });
      return;
    }
    // 通知主进程：把当前 JSON 渲染成独立 HTML 并存到 downloads
    this._notifyMain("brief:export", { date: this._date, payload: this._data });
  }

  close() {
    if (window.aerie && window.aerie.electron && window.aerie.electron.notify) {
      window.aerie.electron.notify("brief:detail-close", {});
    } else {
      window.close();
    }
  }

  _notifyMain(channel, payload) {
    if (window.aerie && window.aerie.electron && window.aerie.electron.notify) {
      window.aerie.electron.notify(channel, payload || {});
    }
  }

  _escapeHTML(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
  _escapeAttr(s) {
    return String(s).replace(/"/g, "&quot;");
  }
}

window.DailyBriefDetail = DailyBriefDetail;
document.addEventListener("DOMContentLoaded", () => {
  if (window.__detailInstance) return;
  window.__detailInstance = new DailyBriefDetail();
});
