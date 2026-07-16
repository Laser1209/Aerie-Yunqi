"use strict";
/* Chat voice input: Web Speech API (webkitSpeechRecognition) — Block-3 R0.2.
 *
 * 依赖浏览器内置 API，离线时会无声提示"需联网"，不抛错。
 * 录音中按钮加 is-recording 状态，状态条 chat-mic-status 出现脉冲。
 * 识别结果实时回写到 #chat-input.value。
 */

class ChatVoice {
  constructor(chat) {
    this._chat = chat;
    this._rec = null;
    this._supported = ("webkitSpeechRecognition" in window) || ("SpeechRecognition" in window);
    this._init();
  }

  _init() {
    const btn = document.getElementById("chat-mic-btn");
    if (!btn) return;
    if (!this._supported) {
      // 浏览器不支持 — 提示一次，不绑定后续
      btn.addEventListener("click", () => this._showHint("浏览器不支持语音 / Voice not supported"));
      btn.setAttribute("title", "浏览器不支持 / Not supported");
      return;
    }
    btn.addEventListener("click", () => this._toggle());
  }

  _toggle() {
    if (this._rec) {
      this._stop();
      return;
    }
    const Ctor = window.SpeechRecognition || window.webkitSpeechRecognition;
    const r = new Ctor();
    r.lang = (navigator.language || "zh-CN").startsWith("zh") ? "zh-CN" : "en-US";
    r.interimResults = true;
    r.continuous = false;
    r.maxAlternatives = 1;

    r.onresult = (e) => {
      let txt = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        txt += e.results[i][0].transcript;
      }
      const input = document.getElementById("chat-input");
      if (input) {
        input.value = txt;
        input.focus();
      }
    };
    r.onerror = () => {
      // network / not-allowed / no-speech 统一静默处理
      this._stop();
    };
    r.onend = () => {
      this._stop();
    };

    try {
      r.start();
    } catch (_) {
      // 已经在跑 / 拒绝授权等异常 — 静默
      return;
    }
    this._rec = r;

    const btn = document.getElementById("chat-mic-btn");
    if (btn) {
      btn.classList.add("is-recording");
      btn.setAttribute("aria-pressed", "true");
    }
    const status = document.getElementById("chat-mic-status");
    if (status) status.hidden = false;
  }

  _stop() {
    if (this._rec) {
      try { this._rec.stop(); } catch (_) {}
      this._rec = null;
    }
    const btn = document.getElementById("chat-mic-btn");
    if (btn) {
      btn.classList.remove("is-recording");
      btn.setAttribute("aria-pressed", "false");
    }
    const status = document.getElementById("chat-mic-status");
    if (status) status.hidden = true;
  }

  _showHint(msg) {
    // 静默：直接写 status-text bar，2s 自动消失
    const status = document.getElementById("chat-mic-status");
    if (!status) return;
    const text = status.querySelector(".chat-mic-status__text");
    if (!text) return;
    const old = text.textContent;
    text.textContent = msg;
    status.hidden = false;
    setTimeout(() => {
      text.textContent = old;
      if (!this._rec) status.hidden = true;
    }, 2000);
  }
}

window.ChatVoice = ChatVoice;
