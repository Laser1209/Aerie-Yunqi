"use strict";
/* NapCat control panel in the sidebar QQ tab */

class NapcatPanel {
  constructor() {
    this._el = {
      phaseDot: document.getElementById("napcat-phase-dot"),
      phaseText: document.getElementById("napcat-phase-text"),
      startBtn: document.getElementById("napcat-start-btn"),
      stopBtn: document.getElementById("napcat-stop-btn"),
      logs: document.getElementById("napcat-logs"),
      qrZone: document.getElementById("napcat-qr-zone"),
      qrImg: document.getElementById("napcat-qr-img"),
      qrRefresh: document.getElementById("napcat-qr-refresh"),
    };
    this._interval = null;
    this._bindEvents();
    this._startPoll();
  }

  _bindEvents() {
    if (this._el.startBtn) {
      this._el.startBtn.addEventListener("click", () => this.start());
    }
    if (this._el.stopBtn) {
      this._el.stopBtn.addEventListener("click", () => this.stop());
    }
    if (this._el.qrRefresh) {
      this._el.qrRefresh.addEventListener("click", () => this._refreshQR());
    }
  }

  _startPoll() {
    this._interval = setInterval(() => this._poll(), 3000);
    this._poll();
  }

  async _poll() {
    try {
      const resp = await window.aerie.napcat.getStatus();
      this._updateUI(resp);
    } catch (_) {}
  }

  _updateUI(status) {
    if (!status) return;
    const phase = status.phase || "idle";
    const phases = { idle: "未连接", starting: "启动中…", qr_pending: "等待扫码", connected: "已连接" };
    if (this._el.phaseDot) {
      this._el.phaseDot.className = "phase-dot phase-dot--" + phase;
    }
    if (this._el.phaseText) {
      this._el.phaseText.textContent = phases[phase] || phase;
    }

    // QR code
    if (this._el.qrZone) {
      if (status.qrcode_available && phase === "qr_pending") {
        this._el.qrZone.classList.remove("hidden");
        if (this._el.qrImg && status.qrcode_path) {
          this._el.qrImg.src = "http://127.0.0.1:7890/api/napcat/qrcode?t=" + Date.now();
        }
      } else if (phase !== "qr_pending") {
        this._el.qrZone.classList.add("hidden");
      }
    }
  }

  _refreshQR() {
    if (this._el.qrImg) {
      this._el.qrImg.src = "http://127.0.0.1:7890/api/napcat/qrcode?t=" + Date.now();
      this._addLog("[系统] 二维码已刷新");
    }
  }

  async start() {
    this._addLog("[系统] 正在启动 NapCat...");
    try {
      const resp = await window.aerie.napcat.start();
      this._addLog("[系统] " + (resp.message || JSON.stringify(resp)));
      this._poll();
    } catch (err) {
      this._addLog("[错误] 启动失败: " + err.message);
    }
  }

  async stop() {
    this._addLog("[系统] 正在停止 NapCat...");
    try {
      const resp = await window.aerie.napcat.stop();
      this._addLog("[系统] " + (resp.message || JSON.stringify(resp)));
      this._poll();
    } catch (err) {
      this._addLog("[错误] 停止失败: " + err.message);
    }
  }

  _addLog(text) {
    if (!this._el.logs) return;
    this._el.logs.textContent += text + "\n";
    this._el.logs.scrollTop = this._el.logs.scrollHeight;
  }
}

window.addEventListener("DOMContentLoaded", () => {
  window._napcatPanel = new NapcatPanel();
});
