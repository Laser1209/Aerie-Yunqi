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
    this._requests = new Map();          // request_id -> RequestViewState
    this._clientToRequest = new Map();   // client_id -> request_id
    this._seenEventIds = new Set();
    this._requestSequences = new Map();  // request_id -> { next, pending }
    this._clientCounter = 0;
    this._reducedMotion = this._prefersReducedMotion();
    this._masterQQ = opts.masterQQ || 3998874040;
    this._sinceId = 0;
    this._quotedMsg = null;            // Phase 4: currently quoted message
    this._pendingAttachments = [];     // Phase 5: file attachments awaiting send

    // Block-2 A1: persona + master avatar cache
    // R7.5: avatar_dataurl is the base64 inline form. The renderer
    // never goes through `<img src="/api/...">` because Electron's
    // file:// protocol would resolve that to file:///api/... (a 404).
    this._personaCache = { name: "伊塔", english_name: "Ita", avatar_url: "", avatar_dataurl: "" };
    this._masterAvatar = "";
    // R7.5: user-side avatar + name. localStorage-only because these
    // are pure UI affordances and don't need to round-trip to Python.
    this._userDataurl = this._readLocalAvatar("user");
    this._userName = (this._readLocalKey("user", "name") || "").trim() || "你";
    // R7.5: cache the AI persona's dataURL in localStorage too so we
    // don't have to wait for the backend round-trip on every startup.
    const cached = this._readLocalAvatar("persona");
    if (cached) this._personaCache.avatar_dataurl = cached;

    this._bindEvents();
    this._listenIPC();
    this._listenSSE();
    this._listenOpenTab();
    this._startPoll();
    this.loadHistory();
    this.restorePendingRequests();
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
    // R7.5 fix: if the event detail ships an avatar_dataurl, push it
    // straight into the cache + localStorage so the refresh is
    // synchronous, not gated on a /api/persona round-trip.
    window.addEventListener("aerie:persona-updated", (ev) => {
      try {
        const detail = (ev && ev.detail) || {};
        if (detail.avatar_dataurl) {
          this._personaCache.avatar_dataurl = detail.avatar_dataurl;
          this._writeLocalAvatar("persona", detail.avatar_dataurl);
          this._refreshAvatarsInDom();
        } else {
          this._loadPersona();
        }
      } catch (_) {}
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
    const briefBtn = document.getElementById("chat-brief-btn");
    if (briefBtn) {
      briefBtn.addEventListener("click", () => {
        if (window.bus && typeof window.bus.emit === "function") {
          window.bus.emit("brief:open");
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
      if (
        !msg ||
        (
          !msg.request_id &&
          !msg.event_id &&
          msg.type !== "recall" &&
          !["user", "assistant"].includes(msg.role)
        )
      ) {
        return;
      }
      this._ingestChatSignal(msg, "ipc");
    });
  }

  _listenSSE() {
    if (
      !window.aerie ||
      !window.aerie.sse ||
      typeof window.aerie.sse.subscribe !== "function"
    ) {
      return;
    }
    try {
      this._sseUnsubscribe = window.aerie.sse.subscribe((signal) => {
        this._ingestChatSignal(signal, "sse");
      });
    } catch (_) {
      this._sseUnsubscribe = null;
    }
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
          // R7.5: prefer the inline dataURL form. The backend always
          // returns one when an avatar file exists, and using it
          // bypasses the file:// + relative-path resolution issue.
          avatar_dataurl: r.data.avatar_dataurl || this._personaCache.avatar_dataurl,
        };
        // Persist into localStorage so a fresh launch has the image
        // immediately, before the first /api/persona round-trip.
        if (this._personaCache.avatar_dataurl) {
          this._writeLocalAvatar("persona", this._personaCache.avatar_dataurl);
        }
        // R6.6: refresh avatar src on every rendered assistant message
        // so a freshly uploaded avatar shows up without a window reload.
        this._refreshAvatarsInDom();
      }
    } catch (_) { /* fail-soft: keep defaults */ }
  }

  // R6.6: re-render every assistant / user avatar in the current
  // message list. R7.5: now actually implemented (the previous version
  // referenced this method but never defined it, so it threw and got
  // swallowed by the try-catch — historical messages kept showing the
  // stale avatar forever). R7.5 fix: placeholder uses first char of
  // display name so it matches _render's logic.
  _refreshAvatarsInDom() {
    if (!this._el || !this._el.messages) return;
    const ai = this._personaCache.avatar_dataurl || this._personaCache.avatar_url || "";
    const user = this._userDataurl || this._masterAvatar || "";
    const aiName = this._personaCache.name || "伊塔";
    const userName = this._userName || "你";
    const aiPlaceholder = (aiName || "伊").slice(0, 1);
    const userPlaceholder = (userName || "你").slice(0, 1);
    const aiImg = ai
      ? `<img class="chat-msg__avatar" src="${this._escapeHtml(ai)}" alt="" onerror="this.parentNode.innerHTML='<span class=&quot;chat-msg__avatar chat-msg__avatar--placeholder&quot; aria-hidden=&quot;true&quot;>${this._escapeHtml(aiPlaceholder)}</span>'">`
      : `<span class="chat-msg__avatar chat-msg__avatar--placeholder" aria-hidden="true">${this._escapeHtml(aiPlaceholder)}</span>`;
    const userImg = user
      ? `<img class="chat-msg__avatar" src="${this._escapeHtml(user)}" alt="" onerror="this.parentNode.innerHTML='<span class=&quot;chat-msg__avatar chat-msg__avatar--placeholder&quot; aria-hidden=&quot;true&quot;>${this._escapeHtml(userPlaceholder)}</span>'">`
      : `<span class="chat-msg__avatar chat-msg__avatar--placeholder" aria-hidden="true">${this._escapeHtml(userPlaceholder)}</span>`;
    const imgs = this._el.messages.querySelectorAll(".chat-msg__avatar");
    imgs.forEach((img) => {
      const wrap = img.closest(".chat-msg");
      if (!wrap) return;
      const role = wrap.classList.contains("chat-msg--assistant") ? "ai"
        : wrap.classList.contains("chat-msg--user") ? "user"
        : null;
      if (role === "ai") {
        img.outerHTML = aiImg;
      } else if (role === "user") {
        img.outerHTML = userImg;
      }
    });
    // R7.5 fix: also refresh the name label so user-renamed display
    // names show up on existing messages without a window reload.
    const nameEls = this._el.messages.querySelectorAll(".chat-msg__name");
    nameEls.forEach((el) => {
      const wrap = el.closest(".chat-msg");
      if (!wrap) return;
      if (wrap.classList.contains("chat-msg--assistant")) {
        el.textContent = aiName;
      } else if (wrap.classList.contains("chat-msg--user")) {
        el.textContent = userName;
      }
    });
  }

  // ── R7.5: localStorage helpers for user + persona avatar/name ──
  // Avatar is stored as a dataURL so we never have to round-trip
  // through a /api/... URL that Electron's file:// can't resolve.
  _LS_KEY(side, field) { return "aerie." + side + "." + field; }
  _readLocalKey(side, field) {
    try { return window.localStorage.getItem(this._LS_KEY(side, field)) || ""; }
    catch (_) { return ""; }
  }
  _writeLocalKey(side, field, value) {
    try { window.localStorage.setItem(this._LS_KEY(side, field), String(value)); }
    catch (_) { /* quota / private mode — non-fatal */ }
  }
  _readLocalAvatar(side) {
    return this._readLocalKey(side, "avatar");
  }
  _writeLocalAvatar(side, dataurl) {
    this._writeLocalKey(side, "avatar", dataurl);
  }
  // R7.5: allow settings.js (or anywhere) to push a new user avatar
  // straight into the chat cache + DOM without a server round-trip.
  setUserAvatar(dataurl) {
    this._userDataurl = dataurl || "";
    this._writeLocalAvatar("user", this._userDataurl);
    this._refreshAvatarsInDom();
  }
  setUserName(name) {
    const trimmed = (name || "").trim() || "你";
    this._userName = trimmed;
    this._writeLocalKey("user", "name", trimmed);
    this._refreshAvatarsInDom();
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
            this._ingestChatSignal(item, "poll");
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

  _prefersReducedMotion() {
    try {
      return Boolean(
        window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      );
    } catch (_) {
      return false;
    }
  }

  _clientIdForRequest(requestId) {
    if (!requestId) return "";
    for (const [clientId, mappedRequestId] of this._clientToRequest.entries()) {
      if (mappedRequestId === requestId) return clientId;
    }
    return "";
  }

  _findBubbleForRequest(requestId, role) {
    if (!requestId || !this._el.messages) return null;
    const classes = role === "assistant"
      ? [".chat-msg--assistant", ".chat-msg--typing"]
      : [".chat-msg--user"];
    for (const selector of classes) {
      const candidates = this._el.messages.querySelectorAll(selector) || [];
      for (const candidate of candidates) {
        if (
          candidate &&
          typeof candidate.getAttribute === "function" &&
          candidate.getAttribute("data-request-id") === requestId
        ) {
          return candidate;
        }
      }
    }

    const clientId = this._clientIdForRequest(requestId);
    if (clientId) {
      const bubble = this._el.messages.querySelector(`[data-id="${clientId}"]`);
      if (bubble) return bubble;
    }

    if (role === "assistant") {
      const typingBubbles = this._el.messages.querySelectorAll(".chat-msg--typing") || [];
      if (typingBubbles.length === 1) {
        return typingBubbles[0];
      }
    }
    return null;
  }

  _requestTypingLabel(status) {
    if (status === "queued") return "排队中";
    if (status === "cancelling") return "取消中";
    return "正在输入";
  }

  _buildTypingIndicator(status) {
    const label = this._requestTypingLabel(status);
    const reduced = this._reducedMotion || status !== "running";
    if (reduced) {
      return `<span class="chat-typing-indicator__label">${this._escapeHtml(label)}…</span>`;
    }
    return `
      <span class="chat-typing-indicator" aria-label="${this._escapeHtml(label)}">
        <span class="chat-typing-indicator__dot"></span>
        <span class="chat-typing-indicator__dot"></span>
        <span class="chat-typing-indicator__dot"></span>
      </span>
    `;
  }

  _buildMessageHtml(msg, { typing = false } = {}) {
    const isAssistant = msg.role === "assistant";
    const displayName = isAssistant
      ? (this._personaCache && this._personaCache.name) || "伊塔"
      : this._userName || "你";
    const aiAvatar = (this._personaCache && this._personaCache.avatar_dataurl)
      || (this._personaCache && this._personaCache.avatar_url)
      || "";
    const userAvatar = this._userDataurl || this._masterAvatar || "";
    const avatarUrl = isAssistant ? aiAvatar : userAvatar;
    const placeholderText = isAssistant ? "伊" : (this._userName || "你").slice(0, 1);
    const avatarContent = avatarUrl
      ? `<img class="chat-msg__avatar" src="${this._escapeHtml(avatarUrl)}" alt="" onerror="this.parentNode.innerHTML='<span class=&quot;chat-msg__avatar chat-msg__avatar--placeholder&quot; aria-hidden=&quot;true&quot;>${this._escapeHtml(placeholderText)}</span>'">`
      : `<span class="chat-msg__avatar chat-msg__avatar--placeholder" aria-hidden="true">${this._escapeHtml(placeholderText)}</span>`;
    let html = "";
    html += `<div class="chat-msg__avatar-wrap">${avatarContent}</div>`;
    html += `<div class="chat-msg__body">`;
    html += `<div class="chat-msg__name">${this._escapeHtml(displayName)}</div>`;
    const tsText = this._formatTime(msg.ts);
    if (tsText) {
      html += `<span class="chat-msg__meta-time">${tsText}</span>`;
    }
    if (!typing && msg.reply_to_id && msg.reply_to_content) {
      const role = msg.reply_to_role === "user" ? "你" : "伊塔";
      html += `<div class="chat-quote-overlay" data-reply-to="${msg.reply_to_id}">
        <span class="chat-quote-overlay__bar"></span>
        <div class="chat-quote-overlay__text">
          <span class="chat-quote-overlay__author">引用 ${role}</span>
          <span class="chat-quote-overlay__preview">${this._escapeHtml((msg.reply_to_content || "").slice(0, 60))}</span>
        </div>
      </div>`;
    }
    if (!typing && msg.attachments && msg.attachments.length > 0) {
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
    if (typing) {
      const typingStatus = msg.request_status || msg.status || "running";
      html += `<div class="chat-bubble chat-bubble--typing" data-chat-typing="true" data-request-status="${this._escapeHtml(typingStatus)}">
        ${this._buildTypingIndicator(typingStatus)}
      </div>`;
    } else {
      html += this._parseMessage(msg.content || "");
    }
    html += `</div>`;
    if (msg.id && !String(msg.id).startsWith("temp_") && !typing) {
      html += `<div class="chat-msg-actions"><button class="chat-msg-actions__btn" data-msg-actions="${msg.id}">⋮</button></div>`;
    }
    return html;
  }

  _syncRequestTypingBubble(state) {
    if (!state || !state.request_id || !this._el.messages) return null;
    const requestId = String(state.request_id);
    const bubbleId = "typing_" + requestId;
    const bubble = this._el.messages.querySelector(`[data-id="${bubbleId}"]`);
    const active = ["running", "cancelling"].includes(state.status);
    if (!active) {
      if (bubble && bubble.parentNode) {
        bubble.remove();
      }
      return null;
    }

    const typingMsg = {
      id: bubbleId,
      role: "assistant",
      request_id: requestId,
      request_status: state.status,
      status: state.status,
      content: "",
      source: state.channel || "local",
    };
    if (bubble) {
      bubble.className = "chat-msg chat-msg--assistant chat-msg--typing";
      if (this._reducedMotion) {
        bubble.className += " chat-msg--typing--reduced";
      }
      bubble.setAttribute("data-id", bubbleId);
      bubble.setAttribute("data-msg-id", bubbleId);
      bubble.setAttribute("data-request-id", requestId);
      bubble.setAttribute("data-request-status", state.status || "");
      bubble.setAttribute("data-chat-typing", "true");
      bubble.innerHTML = this._buildMessageHtml(typingMsg, { typing: true });
      return bubble;
    }

    this._render({
      ...typingMsg,
      typing: true,
    });
    return this._el.messages.querySelector(`[data-id="${bubbleId}"]`);
  }

  _promoteBubbleIdentity(el, msg) {
    if (!el || !msg) return;
    el.setAttribute("data-id", msg.id);
    el.setAttribute("data-msg-id", msg.id);
    if (msg.request_id) {
      el.setAttribute("data-request-id", msg.request_id);
    }
  }

  _updateUserBubble(el, msg) {
    this._promoteBubbleIdentity(el, msg);
    if (msg.request_id) {
      el.setAttribute("data-request-id", msg.request_id);
    }
    el.setAttribute("data-request-status", "");
    if (msg.id && Number.isFinite(Number(msg.id))) {
      const numericId = Number(msg.id);
      if (numericId > this._sinceId) this._sinceId = numericId;
    }
    if (msg.id) {
      this._seenIds.add(msg.id);
    }
  }

  _updateTypingBubble(el, msg) {
    if (!el) return;
    el.className = "chat-msg chat-msg--assistant";
    el.setAttribute("data-id", msg.id);
    el.setAttribute("data-msg-id", msg.id);
    if (msg.request_id) {
      el.setAttribute("data-request-id", msg.request_id);
    }
    el.setAttribute("data-request-status", "");
    el.setAttribute("data-chat-typing", "false");
    el.innerHTML = this._buildMessageHtml(msg, { typing: false });
    if (msg.id) {
      this._seenIds.add(msg.id);
      const numericId = Number(msg.id);
      if (Number.isFinite(numericId) && numericId > this._sinceId) {
        this._sinceId = numericId;
      }
    }
  }

  _requestTypingBubbleForRequest(requestId) {
    if (!requestId || !this._el.messages) return null;
    return this._el.messages.querySelector(`[data-id="typing_${requestId}"]`);
  }

  _newClientId() {
    this._clientCounter += 1;
    return "client_" + Date.now() + "_" + this._clientCounter;
  }

  _normalizeChatSignal(signal) {
    if (!signal) return null;
    if (typeof signal === "string") {
      try {
        return JSON.parse(signal);
      } catch (_) {
        return null;
      }
    }
    if (signal && typeof signal.data === "string") {
      try {
        return JSON.parse(signal.data);
      } catch (_) {
        return null;
      }
    }
    if (typeof signal === "object") return signal;
    return null;
  }

  _ingestChatSignal(signal, transport = "unknown") {
    const normalized = this._normalizeChatSignal(signal);
    if (!normalized) return;

    const eventId = normalized.event_id;
    if (eventId) {
      if (this._seenEventIds.has(eventId)) return;
      this._seenEventIds.add(eventId);
    }

    const sequence = Number(normalized.sequence);
    if (
      normalized.request_id &&
      Number.isInteger(sequence) &&
      sequence >= 0
    ) {
      this._ingestSequencedSignal(normalized, transport, sequence);
      return;
    }
    this._applyChatSignal(normalized, transport);
  }

  _ingestSequencedSignal(signal, transport, sequence) {
    const requestId = signal.request_id;
    let tracker = this._requestSequences.get(requestId);
    if (!tracker) {
      tracker = {
        next: sequence === 0 ? 0 : 1,
        pending: new Map(),
      };
      this._requestSequences.set(requestId, tracker);
    }
    if (sequence < tracker.next) return;
    tracker.pending.set(sequence, { signal, transport });
    while (tracker.pending.has(tracker.next)) {
      const current = tracker.pending.get(tracker.next);
      tracker.pending.delete(tracker.next);
      this._applyChatSignal(current.signal, current.transport);
      tracker.next += 1;
    }
  }

  _applyChatSignal(signal, transport = "unknown") {
    if (signal.type === "recall" || signal.is_recalled) {
      if (signal.id) this._markRecalled(signal.id);
      return;
    }

    if (signal.request_id || this._inferRequestStatus(signal)) {
      this._upsertRequestState(signal);
    }

    if (signal.request_id && signal.role === "user") {
      const existingUser = this._findBubbleForRequest(signal.request_id, "user");
      if (existingUser) {
        this._updateUserBubble(existingUser, signal);
        return;
      }
    }

    if (signal.request_id && signal.role === "assistant") {
      const typingBubble = this._requestTypingBubbleForRequest(signal.request_id);
      if (typingBubble) {
        this._updateTypingBubble(typingBubble, signal);
        const requestState = this._requests.get(signal.request_id);
        if (
          requestState &&
          ["running", "cancelling"].includes(requestState.status)
        ) {
          this._syncRequestTypingBubble(requestState);
        }
        return;
      }
    }

    if (!signal || !["user", "assistant"].includes(signal.role)) {
      return;
    }
    if (signal.id && this._seenIds.has(signal.id)) return;
    if (signal.id) {
      this._seenIds.add(signal.id);
      const numericId = Number(signal.id);
      if (Number.isFinite(numericId) && numericId > this._sinceId) {
        this._sinceId = numericId;
      }
    }
    signal.transport = signal.transport || transport;
    this._render(signal);
  }

  _inferRequestStatus(signal) {
    if (signal.status) return signal.status;
    const type = signal.type || "";
    if (type === "chat_request_running") return "running";
    if (type === "chat_request_completed") return "completed";
    if (type === "chat_request_cancelled") return "cancelled";
    if (type === "chat_request_failed") return "failed";
    if (type === "chat_request_cancelling") return "cancelling";
    if (type === "chat_request_queued") return "queued";
    return "";
  }

  _isTerminalRequestStatus(status) {
    return ["completed", "failed", "cancelled"].includes(status);
  }

  _readPendingRequestIds() {
    try {
      const raw = window.localStorage.getItem("aerie.chat.pending_requests");
      const parsed = JSON.parse(raw || "[]");
      return Array.isArray(parsed) ? parsed.filter(Boolean).map(String) : [];
    } catch (_) {
      return [];
    }
  }

  _writePendingRequestIds(ids) {
    try {
      window.localStorage.setItem(
        "aerie.chat.pending_requests",
        JSON.stringify(Array.from(new Set(ids))),
      );
    } catch (_) {}
  }

  _persistPendingRequestState() {
    const ids = [];
    for (const [requestId, state] of this._requests.entries()) {
      if (!this._isTerminalRequestStatus(state.status)) {
        ids.push(requestId);
      }
    }
    this._writePendingRequestIds(ids);
  }

  _upsertRequestState(view) {
    const requestId = view && view.request_id;
    if (!requestId) return null;
    const previous = this._requests.get(requestId) || {
      request_id: requestId,
      statusHistory: [],
    };
    const status = this._inferRequestStatus(view) || previous.status || "queued";
    const next = {
      ...previous,
      ...view,
      request_id: requestId,
      status,
      can_cancel: view.can_cancel ?? ["queued", "running"].includes(status),
      can_retry: view.can_retry ?? ["failed", "cancelled"].includes(status),
      statusHistory: previous.statusHistory ? previous.statusHistory.slice() : [],
    };
    if (next.statusHistory[next.statusHistory.length - 1] !== status) {
      next.statusHistory.push(status);
    }
    this._requests.set(requestId, next);
    if (next.client_id) {
      this._clientToRequest.set(next.client_id, requestId);
    }
    this._renderRequestStatus(next);
    this._syncRequestTypingBubble(next);
    this._persistPendingRequestState();
    return next;
  }

  _bindClientRequest(clientId, view) {
    if (!view || !view.request_id) return null;
    this._clientToRequest.set(clientId, view.request_id);
    return this._upsertRequestState({ ...view, client_id: clientId });
  }

  _requestStatusLabel(status) {
    return {
      queued: "排队中",
      running: "生成中",
      cancelling: "取消中",
      failed: "失败",
      cancelled: "已取消",
      completed: "已完成",
    }[status] || status || "未知";
  }

  _renderRequestStatus(state) {
    if (!this._el.messages || !state || !state.request_id) return;
    const requestId = state.request_id;
    const clientId = state.client_id || "";
    const selector = `[data-request-id="${requestId}"]`;
    let messageEl = this._el.messages.querySelector(selector);
    if (!messageEl && clientId) {
      messageEl = this._el.messages.querySelector(`[data-id="${clientId}"]`);
    }
    if (!messageEl) return;
    messageEl.setAttribute("data-request-id", requestId);
    messageEl.setAttribute("data-request-status", state.status || "");
    let statusEl = messageEl.querySelector(".chat-request-status");
    if (!statusEl) {
      statusEl = document.createElement("div");
      statusEl.className = "chat-request-status";
      const body = messageEl.querySelector(".chat-msg__body") || messageEl;
      body.appendChild(statusEl);
    }
    const cancelButton = state.can_cancel
      ? `<button class="chat-request-status__btn chat-request-cancel" data-request-cancel="${requestId}">取消</button>`
      : "";
    const retryButton = state.can_retry
      ? `<button class="chat-request-status__btn chat-request-retry" data-request-retry="${requestId}">重试</button>`
      : "";
    statusEl.setAttribute("data-status", state.status || "");
    statusEl.innerHTML = `
      <span class="chat-request-status__label">${this._escapeHtml(this._requestStatusLabel(state.status))}</span>
      ${cancelButton}
      ${retryButton}
    `;
    const cancel = statusEl.querySelector(".chat-request-cancel");
    if (cancel) {
      cancel.addEventListener("click", () => this.cancelRequest(requestId));
    }
    const retry = statusEl.querySelector(".chat-request-retry");
    if (retry) {
      retry.addEventListener("click", () => this.retryRequest(requestId));
    }
  }

  async cancelRequest(requestId) {
    const state = this._requests.get(requestId);
    if (!state || !["queued", "running"].includes(state.status)) return null;
    this._upsertRequestState({ ...state, status: "cancelling", can_cancel: false });
    try {
      const resp = await this._request({
        method: "POST",
        path: "/api/chat/requests/" + encodeURIComponent(requestId) + "/cancel",
      });
      if (resp && resp.data) {
        return this._upsertRequestState(resp.data);
      }
    } catch (err) {
      this._upsertRequestState({
        ...state,
        status: "failed",
        error_code: "cancel_request_failed",
        can_retry: true,
      });
    }
    return null;
  }

  async retryRequest(requestId) {
    const state = this._requests.get(requestId);
    if (!state || !["failed", "cancelled"].includes(state.status)) return null;
    try {
      const resp = await this._request({
        method: "POST",
        path: "/api/chat/requests/" + encodeURIComponent(requestId) + "/retry",
      });
      if (resp && resp.data) {
        return this._upsertRequestState(resp.data);
      }
    } catch (_) {}
    return null;
  }

  async restorePendingRequests() {
    const ids = new Set(this._readPendingRequestIds());
    for (const [requestId, state] of this._requests.entries()) {
      if (!this._isTerminalRequestStatus(state.status)) {
        ids.add(requestId);
      }
    }
    for (const requestId of ids) {
      try {
        const resp = await this._request({
          method: "GET",
          path: "/api/chat/requests/" + encodeURIComponent(requestId),
        });
        if (resp && resp.data && !resp.data.error) {
          this._upsertRequestState(resp.data);
        }
      } catch (_) {}
    }
    this._persistPendingRequestState();
  }

  _handleSSEDisconnect() {
    // SSE remains best-effort in Phase 04.  A disconnect must not turn
    // a real backend request into failed UI state; status polling is the
    // recovery source of truth.
  }

  async send() {
    const text = this._el.input.value.trim();
    if (!text && this._pendingAttachments.length === 0) return;
    this._el.input.value = "";

    const replyToId = this._quotedMsg ? this._quotedMsg.id : 0;
    const attachments = this._pendingAttachments.slice();
    const clientId = this._newClientId();

    // Optimistic render
    this._render({
      id: clientId,
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
      if (resp.status === 202 || (resp.data && resp.data.request_id)) {
        this._bindClientRequest(clientId, resp.data);
        return;
      }
      if (resp.data && resp.data.user_msg_id) {
        const realId = resp.data.user_msg_id;
        const tempEl = this._el.messages.querySelector(`[data-id="${clientId}"]`);
        if (tempEl) {
          tempEl.setAttribute("data-id", realId);
          tempEl.setAttribute("data-msg-id", realId);
        }
        this._seenIds.add(realId);
        if (realId > this._sinceId) this._sinceId = realId;
      }
      if (resp.data && resp.data.reply) {
        // Server reply already pushed via IPC; this is a fallback
      }
    } catch (err) {
      this._render({ id: clientId + "_err", role: "assistant", content: "发送失败: " + err.message });
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
    if (msg.typing) {
      div.className += " chat-msg--typing";
      if (this._reducedMotion) {
        div.className += " chat-msg--typing--reduced";
      }
    }
    div.setAttribute("data-id", msg.id);
    if (msg.id) div.setAttribute("data-msg-id", msg.id);
    if (msg.id) div.setAttribute("data-temp-text", msg.content);
    if (msg.id) div.setAttribute("data-request-id", msg.request_id || "");
    if (msg.id) div.setAttribute("data-request-status", msg.request_status || msg.status || "");
    if (msg.typing) div.setAttribute("data-chat-typing", "true");
    div.innerHTML = this._buildMessageHtml(msg, { typing: Boolean(msg.typing) });
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

    // R7.4: re-scan any new <pre><code> blocks so highlight.js picks
    // them up. highlight.js only auto-highlights on initial page load,
    // so we re-trigger for every newly inserted message.
    if (window.hljs && typeof window.hljs.highlightElement === "function") {
      div.querySelectorAll("pre code").forEach((el) => {
        try { window.hljs.highlightElement(el); } catch (_) {}
      });
    }

    this._el.messages.scrollTop = this._el.messages.scrollHeight;
  }

  /* R7.4: split a message into text / action / thought segments and
     render each in its own bubble. Text segments get full markdown
     treatment via marked + DOMPurify + highlight.js. Action/thought
     segments are plain text in a smaller, centered glass row.
     The three types appear in the order they were written, so a
     single message can interleave dialogue and narration naturally. */
  _parseMessage(content) {
    if (!content) return "";
    const tagRe = /<(action|thought)>([\s\S]*?)<\/\1>/g;
    const parts = [];
    let last = 0;
    let m;
    while ((m = tagRe.exec(content)) !== null) {
      if (m.index > last) {
        parts.push({ type: "text", body: content.slice(last, m.index) });
      }
      parts.push({
        type: m[1] === "action" ? "action" : "thought",
        body: (m[2] || "").trim(),
      });
      last = m.index + m[0].length;
    }
    if (last < content.length) {
      parts.push({ type: "text", body: content.slice(last) });
    }
    // If no tags were found at all, fall back to the legacy single
    // bubble so a totally plain message still works.
    if (parts.length === 0) {
      return `<div class="chat-bubble chat-bubble--text">${this._renderMarkdown("")}</div>`;
    }
    return parts
      .map((p) => {
        if (p.type === "text") {
          return `<div class="chat-bubble chat-bubble--text">${this._renderMarkdown(p.body)}</div>`;
        }
        const esc = this._escapeHtml(p.body);
        return `<div class="chat-bubble chat-bubble--${p.type}">${esc}</div>`;
      })
      .join("");
  }

  /* R7.4: run a text segment through marked + DOMPurify + highlight.js.
     Falls back to a safe escape if any of those globals is missing
     (e.g. when the file is loaded in a context that didn't get the
     vendor scripts). */
  _renderMarkdown(text) {
    const body = text || "";
    if (
      !window.marked ||
      !window.DOMPurify ||
      !window.hljs
    ) {
      return this._escapeHtml(body);
    }
    try {
      // marked v12: marked.parse returns a string; with langPrefix we
      // match the class names highlight.js uses (hljs language-xxx).
      const html = window.marked.parse(body, {
        gfm: true,
        breaks: true,
        langPrefix: "hljs language-",
      });
      const safe = window.DOMPurify.sanitize(html, {
        ADD_ATTR: ["class", "target", "rel"],
        // Allow <pre>, <code>, <span>, <div>, <a>, <h1-h6>, <ul>, <ol>, <li>, <p>, <strong>, <em>, <blockquote>
        // (these are all in DOMPurify's default allow-list, so no
        // ADD_TAGS override is needed).
      });
      return safe;
    } catch (e) {
      console.warn("chat._renderMarkdown failed", e);
      return this._escapeHtml(body);
    }
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
