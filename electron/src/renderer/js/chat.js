"use strict";
/* Chat manager: Phase 4 — recall + quote + attachment support */

class ChatManager {
  constructor(opts = {}) {
    this._el = {
      messages: document.getElementById("chat-messages"),
      input: document.getElementById("chat-input"),
      sendBtn: document.getElementById("chat-send-btn"),
    };
    this._seenIds = new Set();
    this._loading = false;
    this._masterQQ = opts.masterQQ || 3998874040;
    this._sinceId = 0;
    this._quotedMsg = null;            // Phase 4: currently quoted message
    this._pendingAttachments = [];     // Phase 5: file attachments awaiting send

    // Block-2 A1: persona + master avatar cache
    this._personaCache = { name: "伊塔", english_name: "Ita", avatar_url: "" };
    this._masterAvatar = "";

    this._bindEvents();
    this._listenIPC();
    this._listenOpenTab();
    this._startPoll();
    this.loadHistory();
    // Phase 5: file uploader
    if (window.ChatUploader) {
      this._uploader = new window.ChatUploader(this);
    }
    // Block-3 R0.2: voice input
    if (window.ChatVoice) {
      this._voice = new window.ChatVoice(this);
    }
    // Block-2 A1: load persona + master avatar (best-effort, fail-soft)
    this._loadPersona();
    this._loadMasterAvatar();
    // R6.6: periodic persona poll so an upload from the Settings page
    // (or another window) shows up in the chat without manual reload.
    // 30s is gentle on the API and matches the spec'd auto-refresh cadence.
    setInterval(() => this._loadPersona(), 30000);
    // R7.0: instant refresh on persona:updated event from settings.js.
    // Without this listener, an upload via the settings page only takes
    // effect after the 30s poll above — way too slow for the user.
    window.addEventListener("aerie:persona-updated", () => {
      try { this._loadPersona(); } catch (_) {}
    });
  }

