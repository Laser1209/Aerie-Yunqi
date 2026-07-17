"use strict";
/* Aerie · 云栖 v9.0 — Daily Brief popup (Block-5A · 独立窗口 360px 卡片).
 *
 * 运行模式：独立 BrowserWindow (alwaysOnTop, frame=true) 而非 iframe。
 * - init(): GET /api/brief/today → 渲染 5 section
 * - "展开完整日报" 按钮 → 通知主进程打开 1280×800 详情页窗口
 * - 反馈 (thumb + comment) → POST /api/brief/feedback
 * - close(): 通知主进程隐藏
 */

const API_BASE = "http://127.0.0.1:7890";

class DailyBriefPopup {
  constructor() {
    this._data = null;
    this._feedback = { thumbs: {}, comments: {} };
    this._init();
  }

  _init() {
    const closeBtn = document.getElementById("brief-close");
    if (closeBtn) closeBtn.addEventListener("click", () => this.close());

    // R6.4: brand-strip refresh button — same action as re-fetching today.
    const refreshBtn = document.getElementById("brief-refresh");
    if (refreshBtn) refreshBtn.addEventListener("click", () => this.load());

    const expandLink = document.getElementById("brief-link-expand");
    if (expandLink) {
      expandLink.addEventListener("click", (e) => {
        e.preventDefault();
        this._notifyMain("brief:open-detail", { date: (this._data && this._data.date) || "" });
      });
    }

    const chatLink = document.getElementById("brief-link-chat");
    if (chatLink) {
      chatLink.addEventListener("click", (e) => {
        e.preventDefault();
        this._notifyMain("brief:chat", {});
      });
    }

    // Bind thumb + comment feedback
    document.querySelectorAll(".brief-section").forEach((sec) => {
      const section = sec.getAttribute("data-section");
      if (!section) return;
      sec.querySelectorAll(".brief-thumb").forEach((btn) => {
        btn.addEventListener("click", () => {
          const thumb = btn.getAttribute("data-thumb");
          this._toggleThumb(section, thumb, btn);
        });
      });
      const commentInput = sec.querySelector(".brief-comment");
      if (commentInput) {
        let timer = null;
        commentInput.addEventListener("input", () => {
          clearTimeout(timer);
          timer = setTimeout(() => {
            this._feedback.comments[section] = commentInput.value.trim();
            this._submitFeedbackDebounced();
          }, 600);
        });
      }
    });

    this._setGreeting();
    this.load();
  }

  _setGreeting() {
    const el = document.getElementById("brief-greeting");
    if (!el) return;
    const h = new Date().getHours();
    let g = "早上好";
    if (h >= 5  && h < 11) g = "早上好";
    else if (h >= 11 && h < 14) g = "中午好";
    else if (h >= 14 && h < 18) g = "下午好";
    else if (h >= 18 && h < 22) g = "晚上好";
    else g = "夜深了";
    el.textContent = `${g}，傻瓜`;
  }

  _formatDate(d) {
    const date = d || new Date();
    const y = date.getFullYear();
    const m = date.getMonth() + 1;
    const day = date.getDate();
    const weekdays = ["周日", "周一", "周二", "周三", "周四", "周五", "周六"];
    return `${y}年${m}月${day}日 · ${weekdays[date.getDay()]}`;
  }

  async load() {
    try {
      const resp = await fetch(`${API_BASE}/api/brief/today`);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      this._data = data;
      this.render(data);
    } catch (e) {
      this._setDate();
      console.warn("brief load failed:", e);
    }
  }

  render(data) {
    this._setDate(data && (data.date || (data.brief && data.brief.date)));
    // R6.6: API returns {date, brief: {ai_news, ...}, markdown, error}.
    // Unwrap data.brief so each section read sees the actual list/dict.
    const b = (data && data.brief) || data || {};
    this._renderList("ai_news",   b.ai_news);
    this._renderList("it_news",   b.it_news);
    this._renderList("intl_news", b.intl_news);
    this._renderList("cn_news",   b.cn_news);
    this._renderWeather(b.weather);
    // R6.6: surface fetch errors with a small inline notice so the user
    // can tell "no news" from "couldn't reach the network".
    if (data && data.error) {
      this._renderError(data.error, data.detail || "");
      return;
    }
    // R6.6: per-section errors from the fetcher. Show one consolidated
    // banner at the top of the popup so the user knows at least one
    // source failed even if other sections rendered fine.
    if (b.errors && Object.keys(b.errors).length > 0) {
      const errKeys = Object.keys(b.errors).filter((k) => k !== "weather" || !b.weather || b.weather.stub);
      if (errKeys.length > 0) {
        this._renderError("partial", errKeys.join(" / "));
      } else {
        this._renderErrorClear();
      }
    } else {
      this._renderErrorClear();
    }
  }

