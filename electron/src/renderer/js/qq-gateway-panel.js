"use strict";
/* QQ 引擎网关面板 — merged into Status tab */

class QQGatewayPanel {
  constructor() {
    this._el = {
      phaseDot: document.getElementById("qq-gateway-phase-dot"),
      phaseText: document.getElementById("qq-gateway-phase-text"),
      startBtn: document.getElementById("qq-gateway-start-btn"),
      stopBtn: document.getElementById("qq-gateway-stop-btn"),
      logs: document.getElementById("qq-gateway-logs"),
      qrZone: document.getElementById("qq-gateway-qr-zone"),
      qrImg: document.getElementById("qq-gateway-qr-img"),
      qrRefresh: document.getElementById("qq-gateway-qr-refresh"),
      statsQQ: document.getElementById("stats-qq"),
      qqBadge: document.getElementById("status-qq-badge"),
    };
    this._interval = null;
    this._qrLoading = false;
    this._bindEvents();
    this._bindQQToggle();
    this._startPoll();
  }

  _bindQQToggle() {
    const toggle = document.getElementById("status-qq-toggle");
    const section = document.getElementById("panel-status")?.querySelector(".status-qq-section");
    if (toggle && section) {
      toggle.addEventListener("click", () => {
        section.classList.toggle("collapsed");
      });
    }
  }

  _bindEvents() {
    if (this._el.startBtn) {
      this._el.startBtn.addEventListener("click", () => this.start());
    }
    if (this._el.stopBtn) {
      this._el.stopBtn.addEventListener("click", () => this.stop());
    }
    if (this._el.qrRefresh) {
      this._el.qrRefresh.addEventListener("click", () => this._refreshQR(true));
    }
  }

  _startPoll() {
    this._interval = setInterval(() => this._poll(), 3000);
    this._poll();
  }

  async _poll() {
    try {
      const resp = await window.aerie.qqGateway.getStatus();
      this._updateUI(resp);
    } catch (_) {}
    try {
      const logsResp = await window.aerie.api.request({
        method: "GET",
        path: "/api/qq/gateway/logs?limit=100",
      });
      if (logsResp && logsResp.data && logsResp.data.logs) {
        this._updateLogs(logsResp.data.logs);
      }
    } catch (_) {}
  }

  _updateLogs(logs) {
    if (!this._el.logs || !Array.isArray(logs)) return;
    const text = logs.join("\n");
    if (this._el.logs.textContent !== text) {
      this._el.logs.textContent = text;
      this._el.logs.scrollTop = this._el.logs.scrollHeight;
    }
  }

  _updateUI(status) {
    if (!status) return;
    const phase = status.phase || "idle";
    const phases = {
      idle: "未连接",
      starting: "启动中…",
      qr_pending: "等待扫码",
      connected: status.owned === false ? "已连接（外部）" : "已连接",
      error: "连接错误",
    };
    const errors = {
      backend_unreachable: "后端不可用",
      launcher_not_found: "未找到 QQ 引擎启动器",
      engine_start_timeout: "启动超时",
      engine_start_failed: "启动失败",
      engine_residual_port: "停止未完成",
      config_inject_failed: "配置注入失败",
    };
    const phaseText = phase === "error"
      ? (errors[status.error_code] || phases.error)
      : (phases[phase] || "状态未知");

    if (this._el.phaseDot) {
      this._el.phaseDot.className = "phase-dot phase-dot--" + phase;
    }
    if (this._el.phaseText) {
      this._el.phaseText.textContent = phaseText;
    }

    if (this._el.statsQQ) {
      this._el.statsQQ.textContent = phase === "connected" ? "已连接" : phaseText;
    }
    if (this._el.qqBadge) {
      this._el.qqBadge.className = "status-qq-badge status-qq-badge--" + phase;
      this._el.qqBadge.textContent = phaseText;
    }

    // QR code
    if (this._el.qrZone) {
      if (status.qrcode_available && phase === "qr_pending") {
        this._el.qrZone.classList.remove("hidden");
        if (this._el.qrImg && !this._el.qrImg.getAttribute("src")) {
          this._refreshQR(false);
        }
      } else if (phase !== "qr_pending") {
        this._el.qrZone.classList.add("hidden");
        if (this._el.qrImg) this._el.qrImg.removeAttribute("src");
      }
    }
    if (this._el.startBtn) {
      this._el.startBtn.disabled = ["starting", "qr_pending", "connected"].includes(phase);
    }
    if (this._el.stopBtn) {
      this._el.stopBtn.disabled = status.owned !== true;
      this._el.stopBtn.title = status.owned === true
        ? "停止由 Aerie 启动的 QQ 引擎"
        : "Aerie 不会停止外部启动的 QQ 引擎";
    }
  }

  async _refreshQR(showLog) {
    if (!this._el.qrImg || this._qrLoading) return;
    this._qrLoading = true;
    try {
      const response = await window.aerie.qqGateway.getQrCode();
      if (!response || response.ok !== true || !response.dataUrl) {
        throw new Error(response && response.errorCode || "qrcode_unavailable");
      }
      this._el.qrImg.src = response.dataUrl;
      if (showLog) this._addLog("[系统] 二维码已刷新");
    } catch (error) {
      this._addLog("[错误] 二维码刷新失败: " + String(error && error.message || error));
    } finally {
      this._qrLoading = false;
    }
  }

  async start() {
    this._addLog("[系统] 正在启动 QQ 引擎...");
    try {
      const resp = await window.aerie.qqGateway.start();
      this._addLog((resp && resp.ok === false ? "[错误] " : "[系统] ")
        + (resp.message || JSON.stringify(resp)));
      await this._poll();
    } catch (err) {
      this._addLog("[错误] 启动失败: " + err.message);
    }
  }

  async stop() {
    this._addLog("[系统] 正在停止 QQ 引擎...");
    try {
      const resp = await window.aerie.qqGateway.stop();
      this._addLog((resp && resp.ok === false ? "[错误] " : "[系统] ")
        + (resp.message || JSON.stringify(resp)));
      await this._poll();
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
  window._qqGatewayPanel = new QQGatewayPanel();
});