  _bindEvents() {
    if (this._el.sendBtn) {
      this._el.sendBtn.addEventListener("click", () => this.send());
    }
    if (this._el.input) {
      this._el.input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          this.send();
        } else if (e.key === "Escape" && this._quotedMsg) {
          this._cancelQuote();
        }
      });
    }
    // Global click outside menu to close
    document.addEventListener("click", (e) => {
      if (!e.target.closest(".chat-msg-actions") && !e.target.closest(".chat-action-menu")) {
        this._closeAllActionMenus();
      }
    });
  }

  _listenIPC() {
    if (!window.aerie) return;
    window.aerie.api.onMessage((msg) => {
      // msg can be either a normal chat message or a recall event
      if (msg && msg.type === "recall") {
        this._markRecalled(msg.id);
        return;
      }
      if (this._seenIds.has(msg.id)) return;
      this._seenIds.add(msg.id);
      this._render(msg);
    });
  }

  // Block-2 T1 bridge: tray "设置" click → switch to settings tab
  _listenOpenTab() {
    if (window.aerie && window.aerie.electron && window.aerie.electron.onOpenTab) {
      window.aerie.electron.onOpenTab((tab) => {
        const btn = document.querySelector('.tab-btn[data-tab="' + tab + '"]');
        if (btn) btn.click();
      });
    }
  }

  // Block-2 A1: best-effort persona + master avatar fetch
  async _loadPersona() {
    try {
      const r = await this._request({ method: "GET", path: "/api/persona" });
      if (r && r.data && !r.data.error && typeof r.data === "object") {
        this._personaCache = {
          name: r.data.name || this._personaCache.name,
          english_name: r.data.english_name || this._personaCache.english_name,
          avatar_url: r.data.avatar_url || this._personaCache.avatar_url,
        };
        // R6.6: refresh avatar src on every rendered assistant message
        // so a freshly uploaded avatar shows up without a window reload.
        this._refreshAvatarsInDom();
      }
    } catch (_) { /* fail-soft: keep defaults */ }
  }

  // R6.6: re-render every message in the DOM with the current persona
  // cache. Cheap because the message list is small (≤ a few hundred)
  // and it only runs after a known persona change.
  _rerenderVisible() {
    if (!this._el || !this._el.messages) return;
    const messages = this._messages || [];
    if (!messages.length) return;
    this._el.messages.innerHTML = messages
      .map((m) => this._renderMessage(m))
      .join("");
    this._scrollToBottom();
  }

  async _loadMasterAvatar() {
    try {
      const r = await this._request({
        method: "GET",
        path: "/api/qq/avatar?user_id=" + this._masterQQ,
      });
      if (r && r.data && !r.data.error && typeof r.data.url === "string") {
        this._masterAvatar = r.data.url;
      }
    } catch (_) { /* fail-soft: keep empty */ }
  }

  _markRecalled(msgId) {
    const el = this._el.messages.querySelector(`[data-id="${msgId}"]`);
    if (!el) return;
    el.classList.add("chat-msg--recalled");
    el.innerHTML = `<div class="chat-bubble chat-bubble--recalled">（消息已撤回）</div>`;
  }

  _startPoll() {
    setInterval(async () => {
      try {
        const resp = await this._request({
          method: "GET",
          path: "/api/chat/poll?user_id=" + this._masterQQ + "&since_id=" + this._sinceId,
        });
        if (resp.data && resp.data.items) {
          for (const item of resp.data.items) {
            if (item.is_recalled) {
              this._markRecalled(item.id);
              continue;
            }
            if (this._seenIds.has(item.id)) continue;
            this._seenIds.add(item.id);
            this._render(item);
            if (item.id > this._sinceId) this._sinceId = item.id;
          }
        }
      } catch (_) {}
    }, 3000);
  }

  async loadHistory() {
    try {
      const resp = await this._request({
        method: "GET",
        path: "/api/chat/history?user_id=" + this._masterQQ + "&limit=50",
      });
      if (resp.data && resp.data.history) {
        const empty = this._el.messages.querySelector(".chat-empty");
        if (empty) empty.remove();
        for (const item of resp.data.history) {
          if (item.is_recalled) {
            this._renderRecalledStub(item);
            continue;
          }
          if (this._seenIds.has(item.id)) continue;
          this._seenIds.add(item.id);
          this._render(item);
          if (item.id > this._sinceId) this._sinceId = item.id;
        }
      }
    } catch (_) {}
  }

  _renderRecalledStub(item) {
    if (!this._el.messages) return;
    const div = document.createElement("div");
    div.className = "chat-msg chat-msg--recalled";
    div.setAttribute("data-id", item.id);
    div.innerHTML = `<div class="chat-bubble chat-bubble--recalled">（消息已撤回）</div>`;
    this._el.messages.appendChild(div);
  }

  async send() {
    if (this._loading) return;
    const text = this._el.input.value.trim();
    if (!text && this._pendingAttachments.length === 0) return;
    this._el.input.value = "";
    this._loading = true;

    const replyToId = this._quotedMsg ? this._quotedMsg.id : 0;
    const attachments = this._pendingAttachments.slice();

    // Optimistic render
    const tempId = "temp_" + Date.now();
    this._render({
      id: tempId,
      role: "user",
      content: text,
      reply_to_id: replyToId,
      reply_to_content: this._quotedMsg?.content || "",
      reply_to_role: this._quotedMsg?.role || "",
      attachments,
    });

    // Clear quote and attachments
    this._cancelQuote();
    this._pendingAttachments = [];
    this._renderAttachmentPreviews();

    try {
      const resp = await this._request({
        method: "POST",
        path: "/api/chat/send",
        body: {
          text,
          user_id: this._masterQQ,
          reply_to_id: replyToId,
          attachments,
        },
      });
      if (resp.data && resp.data.reply) {
        // Server reply already pushed via IPC; this is a fallback
      }
    } catch (err) {
      this._render({ id: tempId + "_err", role: "assistant", content: "发送失败: " + err.message });
    } finally {
      this._loading = false;
    }
  }

  // ── Phase 4: Quote helpers ──────────────────────────
  _quoteMessage(msg) {
    this._quotedMsg = msg;
    this._renderQuoteBar();
  }

  _cancelQuote() {
    this._quotedMsg = null;
    this._renderQuoteBar();
  }

  _renderQuoteBar() {
    let bar = document.getElementById("chat-quote-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "chat-quote-bar";
      bar.className = "chat-quote-bar";
      const inputArea = document.querySelector(".chat-input-area");
      if (inputArea) inputArea.parentNode.insertBefore(bar, inputArea);
    }
    if (!this._quotedMsg) {
      bar.style.display = "none";
      return;
    }
    bar.style.display = "flex";
    bar.innerHTML = `
      <span class="chat-quote-bar__icon"><svg class="icon icon--12" aria-hidden="true"><use href="#icon-reply"/></svg></span>
      <div class="chat-quote-bar__text">
        引用 ${this._quotedMsg.role === "user" ? "你" : "伊塔"}：
        <span class="chat-quote-bar__preview">${this._escapeHtml((this._quotedMsg.content || "").slice(0, 60))}</span>
      </div>
      <button class="chat-quote-bar__cancel" id="chat-quote-cancel" title="取消引用"><svg class="icon icon--12" aria-hidden="true"><use href="#icon-ui-close"/></svg></button>
    `;
    const cancelBtn = document.getElementById("chat-quote-cancel");
    if (cancelBtn) cancelBtn.addEventListener("click", () => this._cancelQuote());
  }

  _renderAttachmentPreviews() {
    let preview = document.getElementById("chat-attach-preview");
    if (!preview) {
      preview = document.createElement("div");
      preview.id = "chat-attach-preview";
      preview.className = "chat-attach-preview";
      const inputArea = document.querySelector(".chat-input-area");
      if (inputArea) inputArea.parentNode.insertBefore(preview, inputArea);
    }
    if (this._pendingAttachments.length === 0) {
      preview.style.display = "none";
      preview.innerHTML = "";
      return;
    }
    preview.style.display = "flex";
    // Block-3 R0.2: 4 态状态机 (uploading / converting / ready / failed)
    preview.innerHTML = this._pendingAttachments
      .map((a, i) => {
        const isDoc = a.is_doc === true;
        const state = a.state || "ready";   // uploading | converting | ready | failed
        const stateLabel = {
          uploading:  "上传中… / Uploading…",
          converting: "转 markdown 中… / Converting…",
          ready:      "",
          failed:     "她读不了这个 / She can't read this",
        }[state] || "";
        const stateClass = "chat-attach-thumb--state-" + state;
        if (a.type === "image") {
          return `<div class="chat-attach-thumb ${stateClass}" data-i="${i}"><img src="/uploads/${this._escapeHtml(a.url)}" alt=""><span class="chat-attach-thumb__state">${this._escapeHtml(stateLabel)}</span></div>`;
        }
        return `<div class="chat-attach-thumb ${stateClass}" data-i="${i}"><svg class="icon icon--14" aria-hidden="true"><use href="#icon-ui-attach"/></svg><span class="chat-attach-thumb__name">${this._escapeHtml(a.name)}</span><span class="chat-attach-thumb__state">${this._escapeHtml(stateLabel)}</span></div>`;
      })
      .join("");
  }

  // ── Phase 4: Action menu (recall / quote / copy) ──
  _closeAllActionMenus() {
    document.querySelectorAll(".chat-action-menu").forEach((m) => m.remove());
  }

  _showActionMenu(msg, anchorEl) {
    this._closeAllActionMenus();
    const menu = document.createElement("div");
    menu.className = "chat-action-menu";

    const ageSec = (Date.now() - new Date(msg.created_at || Date.now()).getTime()) / 1000;
    const canRecall = ageSec < 120 && !msg.is_recalled;

    menu.innerHTML = `
      <button class="chat-action-menu__item" data-act="copy"><svg class="icon icon--14" aria-hidden="true"><use href="#icon-ui-copy"/></svg>复制</button>
      <button class="chat-action-menu__item" data-act="quote"><svg class="icon icon--14" aria-hidden="true" style="transform: scaleX(-1) rotate(180deg)"><use href="#icon-ui-attach"/></svg>引用</button>
      ${canRecall ? '<button class="chat-action-menu__item" data-act="recall"><svg class="icon icon--14" aria-hidden="true" style="transform: scaleX(-1)"><use href="#icon-ui-attach"/></svg>撤回</button>' : ""}
    `;
    const rect = anchorEl.getBoundingClientRect();
    menu.style.position = "fixed";
    menu.style.top = rect.top + "px";
    menu.style.right = window.innerWidth - rect.left + "px";
    document.body.appendChild(menu);

    menu.querySelectorAll(".chat-action-menu__item").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const act = btn.getAttribute("data-act");
        this._closeAllActionMenus();
        if (act === "copy") {
          try {
            await navigator.clipboard.writeText(msg.content || "");
          } catch (_) {}
        } else if (act === "quote") {
          this._quoteMessage(msg);
          if (this._el.input) this._el.input.focus();
        } else if (act === "recall") {
          await this._recallMessage(msg);
        }
      });
    });
  }

  async _recallMessage(msg) {
    if (!confirm("确定撤回这条消息吗？")) return;
    try {
      const resp = await this._request({
        method: "POST",
        path: "/api/chat/recall/" + msg.id,
      });
      if (resp.data && resp.data.status === "ok") {
        this._markRecalled(msg.id);
      } else if (resp.data && resp.data.error) {
        alert("撤回失败: " + resp.data.error);
      }
    } catch (err) {
      alert("撤回失败: " + err.message);
    }
  }

  // ── Render ──
  _render(msg) {
    if (!this._el.messages) return;
    const empty = this._el.messages.querySelector(".chat-empty");
    if (empty) empty.remove();

    // Remove temp optimistic bubble if a real one is arriving
    if (msg.id && !String(msg.id).startsWith("temp_")) {
      const oldTemps = this._el.messages.querySelectorAll('[data-id^="temp_"]');
      oldTemps.forEach((t) => {
        if (t.getAttribute("data-temp-text") === msg.content) t.remove();
      });
    }

    // Don't re-render duplicate real messages
    if (
      msg.id &&
      !String(msg.id).startsWith("temp_") &&
      this._el.messages.querySelector(`[data-id="${msg.id}"]`)
    ) {
      return;
    }

    if (msg.is_recalled) {
      this._renderRecalledStub(msg);
      return;
    }

    const div = document.createElement("div");
    div.className = "chat-msg chat-msg--" + msg.role;
    div.setAttribute("data-id", msg.id);
    if (msg.id) div.setAttribute("data-msg-id", msg.id);
    if (msg.id) div.setAttribute("data-temp-text", msg.content);

    // Block-2 A1: avatar + name meta (above bubble)
    const isAssistant = msg.role === "assistant";
    const displayName = isAssistant
      ? (this._personaCache && this._personaCache.name) || "伊塔"
      : "你";
    const avatarUrl = isAssistant
      ? (this._personaCache && this._personaCache.avatar_url) || ""
      : this._masterAvatar || "";

    let html = "";
    // Block-2 A1 + R6.4: avatar on outer side, name (small) above bubble,
    // bubble below name. Outer-side flip via flex-direction: row-reverse.
    const avatarContent = avatarUrl
      ? `<img class="chat-msg__avatar" src="${this._escapeHtml(avatarUrl)}" alt="" onerror="this.style.visibility='hidden'">`
      : `<span class="chat-msg__avatar chat-msg__avatar--placeholder" aria-hidden="true">${isAssistant ? "伊" : "你"}</span>`;
    html += `<div class="chat-msg__avatar-wrap">${avatarContent}</div>`;
    html += `<div class="chat-msg__body">`;
    html += `<div class="chat-msg__name">${this._escapeHtml(displayName)}</div>`;
    // R6.5: timestamp (hover-only, shown by CSS when the message is
    // hovered). Format: HH:MM for today, MM-DD HH:MM for older messages.
    const tsText = this._formatTime(msg.ts);
    if (tsText) {
      html += `<span class="chat-msg__meta-time">${tsText}</span>`;
    }
    // Phase 4: quote overlay (above bubble)
    if (msg.reply_to_id && msg.reply_to_content) {
      const role = msg.reply_to_role === "user" ? "你" : "伊塔";
      html += `<div class="chat-quote-overlay" data-reply-to="${msg.reply_to_id}">
        <span class="chat-quote-overlay__bar"></span>
        <div class="chat-quote-overlay__text">
          <span class="chat-quote-overlay__author">引用 ${role}</span>
          <span class="chat-quote-overlay__preview">${this._escapeHtml((msg.reply_to_content || "").slice(0, 60))}</span>
        </div>
      </div>`;
    }
    // Phase 5: attachments
    if (msg.attachments && msg.attachments.length > 0) {
      html += '<div class="chat-attachments">';
      for (const att of msg.attachments) {
        if (att.type === "image") {
          html += `<div class="chat-attach-card" data-type="image"><img src="/uploads/${this._escapeHtml(att.url)}" alt=""></div>`;
        } else {
          html += `<div class="chat-attach-card" data-type="file"><svg class="icon icon--20" aria-hidden="true"><use href="#icon-ui-attach"/></svg>${this._escapeHtml(att.name || "文件")}</div>`;
        }
      }
      html += "</div>";
    }
    html += `<div class="chat-bubble">${this._escapeHtml(msg.content || "")}</div>`;
    html += `</div>`;  // close .chat-msg__body
    // Action menu trigger
    if (msg.id && !String(msg.id).startsWith("temp_")) {
      html += `<div class="chat-msg-actions"><button class="chat-msg-actions__btn" data-msg-actions="${msg.id}">⋮</button></div>`;
    }

    div.innerHTML = html;
    this._el.messages.appendChild(div);

    // Bind action button
    const actionsBtn = div.querySelector("[data-msg-actions]");
    if (actionsBtn) {
      actionsBtn.addEventListener("click", (e) => {
        e.stopPropagation();
        this._showActionMenu(msg, actionsBtn);
      });
    }

    // Bind quote overlay click → jump to original
    const quoteOverlay = div.querySelector(".chat-quote-overlay");
    if (quoteOverlay) {
      quoteOverlay.addEventListener("click", () => {
        const targetId = quoteOverlay.getAttribute("data-reply-to");
        const target = this._el.messages.querySelector(`[data-msg-id="${targetId}"]`);
        if (target) {
          target.scrollIntoView({ behavior: "smooth", block: "center" });
          target.classList.add("chat-msg--highlight");
          setTimeout(() => target.classList.remove("chat-msg--highlight"), 1500);
        }
      });
    }

    this._el.messages.scrollTop = this._el.messages.scrollHeight;
  }

  _escapeHtml(text) {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML.replace(/\n/g, "<br>");
  }

  // R6.5: format a timestamp for hover-only display on each message.
  // Accepts unix seconds (number), unix milliseconds (large number), or
  // ISO 8601 string. Returns "" for unparseable / missing input.
  _formatTime(ts) {
    if (ts === null || ts === undefined || ts === "") return "";
    let d;
    try {
      d = typeof ts === "number"
        ? new Date(ts < 1e12 ? ts * 1000 : ts)
        : new Date(ts);
    } catch (_) {
      return "";
    }
    if (isNaN(d.getTime())) return "";
    const now = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const hh = pad(d.getHours());
    const mm = pad(d.getMinutes());
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return `${hh}:${mm}`;
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hh}:${mm}`;
  }

  async _request(opts) {
    if (window.aerie) {
      try {
        return await window.aerie.api.request(opts);
      } catch (_) {}
    }
    const url = "http://127.0.0.1:7890" + opts.path;
    const init = {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" },
    };
    if (opts.body) init.body = JSON.stringify(opts.body);
    const r = await fetch(url, init);
    const data = await r.json();
    return { status: r.status, data };
  }
}

// Auto-init
window.addEventListener("DOMContentLoaded", () => {
  window._chat = new ChatManager();
});