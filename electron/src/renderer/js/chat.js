"use strict";
/* Chat manager: shared between main window and floating chat bar */

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

    this._bindEvents();
    this._listenIPC();
    this._startPoll();
    this.loadHistory();
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
        }
      });
    }
  }

  _listenIPC() {
    if (!window.aerie) return;
    window.aerie.api.onMessage((msg) => {
      if (this._seenIds.has(msg.id)) return;
      this._seenIds.add(msg.id);
      this._render(msg);
    });
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
          if (this._seenIds.has(item.id)) continue;
          this._seenIds.add(item.id);
          this._render(item);
          if (item.id > this._sinceId) this._sinceId = item.id;
        }
      }
    } catch (_) {}
  }

  async send() {
    if (this._loading) return;
    const text = this._el.input.value.trim();
    if (!text) return;
    this._el.input.value = "";
    this._loading = true;

    // Optimistic render
    const tempId = "temp_" + Date.now();
    this._render({ id: tempId, role: "user", content: text });

    try {
      const resp = await this._request({
        method: "POST",
        path: "/api/chat/send",
        body: { text, user_id: this._masterQQ },
      });
      // IPC already delivers the assistant reply — just confirm
      if (resp.data && resp.data.reply) {
        this._render({ id: tempId + "_r", role: "assistant", content: resp.data.reply });
      }
    } catch (err) {
      this._render({ id: tempId + "_err", role: "assistant", content: "发送失败: " + err.message });
    } finally {
      this._loading = false;
    }
  }

  _render(msg) {
    if (!this._el.messages) return;
    const empty = this._el.messages.querySelector(".chat-empty");
    if (empty) empty.remove();

    // Remove temp optimistic bubble
    const oldTemp = this._el.messages.querySelector('[data-id^="temp_"]');
    if (msg.id && !String(msg.id).startsWith("temp_") && oldTemp) {
      oldTemp.remove();
    }

    // Don't re-render duplicate real messages
    if (!String(msg.id).startsWith("temp_") && this._el.messages.querySelector(`[data-id="${msg.id}"]`)) {
      return;
    }

    const div = document.createElement("div");
    div.className = "chat-msg chat-msg--" + msg.role;
    div.setAttribute("data-id", msg.id);
    div.innerHTML = `<div class="chat-bubble">${this._escapeHtml(msg.content)}</div>`;
    this._el.messages.appendChild(div);
    this._el.messages.scrollTop = this._el.messages.scrollHeight;
  }

  _escapeHtml(text) {
    const d = document.createElement("div");
    d.textContent = text;
    return d.innerHTML.replace(/\n/g, "<br>");
  }

  async _request(opts) {
    if (window.aerie) {
      try {
        return await window.aerie.api.request(opts);
      } catch (_) {}
    }
    // Fallback: direct HTTP
    const url = "http://127.0.0.1:7890" + opts.path;
    const init = { method: opts.method || "GET", headers: { "Content-Type": "application/json" } };
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
