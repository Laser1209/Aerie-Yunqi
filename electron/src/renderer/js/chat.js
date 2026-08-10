"use strict";
/* Chat manager: Phase 4 — recall + quote + attachment support */

function attachmentPublicUrl(value) {
  const raw = String(value || "").trim();
  if (!raw) return "";
  if (/^https?:\/\//i.test(raw) || raw.startsWith("data:")) return raw;
  const normalized = raw.replace(/^\/+/, "");
  if (normalized.startsWith("uploads/")) return "/" + normalized;
  return "/uploads/" + normalized;
}

class ChatManager {
  constructor(opts = {}) {
    this._el = {
      messages: document.getElementById("chat-messages"),
      input: document.getElementById("chat-input"),
      sendBtn: document.getElementById("chat-send-btn"),
    };
    this._requests = new Map();          // request_id -> RequestViewState
    this._clientToRequest = new Map();   // client_id -> request_id
    this._clientCounter = 0;
    this._reducedMotion = this._prefersReducedMotion();
    this._masterQQ = opts.masterQQ || null;
    this._identityReady = Boolean(this._masterQQ);
    this._identityBootstrapPromise = null;
    this._chatStarted = false;
    this._sinceId = 0;
    this._quotedMsg = null;            // Phase 4: currently quoted message
    this._pendingAttachments = [];     // Phase 5: file attachments awaiting send
    this._history = {
      olderCursor: null,
      newerCursor: null,
      hasOlder: false,
      hasNewer: false,
      loading: false,
      autoLoadCooldown: 0, // 顶部自动加载的冷却时间戳, 防止停在顶部时连发多批
    };
    // 同时保留在 DOM 里的消息气泡上限。历史很多时靠向上翻页按批加载,
    // 超出即裁剪最旧气泡, 避免开机渲染/滚动时 DOM 过大导致卡顿。
    this._maxDomMessages = 200;
    // 单一数据源: 判重/排序/请求状态/稳定元素 id 映射全由 store 接管,
    // DOM 层只认 store 产出的渲染意图(Intent)。
    this._store = window.createChatStore({ maxMessages: this._maxDomMessages });

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
    this._bindHistoryScroll();
    this._listenIPC();
    this._listenSSE();
    this._listenOpenTab();
    if (this._identityReady) {
      this._startChatForIdentity();
    } else {
      this._bootstrapRuntimeIdentity();
    }
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

  async _bootstrapRuntimeIdentity() {
    if (this._identityBootstrapPromise) return this._identityBootstrapPromise;
    this._identityBootstrapPromise = (async () => {
      try {
        const response = await this._request({ method: "GET", path: "/api/runtime/snapshot" });
        const data = (response && response.data) || {};
        const candidate = data.primaryUserId
          ?? data.primary_user_id
          ?? (data.primaryIdentity && (
            data.primaryIdentity.primaryUserId
            ?? data.primaryIdentity.userId
            ?? data.primaryIdentity.user_id
          ));
        const normalized = Number(candidate);
        if (!Number.isSafeInteger(normalized) || normalized <= 0) {
          throw new Error("主身份未配置");
        }
        this._masterQQ = normalized;
        this._identityReady = true;
        const identityError = this._el.messages
          && this._el.messages.querySelector("[data-identity-error]");
        if (identityError) identityError.remove();
        this._syncSendAvailability();
        this._startChatForIdentity();
        this._loadMasterAvatar();
        return true;
      } catch (_) {
        this._identityReady = false;
        this._syncSendAvailability();
        if (this._el.messages && !this._el.messages.querySelector("[data-identity-error]")) {
          const status = document.createElement("div");
          status.className = "chat-empty";
          status.setAttribute("data-identity-error", "true");
          status.textContent = "主身份未配置，聊天暂不可用";
          this._el.messages.appendChild(status);
        }
        return false;
      } finally {
        this._identityBootstrapPromise = null;
      }
    })();
    return this._identityBootstrapPromise;
  }

  _startChatForIdentity() {
    if (this._chatStarted || !this._identityReady) return;
    this._chatStarted = true;
    this._startPoll();
    this.loadHistory();
  }

  _syncSendAvailability() {
    if (!this._el.sendBtn) return;
    const attachmentsReady = this._pendingAttachments.every(
      (attachment) => attachment.state === "ready",
    );
    this._el.sendBtn.disabled = !this._identityReady || !attachmentsReady;
    this._el.sendBtn.title = !this._identityReady
      ? "主身份未配置"
      : (!attachmentsReady ? "请等待附件解析完成" : "");
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
      if (!e.target.closest(".chat-action-menu")) {
        this._closeAllActionMenus();
      }
    });
  }

  _listenIPC() {
    if (!window.aerie) return;
    if (
      window.aerie.electron
      && typeof window.aerie.electron.onBackendReady === "function"
    ) {
      window.aerie.electron.onBackendReady(() => {
        if (!this._identityReady) this._bootstrapRuntimeIdentity();
      });
    }
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

  _recallNoticeHtml() {
    const name = (this._personaCache && this._personaCache.name) || "伊塔";
    return `<div class="chat-msg__recall-notice">${this._escapeHtml(name)} 撤回了一条消息</div>`;
  }

  _markRecalled(msgId) {
    const el = this._el.messages.querySelector(`[data-id="${msgId}"]`);
    if (!el) return;
    el.classList.add("chat-msg--recalled");
    el.innerHTML = this._recallNoticeHtml();
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
    return this._loadHistoryPage("initial");
  }

  async _loadHistoryPage(direction) {
    if (!this._identityReady || this._history.loading) return;
    const cursor = direction === "older"
      ? this._history.olderCursor
      : (direction === "newer" ? this._history.newerCursor : null);
    if (direction !== "initial" && !cursor) return;
    this._history.loading = true;
    this._renderHistoryControls();
    try {
      let path = "/api/chat/history/page?user_id=" + encodeURIComponent(this._masterQQ)
        + "&limit=50";
      if (direction !== "initial") {
        path += "&direction=" + direction + "&cursor=" + encodeURIComponent(cursor);
      }
      const resp = await this._request({ method: "GET", path });
      const page = (resp && resp.data) || {};
      if (!Array.isArray(page.items)) throw new Error("invalid history page");
      const previousHeight = this._el.messages ? this._el.messages.scrollHeight : 0;
      const previousTop = this._el.messages ? this._el.messages.scrollTop : 0;
      const firstMessage = this._el.messages
        ? this._el.messages.querySelector(".chat-msg")
        : null;
      const empty = this._el.messages && this._el.messages.querySelector(".chat-empty");
      if (empty) empty.remove();
      for (const item of page.items) {
        const before = direction === "older" ? firstMessage : null;
        if (item.is_recalled) {
          this._reconcileRecalled(item.id, before);
        } else {
          for (const intent of this._store.ingestSignal(item, "history")) {
            this._applyIntent(intent, { before, autoScroll: false });
          }
        }
        const numericId = Number(item.id);
        if (Number.isFinite(numericId) && numericId > this._sinceId) this._sinceId = numericId;
      }
      this._history.olderCursor = page.olderCursor || null;
      this._history.newerCursor = page.newerCursor || null;
      this._history.hasOlder = Boolean(page.hasOlder);
      this._history.hasNewer = Boolean(page.hasNewer);
      this._trimMessageWindow(direction === "older" ? "newest" : "oldest");
      if (this._el.messages) {
        if (direction === "older") {
          this._el.messages.scrollTop = previousTop
            + (this._el.messages.scrollHeight - previousHeight);
        } else if (direction === "initial") {
          this._el.messages.scrollTop = this._el.messages.scrollHeight;
        }
      }
    } catch (_) {
      // History remains retryable through the controls.
    } finally {
      this._history.loading = false;
      // 顶部自动加载后冷却片刻, 防止用户停在顶部时连续拉取多批更早消息。
      if (direction === "older") {
        this._history.autoLoadCooldown = Date.now() + 800;
      }
      this._renderHistoryControls();
    }
  }

  _renderHistoryControls() {
    if (!this._el.messages) return;
    for (const existing of this._el.messages.querySelectorAll(".chat-history-control")) {
      existing.remove();
    }
    const makeButton = (kind, label) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "chat-history-control chat-history-control--" + kind;
      button.textContent = this._history.loading ? "加载中…" : label;
      button.disabled = this._history.loading;
      button.addEventListener("click", () => this._loadHistoryPage(kind));
      return button;
    };
    if (this._history.hasOlder) {
      const first = this._el.messages.querySelector(".chat-msg");
      this._el.messages.insertBefore(makeButton("older", "加载更早消息"), first);
    }
    if (this._history.hasNewer) {
      this._el.messages.appendChild(makeButton("newer", "加载更新消息"));
    }
  }

  // 滚动到列表顶部时自动按批拉取更早消息, 替代/兜底「加载更早」按钮。
  // 用 rAF 节流 + 冷却时间戳, 避免停在顶部时一口气加载多批。
  _bindHistoryScroll() {
    if (!this._el.messages) return;
    let pending = false;
    this._el.messages.addEventListener("scroll", () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        const el = this._el.messages;
        if (
          !el
          || this._history.loading
          || !this._history.hasOlder
          || Date.now() < this._history.autoLoadCooldown
        ) {
          return;
        }
        if (el.scrollTop < 60) {
          this._loadHistoryPage("older");
        }
      });
    });
  }

  _trimMessageWindow(removeSide) {
    if (!this._el.messages) return;
    const nodes = Array.from(this._el.messages.querySelectorAll(".chat-msg"));
    while (nodes.length > this._maxDomMessages) {
      const removed = removeSide === "newest" ? nodes.pop() : nodes.shift();
      if (removed) removed.remove();
    }
    const remaining = Array.from(this._el.messages.querySelectorAll(".chat-msg"));
    if (!remaining.length) return;
    const firstCursor = remaining[0].getAttribute("data-history-cursor");
    const lastCursor = remaining[remaining.length - 1].getAttribute("data-history-cursor");
    if (removeSide === "oldest" && firstCursor) {
      this._history.hasOlder = true;
      this._history.olderCursor = firstCursor;
    }
    if (removeSide === "newest" && lastCursor) {
      this._history.hasNewer = true;
      this._history.newerCursor = lastCursor;
    }
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
    const tsRaw = msg.ts ?? msg.created_at;
    const tsText = this._formatTime(tsRaw);
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
        html += this._buildAttachmentCard(att);
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
    if (tsText) {
      html += `<span class="chat-msg__meta-time">${tsText}</span>`;
    }
    html += `</div>`;
    return html;
  }

  _attachmentStateLabel(state) {
    return {
      queued: "等待处理",
      processing: "解析中",
      ready: "可读取",
      failed: "解析失败",
      quarantined: "已隔离",
      unsupported: "不支持",
    }[state] || "状态未知";
  }

  _formatAttachmentSize(value) {
    const bytes = Number(value || 0);
    if (!Number.isFinite(bytes) || bytes <= 0) return "";
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  _redactSensitive(text) {
    let s = String(text || "");
    s = s.replace(/[A-Za-z]:\\[^\s"'<>]*/g, "<path>");
    s = s.replace(/\/(?:home|Users|root|var|opt|tmp)\/[^\s"'<>]*/g, "<path>");
    s = s.replace(/(?:api[_-]?key|token|secret|bearer|ghp_)[^\s"'<>]*/gi, "<redacted>");
    return s;
  }

  _attachmentVisual(category, extension, name) {
    const ext = String(extension || name || "").split(".").pop().toLowerCase();
    const cat = String(category || "").toLowerCase();
    // Map category + extension to an SVG icon id + theme colors (soft pastel)
    if (cat === "image" || ["png", "jpg", "jpeg", "gif", "bmp", "webp", "svg", "heic"].includes(ext)) {
      return { icon: "icon-ui-image",  bg: "#fff0f3", fg: "#ff5b9c" };
    }
    if (cat === "video" || ["mp4", "mov", "avi", "mkv", "webm", "flv", "m4v"].includes(ext)) {
      return { icon: "icon-ui-video",  bg: "#eef3ff", fg: "#6e8efb" };
    }
    if (cat === "audio" || ["mp3", "wav", "flac", "aac", "ogg", "m4a"].includes(ext)) {
      return { icon: "icon-ui-mic",    bg: "#fff6ec", fg: "#ff9f43" };
    }
    if (ext === "pdf") {
      return { icon: "icon-ui-file-text", bg: "#ffeaea", fg: "#e74c3c" };
    }
    if (["doc", "docx", "txt", "md", "rtf", "odt"].includes(ext)) {
      return { icon: "icon-ui-file-text", bg: "#eaf1ff", fg: "#3b82f6" };
    }
    if (["xls", "xlsx", "csv", "numbers"].includes(ext)) {
      return { icon: "icon-ui-file-text", bg: "#e8f8ee", fg: "#10b981" };
    }
    if (["ppt", "pptx", "key"].includes(ext)) {
      return { icon: "icon-ui-file-text", bg: "#fff3e6", fg: "#f59e0b" };
    }
    if (cat === "code" || ["py", "js", "ts", "html", "css", "java", "go", "rs", "c", "cpp", "h", "json", "yaml", "yml", "sh", "sql", "vue", "jsx", "tsx"].includes(ext)) {
      return { icon: "icon-ui-file-text", bg: "#f3eeff", fg: "#8b5cf6" };
    }
    if (cat === "archive" || ["zip", "rar", "7z", "tar", "gz", "bz2", "xz", "apk"].includes(ext)) {
      return { icon: "icon-ui-package", bg: "#fef3e2", fg: "#d97706" };
    }
    if (cat === "folder") {
      return { icon: "icon-ui-folder", bg: "#eaf4ff", fg: "#2563eb" };
    }
    return { icon: "icon-ui-file-text", bg: "#f4f4f7", fg: "#6b7280" };
  }

  _buildAttachmentCard(att) {
    const id = att.attachmentId || att.id || "";
    const state = att.state || "ready";
    const category = att.category || att.type || "file";
    const name = this._escapeHtml(att.name || "文件");
    const stateLabel = this._escapeHtml(this._attachmentStateLabel(state));
    const sizeStr = this._formatAttachmentSize(att.size);
    const size = sizeStr ? this._escapeHtml(sizeStr) : "";
    const rawError = att.error && (att.error.message || att.error.code);
    const error = rawError ? this._escapeHtml(this._redactSensitive(rawError)) : "";
    const ext = String(att.extension || att.name || "").split(".").pop().toUpperCase();
    const visual = this._attachmentVisual(category, att.extension, att.name);
    const open = state === "ready" && id
      ? `<button type="button" data-attachment-open="${this._escapeHtml(id)}">打开</button>`
      : "";
    const retry = state === "failed" && id
      ? `<button type="button" data-attachment-retry="${this._escapeHtml(id)}">重试</button>`
      : "";
    let notice = "";
    if (state === "quarantined") {
      notice = '<span class="chat-attach-card__notice">文件未通过安全校验，已隔离</span>';
    } else if (state === "unsupported") {
      notice = '<span class="chat-attach-card__notice">此文件类型暂不支持</span>';
    }

    // ── IMAGE category: standalone large thumbnail bubble ──
    if (String(category).toLowerCase() === "image") {
      let src = att.thumbnailUrl || att.thumbnail_url || "";
      if (!src && att.downloadUrl) src = att.downloadUrl;
      if (!src && att.download_url) src = att.download_url;
      if (src) {
        // Rewrite to absolute backend URL for Electron's file:// protocol
        const absSrc = /^https?:|^data:/i.test(src)
          ? src
          : ("http://127.0.0.1:7890" + (src.startsWith("/") ? "" : "/") + src);
        return `<div class="chat-attach-card chat-attach-card--image"
                     data-type="image" data-attachment-id="${this._escapeHtml(id)}" data-state="${this._escapeHtml(state)}">
          <div class="chat-attach-card__image-wrap">
            <img src="${this._escapeHtml(absSrc)}" alt="${name}" loading="lazy">
          </div>
          <div class="chat-attach-card__image-meta">
            <span class="chat-attach-card__image-name">${name}</span>
            ${size ? `<span class="chat-attach-card__image-size">${size}</span>` : ""}
          </div>
          ${notice ? `<div class="chat-attach-card__notice-row">${notice}</div>` : ""}
          ${error ? `<div class="chat-attach-card__error-row" title="${error}">${error}</div>` : ""}
          ${(open || retry) ? `<div class="chat-attach-card__actions">${open}${retry}</div>` : ""}
        </div>`;
      }
    }

    // ── NON-IMAGE: horizontal file bubble card (large icon + name/size) ──
    return `<div class="chat-attach-card chat-attach-card--file"
                 data-type="${this._escapeHtml(category)}" data-attachment-id="${this._escapeHtml(id)}" data-state="${this._escapeHtml(state)}">
      <div class="chat-attach-card__icon" style="background:${visual.bg}; color:${visual.fg}">
        <svg class="icon icon--28" aria-hidden="true"><use href="#${visual.icon}"/></svg>
        ${ext ? `<span class="chat-attach-card__ext" style="color:${visual.fg}">${this._escapeHtml(ext.slice(0, 5))}</span>` : ""}
      </div>
      <div class="chat-attach-card__info">
        <span class="chat-attach-card__name">${name}</span>
        <span class="chat-attach-card__meta">
          ${size ? size + " · " : ""}${stateLabel}
        </span>
        ${notice ? `<span class="chat-attach-card__notice">${notice}</span>` : ""}
        ${error ? `<span class="chat-attach-card__error" title="${error}">${error}</span>` : ""}
      </div>
      ${(open || retry) ? `<div class="chat-attach-card__actions">${open}${retry}</div>` : ""}
    </div>`;
  }

  async _openAttachment(attachmentId) {
    if (
      window.aerie && window.aerie.attachments
      && typeof window.aerie.attachments.open === "function"
    ) {
      await window.aerie.attachments.open(attachmentId);
      return;
    }
    if (typeof window.open === "function") {
      window.open(
        "http://127.0.0.1:7890/api/attachments/"
          + encodeURIComponent(attachmentId) + "/download",
        "_blank",
      );
    }
  }

  async _retryAttachment(attachmentId) {
    if (this._uploader && typeof this._uploader.retry === "function") {
      const pending = this._pendingAttachments.some(
        (attachment) => String(attachment.attachmentId || attachment.id) === String(attachmentId),
      );
      if (pending) return this._uploader.retry(attachmentId);
    }
    try {
      await this._request({
        method: "POST",
        path: "/api/attachments/" + encodeURIComponent(attachmentId) + "/retry",
      });
    } catch (_) {}
  }

  _syncRequestTypingBubble(state) {
    if (!state || !state.request_id || !this._el.messages) return null;
    const requestId = String(state.request_id);
    // 与 store 的 requestIdToDomId 稳定键一致: req_<request_id>。
    // 输入中气泡与最终消息共用同一元素, 不做 id 偷换。
    const domId = "req_" + requestId;
    const bubble = this._el.messages.querySelector(`[data-id="${domId}"]`);
    const active = ["running", "cancelling"].includes(state.status);
    if (!active) {
      // 仅在仍是输入中气泡时移除; 已升级为真实内容则保留。
      if (bubble && bubble.getAttribute("data-chat-typing") === "true") {
        bubble.remove();
      }
      return null;
    }

    const typingMsg = {
      id: domId,
      role: "assistant",
      request_id: requestId,
      request_status: state.status,
      status: state.status,
      content: "",
      typing: true,
      source: state.channel || "local",
    };
    this._reconcileMessage(typingMsg, { autoScroll: true });
    return this._el.messages.querySelector(`[data-id="${domId}"]`);
  }

  _newClientId() {
    this._clientCounter += 1;
    return "client_" + Date.now() + "_" + this._clientCounter;
  }

  // 通过 request_id 反查乐观 client_id(请求状态链路)。
  _clientIdForRequest(requestId) {
    if (!requestId) return "";
    for (const [clientId, mappedRequestId] of this._clientToRequest.entries()) {
      if (mappedRequestId === requestId) return clientId;
    }
    return "";
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
    let normalized = this._normalizeChatSignal(signal);
    if (!normalized) return;
    // 用户乐观气泡升级: 真实回显带 request_id 但无 client_id, 用
    // _clientToRequest 把它关联回乐观气泡的稳定 domId, 让 store 原地
    // 更新而非新建重复元素(取代旧 _updateUserBubble 的 id 偷换)。
    if (normalized.role === "user" && normalized.request_id) {
      const clientId = this._clientIdForRequest(normalized.request_id);
      if (clientId && this._store.clientIdToDomId.has(clientId)) {
        normalized = {
          ...normalized,
          client_id: clientId,
          domId: this._store.clientIdToDomId.get(clientId),
        };
      }
    }
    // 判重(seenEventIds/seenRealIds)、分片排序(requestSequences)、
    // 稳定 domId 映射全由 store 接管; 这里只把意图翻译成 DOM 操作。
    for (const intent of this._store.ingestSignal(normalized, transport)) {
      this._applyIntent(intent);
    }
  }

  // 唯一的 DOM 应用入口: 把 store 产出的渲染意图应用到消息列表。
  // 每个逻辑消息只对应一个 [data-id] 元素, data-id 稳定永不改写。
  _applyIntent(intent, { before = null, autoScroll = true } = {}) {
    if (!intent) return;
    switch (intent.action) {
      case "upsert":
      case "typing":
        this._reconcileMessage(intent.msg, { before, autoScroll });
        break;
      case "recall":
        this._reconcileRecalled(intent.id);
        break;
      case "status":
        // 请求状态(取消/重试/徽标)走 chat.js 的请求状态owner, 便于
        // cancel/retry/restore 复用同一份状态。
        this._upsertRequestState(intent.state);
        break;
      case "remove":
        this._removeMessage(intent.id);
        break;
    }
  }

  // 创建或原地更新一个 .chat-msg 元素。同一 domId 永远命中同一元素。
  _reconcileMessage(msg, { before = null, autoScroll = true } = {}) {
    if (!this._el.messages) return;
    const empty = this._el.messages.querySelector(".chat-empty");
    if (empty) empty.remove();
    const domId = msg.id;
    let el = this._el.messages.querySelector(`[data-id="${domId}"]`);
    const create = !el;
    if (create) {
      el = document.createElement("div");
      if (before) this._el.messages.insertBefore(el, before);
      else this._el.messages.appendChild(el);
    }
    el.className = "chat-msg chat-msg--" + msg.role + (msg.typing ? " chat-msg--typing" : "");
    if (msg.typing && this._reducedMotion) el.className += " chat-msg--typing--reduced";
    el.setAttribute("data-id", domId);
    if (msg.msgId) el.setAttribute("data-msg-id", msg.msgId);
    else el.removeAttribute("data-msg-id");
    if (msg.request_id) el.setAttribute("data-request-id", msg.request_id);
    else el.removeAttribute("data-request-id");
    el.setAttribute("data-request-status", msg.request_status || msg.status || "");
    if (msg.typing) el.setAttribute("data-chat-typing", "true");
    else el.removeAttribute("data-chat-typing");
    el.innerHTML = this._buildMessageHtml(msg, { typing: Boolean(msg.typing) });
    this._bindMessageActions(el, msg);
    if (msg.msgId) {
      const numericId = Number(msg.msgId);
      if (Number.isFinite(numericId) && numericId > this._sinceId) this._sinceId = numericId;
    }
    this._trimMessageWindow("oldest");
    if (create && autoScroll) this._el.messages.scrollTop = this._el.messages.scrollHeight;
    return el;
  }

  // 撤回: 命中已有元素则标记, 否则创建撤回占位。id 为稳定 domId。
  _reconcileRecalled(id, before = null) {
    if (!this._el.messages || !id) return;
    const existing = this._el.messages.querySelector(`[data-id="${id}"]`);
    if (existing) {
      this._markRecalled(id);
      return;
    }
    const div = document.createElement("div");
    div.className = "chat-msg chat-msg--recalled";
    div.setAttribute("data-id", id);
    div.setAttribute("data-msg-id", id);
    div.innerHTML = this._recallNoticeHtml();
    if (before) this._el.messages.insertBefore(div, before);
    else this._el.messages.appendChild(div);
  }

  _removeMessage(id) {
    const el = this._el.messages && this._el.messages.querySelector(`[data-id="${id}"]`);
    if (el && el.parentNode) el.parentNode.removeChild(el);
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

  _isWorkMode() {
    const office = window.officeMode;
    if (office && typeof office.isOfficeActive === "function") {
      return office.isOfficeActive();
    }
    return false;
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
    // 非办公模式：日常闲聊完成时不展示"已完成"徽标（仅工作/办公模式保留）。
    // 办公模式(含 auto 下识别为工作的消息)才显示，见 _isWorkMode()。
    if (state.status === "completed" && !this._isWorkMode()) {
      messageEl.removeAttribute("data-request-status");
      const existing = messageEl.querySelector(".chat-request-status");
      if (existing) existing.remove();
      return;
    }
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
    if (!this._identityReady) return;
    const text = this._el.input.value.trim();
    if (!text && this._pendingAttachments.length === 0) return;
    if (this._pendingAttachments.some((attachment) => attachment.state !== "ready")) {
      alert("请等待所有附件解析完成，失败项可重试或移除");
      return;
    }
    this._el.input.value = "";

    const replyToId = this._quotedMsg ? this._quotedMsg.id : 0;
    const attachments = this._pendingAttachments.map((attachment) => ({
      id: attachment.attachmentId || attachment.id,
      attachmentId: attachment.attachmentId || attachment.id,
      name: attachment.name,
      size: attachment.size,
      type: attachment.category || attachment.type,
      category: attachment.category || attachment.type,
      state: attachment.state,
      contentType: attachment.contentType || "",
      sha256: attachment.sha256 || "",
      downloadUrl: attachment.downloadUrl || null,
      metadata: attachment.metadata || {},
    }));
    const clientId = this._newClientId();

    // Optimistic render — 走 store, 稳定 domId = clientId, 后续真实回显原地升级。
    for (const intent of this._store.ingestSignal({
      client_id: clientId,
      domId: clientId,
      role: "user",
      content: text,
      reply_to_id: replyToId,
      reply_to_content: this._quotedMsg?.content || "",
      reply_to_role: this._quotedMsg?.role || "",
      attachments,
    })) {
      this._applyIntent(intent);
    }

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
        // 通过 store 原地升级乐观气泡(稳定 domId = clientId), 不偷换 data-id。
        for (const intent of this._store.ingestSignal({
          id: realId,
          client_id: clientId,
          role: "user",
          content: text,
        })) {
          this._applyIntent(intent);
        }
      }
      if (resp.data && resp.data.reply) {
        // Server reply already pushed via IPC; this is a fallback
      }
    } catch (err) {
      for (const intent of this._store.ingestSignal({
        id: clientId + "_err",
        role: "assistant",
        content: "发送失败: " + err.message,
      })) {
        this._applyIntent(intent);
      }
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
      this._syncSendAvailability();
      return;
    }
    preview.style.display = "flex";
    preview.innerHTML = this._pendingAttachments
      .map((a) => {
        const id = a.attachmentId || a.id || "";
        const state = a.state || "queued";
        const stateLabel = this._attachmentStateLabel(state);
        const stateClass = "chat-attach-thumb--state-" + state;
        const error = a.error && (a.error.message || a.error.code);
        const retry = state === "failed" && id
          ? `<button type="button" data-pending-attachment-retry="${this._escapeHtml(id)}">重试</button>`
          : "";
        const remove = `<button type="button" data-pending-attachment-remove="${this._escapeHtml(id)}" title="移除">×</button>`;
        return `<div class="chat-attach-thumb ${stateClass}" data-attachment-id="${this._escapeHtml(id)}">
          <svg class="icon icon--14" aria-hidden="true"><use href="#icon-ui-attach"/></svg>
          <span class="chat-attach-thumb__name">${this._escapeHtml(a.name || "文件")}</span>
          <span class="chat-attach-thumb__state" title="${this._escapeHtml(error || stateLabel)}">${this._escapeHtml(stateLabel)}</span>
          ${retry}${remove}
        </div>`;
      })
      .join("");
    for (const button of preview.querySelectorAll("[data-pending-attachment-remove]")) {
      button.addEventListener("click", () => {
        if (this._uploader) {
          this._uploader.remove(button.getAttribute("data-pending-attachment-remove"));
        }
      });
    }
    for (const button of preview.querySelectorAll("[data-pending-attachment-retry]")) {
      button.addEventListener("click", () => {
        if (this._uploader) {
          this._uploader.retry(button.getAttribute("data-pending-attachment-retry"));
        }
      });
    }
    this._syncSendAvailability();
  }

  // ── Phase 4: Action menu (recall / quote / copy) ──
  _closeAllActionMenus() {
    document.querySelectorAll(".chat-action-menu").forEach((m) => m.remove());
  }

  _showActionMenu(msg, clientX, clientY) {
    this._closeAllActionMenus();
    const menu = document.createElement("div");
    menu.className = "chat-action-menu";

    const ageSec = (Date.now() - new Date(msg.created_at || Date.now()).getTime()) / 1000;
    const canRecall = ageSec < 120 && !msg.is_recalled;

    menu.innerHTML = `
      <button class="chat-action-menu__item" data-act="copy"><svg class="icon icon--14" aria-hidden="true"><use href="#icon-ui-copy"/></svg>复制</button>
      <button class="chat-action-menu__item" data-act="quote"><svg class="icon icon--14" aria-hidden="true"><use href="#icon-reply"/></svg>引用</button>
      ${canRecall ? '<button class="chat-action-menu__item" data-act="recall"><svg class="icon icon--14" aria-hidden="true"><use href="#icon-ui-trash"/></svg>撤回</button>' : ""}
    `;
    // Position at the right-click cursor, clamped so the menu never
    // runs off-screen.
    menu.style.position = "fixed";
    menu.style.left = Math.max(4, Math.min(clientX, window.innerWidth - 130)) + "px";
    menu.style.top = Math.max(4, Math.min(clientY, window.innerHeight - 120)) + "px";
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
  // 绑定单条消息元素上的事件(右键菜单 / 附件 / 引用跳转 / 代码高亮)。
  // 创建与更新逻辑集中在 _reconcileMessage, 此处只负责交互绑定。
  _bindMessageActions(el, msg) {
    if (!el || !msg) return;
    // Bind right-click on the message to open the action menu
    el.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      if (msg.id && !String(msg.id).startsWith("temp_")) {
        this._showActionMenu(msg, e.clientX, e.clientY);
      }
    });

    for (const button of el.querySelectorAll("[data-attachment-open]")) {
      button.addEventListener("click", () => {
        this._openAttachment(button.getAttribute("data-attachment-open"));
      });
    }
    for (const button of el.querySelectorAll("[data-attachment-retry]")) {
      button.addEventListener("click", () => {
        this._retryAttachment(button.getAttribute("data-attachment-retry"));
      });
    }
    // Clicking image thumbnail also opens the attachment
    for (const imgCard of el.querySelectorAll(".chat-attach-card--image")) {
      const cardId = imgCard.getAttribute("data-attachment-id");
      const state = imgCard.getAttribute("data-state");
      if (cardId && state === "ready") {
        const img = imgCard.querySelector(".chat-attach-card__image-wrap img");
        if (img) {
          img.style.cursor = "zoom-in";
          img.addEventListener("click", () => this._openAttachment(cardId));
        }
      }
    }

    // Bind quote overlay click → jump to original
    const quoteOverlay = el.querySelector(".chat-quote-overlay");
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
      el.querySelectorAll("pre code").forEach((code) => {
        try { window.hljs.highlightElement(code); } catch (_) {}
      });
    }
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
      // Rewrite relative <img src="..."> paths to absolute backend URL.
      // Electron's file:// protocol cannot resolve /uploads/... correctly,
      // so prefix the API base so images survive reload/restart.
      // Covers three cases: leading slash (/uploads/), no slash (uploads/),
      // and api/ prefixes (/api/... or api/...). data: / http: / https: bypass.
      let rewritten = safe.replace(
        /(<img[^>]+src=["'])(\/?(?:uploads|api)[^"']*["'])/gi,
        (_m, prefix, path) => {
          const normalized = path.startsWith("/") ? path : "/" + path;
          return prefix + "http://127.0.0.1:7890" + normalized;
        },
      );
      // Also rewrite pure Markdown ![alt](relative_url) in escaped HTML,
      // in case DOMPurify ever treats images differently between runs.
      rewritten = rewritten.replace(
        /(<a[^>]+href=["'])(\/?(?:uploads|api)[^"']*["'])/gi,
        (_m, prefix, path) => {
          const normalized = path.startsWith("/") ? path : "/" + path;
          return prefix + "http://127.0.0.1:7890" + normalized;
        },
      );
      return rewritten;
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
    const ss = pad(d.getSeconds());
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) return `${hh}:${mm}:${ss}`;
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${hh}:${mm}:${ss}`;
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