  _renderErrorClear() {
    const bar = document.getElementById("brief-error-bar");
    if (bar) {
      bar.remove();
    }
  }

  _renderError(code, detail) {
    // Use a body-level notice rather than per-section so it doesn't fight
    // with the (暂无) placeholders.
    const wrap = document.getElementById("brief-wrap") || document.body;
    let bar = document.getElementById("brief-error-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "brief-error-bar";
      bar.className = "brief-error-bar";
      wrap.insertBefore(bar, wrap.firstChild);
    }
    const msg = code === "fetch_failed"
      ? "网络不可用 / Network unavailable"
      : "拉取失败 / Fetch failed";
    bar.textContent = msg + (detail ? " — " + detail : "");
  }


  _setDate(dateStr) {
    const el = document.getElementById("brief-date");
    if (!el) return;
    if (dateStr) {
      const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(dateStr);
      if (m) {
        el.textContent = this._formatDate(new Date(+m[1], +m[2] - 1, +m[3]));
        return;
      }
    }
    el.textContent = this._formatDate();
  }

  _renderList(key, items) {
    const targetId = `brief-${key.replace("_", "-")}`;
    const ul = document.getElementById(targetId);
    if (!ul) return;
    if (!Array.isArray(items) || items.length === 0) {
      ul.innerHTML = '<li class="brief-empty">（暂无）</li>';
      return;
    }
    ul.innerHTML = items.slice(0, 5).map((it) => {
      const title = this._escapeHTML((it.title || "").trim());
      const url = this._escapeAttr(it.url || "");
      if (url) {
        return `<li><span class="brief-dot"></span><a href="${url}" target="_blank" rel="noopener">${title}</a></li>`;
      }
      return `<li><span class="brief-dot"></span><span>${title}</span></li>`;
    }).join("");
  }

  _renderWeather(w) {
    const cityEl = document.getElementById("brief-weather-city");
    const descEl = document.getElementById("brief-weather-desc");
    if (!cityEl || !descEl) return;
    if (!w) {
      cityEl.textContent = "—";
      descEl.textContent = "（暂无）";
      return;
    }
    cityEl.textContent = w.city || "—";
    const t = w.temp || "—";
    const d = w.desc || "—";
    descEl.textContent = `${d} · ${t}℃`;
  }

  _toggleThumb(section, thumb, btn) {
    const sec = btn.closest(".brief-section");
    if (!sec) return;
    const wasActive = btn.classList.contains("is-active");
    sec.querySelectorAll(".brief-thumb").forEach((b) => b.classList.remove("is-active"));
    if (!wasActive) {
      btn.classList.add("is-active");
      this._feedback.thumbs[section] = thumb;
    } else {
      delete this._feedback.thumbs[section];
    }
    this._submitFeedbackDebounced();
  }

  _submitFeedbackDebounced() {
    if (this._fbTimer) clearTimeout(this._fbTimer);
    this._fbTimer = setTimeout(() => this.submitFeedback(), 800);
  }

  async submitFeedback() {
    const sectionsLiked = [];
    const sectionsDisliked = [];
    for (const [k, v] of Object.entries(this._feedback.thumbs)) {
      if (v === "up")   sectionsLiked.push(k);
      if (v === "down") sectionsDisliked.push(k);
    }
    const payload = {
      thumbs: this._feedback.thumbs,
      sections_liked: sectionsLiked,
      sections_disliked: sectionsDisliked,
      comments: this._feedback.comments,
    };
    try {
      await fetch(`${API_BASE}/api/brief/feedback`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } catch (e) {
      console.warn("brief feedback failed:", e);
    }
  }

  close() {
    const wrap = document.getElementById("brief-wrap");
    if (wrap) wrap.classList.add("is-leaving");
    setTimeout(() => this._notifyMain("brief:hide", {}), 240);
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

window.DailyBriefPopup = DailyBriefPopup;
document.addEventListener("DOMContentLoaded", () => {
  if (window.__briefInstance) return;
  window.__briefInstance = new DailyBriefPopup();
});
