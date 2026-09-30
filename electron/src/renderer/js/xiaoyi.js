"use strict";
/*
 * 小伊 · 系统管家 —— 独立窗口的前端。
 *
 * 为什么单独一个窗口 + 单独一个模块，而不是塞进主窗口：小伊与主人格
 * **物理隔离** —— 不同会话、不同提示词、不同关注点。混在一起迟早会把
 * "系统配置"漏进伊塔的嘴里，那正是这个角色要解决的问题。她也不该占走聊天区的地方。
 *
 * 数据来源：GET /api/xiaoyi/snapshot（轮询 5s）+ POST /api/xiaoyi/chat。
 * 窗口位置/显隐由主进程管（见 main.js 的 xiaoyi:open/close 与 computeXiaoyiDock），
 * 这里只管内容：看板 + 对话。
 */

const XIAOYI_POLL_MS = 5000;

class XiaoyiWindow {
  constructor() {
    this._el = {
      avatar: document.getElementById("xiaoyi-avatar"),
      board: document.getElementById("xiaoyi-board"),
      chat: document.getElementById("xiaoyi-chat"),
      form: document.getElementById("xiaoyi-form"),
      input: document.getElementById("xiaoyi-input"),
      send: document.getElementById("xiaoyi-send"),
      refresh: document.getElementById("xiaoyi-refresh"),
      close: document.getElementById("xiaoyi-close"),
    };
    this._history = [];
    this._timer = null;
    this._busy = false;
  }

  init() {
    if (this._el.avatar && !this._el.avatar.getAttribute("src")) {
      // 立绘由用户后续提供；先用应用图标占位，不伪造形象。
      this._el.avatar.setAttribute("src", "logo-96.png");
    }

    if (this._el.close) {
      this._el.close.addEventListener("click", () => this.close());
    }
    if (this._el.refresh) {
      this._el.refresh.addEventListener("click", () => this.refresh());
    }
    if (this._el.form) {
      this._el.form.addEventListener("submit", (e) => {
        e.preventDefault();
        this.send();
      });
    } else if (this._el.send) {
      this._el.send.addEventListener("click", () => this.send());
    }

    document.addEventListener("visibilitychange", () => {
      // 窗口被收起时停掉轮询，别在看不见的地方空转。
      if (document.hidden) this._stopPolling();
      else {
        this.refresh();
        this._startPolling();
      }
    });

    this.refresh();
    this._startPolling();
  }

  /** 「收起」= 让主进程隐藏本窗口并把主窗口收回原位，不销毁（记录留着）。 */
  close() {
    const api = window.aerie && window.aerie.xiaoyi;
    if (api && typeof api.close === "function") api.close();
    else window.close();
  }

  _startPolling() {
    this._stopPolling();
    this._timer = setInterval(() => {
      if (!document.hidden) this.refresh();
    }, XIAOYI_POLL_MS);
  }

  _stopPolling() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  async _request(opts) {
    const api = window.aerie && window.aerie.api;
    if (api && typeof api.request === "function") return api.request(opts);
    return { status: 0, data: {} };
  }

  async refresh() {
    if (!this._el.board) return;
    try {
      const resp = await this._request({ method: "GET", path: "/api/xiaoyi/snapshot" });
      if (resp && resp.data && resp.data.status === "ok") this._renderBoard(resp.data);
    } catch (_) {
      /* 后端没起来时静默：侧栏不该刷错误 */
    }
  }

  /** 每条数据配一句小白话 —— 用户看的是"要不要管我"，不是指标本身。 */
  _renderBoard(snap) {
    const rows = [];
    const health = snap.health || {};
    const tokens = snap.tokens || {};
    const caps = snap.capabilities || {};

    if (health.uptime_text) {
      rows.push(["运行状况", `运行正常，已经连续工作 ${health.uptime_text}`]);
    }
    const banned = health.providers_banned || [];
    if (banned.length) {
      rows.push(["需要注意", `${banned.length} 个模型服务暂时连不上，我会自动换别的`]);
    }

    const calls = tokens.calls || tokens.count || 0;
    const used = tokens.total_tokens || tokens.tokens || 0;
    if (calls || used) {
      rows.push(["今日用量", `今天思考了 ${calls} 次，用掉约 ${used} 个字`]);
    }

    const unavailable = caps.unavailable || [];
    if (unavailable.length) {
      rows.push(["待处理项", `有 ${unavailable.length} 个功能还没配好，点我就能帮你看看怎么开`, unavailable]);
    }

    const pending = snap.pending_proposals || 0;
    if (pending) {
      rows.push(["待确认", `有 ${pending} 条改进提案在等你确认`]);
    }

    if (!rows.length) rows.push(["运行状况", "一切正常，没有需要你处理的事"]);

    this._el.board.innerHTML = "";
    for (const [label, value, todos] of rows) {
      const li = document.createElement("li");
      li.className = "xiaoyi-board__row";
      const labelEl = document.createElement("span");
      labelEl.className = "xiaoyi-board__label";
      labelEl.textContent = label;
      const valueEl = document.createElement("span");
      valueEl.className = "xiaoyi-board__value";
      valueEl.textContent = value;
      li.appendChild(labelEl);
      li.appendChild(valueEl);
      if (Array.isArray(todos) && todos.length) {
        const ul = document.createElement("ul");
        ul.className = "xiaoyi-board__todo";
        for (const item of todos) {
          const entry = document.createElement("li");
          const where = item.where ? ` → ${item.where}` : "";
          entry.textContent = `${item.name}：${item.unavailable_reason || "不可用"}${where}`;
          ul.appendChild(entry);
        }
        li.appendChild(ul);
      }
      this._el.board.appendChild(li);
    }
  }

  _appendMessage(role, text) {
    if (!this._el.chat) return;
    const div = document.createElement("div");
    div.className = `xiaoyi-msg xiaoyi-msg--${role === "user" ? "user" : "xiaoyi"}`;
    div.textContent = String(text || "");
    this._el.chat.appendChild(div);
    this._el.chat.scrollTop = this._el.chat.scrollHeight;
  }

  async send() {
    if (this._busy || !this._el.input) return;
    const text = String(this._el.input.value || "").trim();
    if (!text) return;

    this._busy = true;
    if (this._el.send) this._el.send.disabled = true;
    this._el.input.value = "";
    this._appendMessage("user", text);
    this._history.push({ role: "user", content: text });

    try {
      const resp = await this._request({
        method: "POST",
        path: "/api/xiaoyi/chat",
        body: { message: text, history: this._history.slice(-6) },
      });
      const data = (resp && resp.data) || {};
      const reply = data.reply || data.error || "我这边暂时答不上来，等会儿再问我一次？";
      this._appendMessage("xiaoyi", reply);
      if (data.reply) this._history.push({ role: "assistant", content: data.reply });
    } catch (_) {
      this._appendMessage("xiaoyi", "后端好像没连上，稍后再试。");
    } finally {
      this._busy = false;
      if (this._el.send) this._el.send.disabled = false;
    }
  }
}

window.addEventListener("DOMContentLoaded", () => {
  const win = new XiaoyiWindow();
  win.init();
  window._xiaoyi = win;
});
