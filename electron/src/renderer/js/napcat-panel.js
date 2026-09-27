"use strict";
/* NapCat control panel — merged into Status tab */

class NapcatPanel {
  constructor() {
    this._el = {
      phaseDot: document.getElementById("napcat-phase-dot"),
      phaseText: document.getElementById("napcat-phase-text"),
      startBtn: document.getElementById("napcat-start-btn"),
      stopBtn: document.getElementById("napcat-stop-btn"),
      downloadBtn: document.getElementById("napcat-download-btn"),
      checkUpdateBtn: document.getElementById("napcat-check-update-btn"),
      logs: document.getElementById("napcat-logs"),
      qrZone: document.getElementById("napcat-qr-zone"),
      qrImg: document.getElementById("napcat-qr-img"),
      qrHint: document.getElementById("napcat-qr-hint"),
      qrRefresh: document.getElementById("napcat-qr-refresh"),
      quickLogin: document.getElementById("napcat-quick-login"),
      qqBadge: document.getElementById("status-qq-badge"),
    };
    this._interval = null;
    this._qrLoading = false;
    this._qrFetchAt = 0;
    this._autoRenewAt = 0;
    this._accountsAt = 0;
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
    if (this._el.downloadBtn) {
      this._el.downloadBtn.addEventListener("click", () => this.download());
    }
    if (this._el.checkUpdateBtn) {
      this._el.checkUpdateBtn.addEventListener("click", () => this.checkUpdate());
    }
    if (this._el.qrRefresh) {
      this._el.qrRefresh.addEventListener("click", () => this._refreshQR(true, { forceRenew: true }));
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
    try {
      const logsResp = await window.aerie.api.request({
        method: "GET",
        path: "/api/napcat/logs?limit=100",
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
      starting: "登录中…",
      qr_pending: "等待扫码",
      qr_expired: "二维码已过期",
      connected: status.owned === false ? "已连接（外部）" : "已连接",
      error: "连接错误",
    };
    const errors = {
      backend_unreachable: "后端不可用",
      launcher_not_found: "未找到 NapCat 启动器",
      napcat_start_timeout: "启动超时",
      napcat_start_failed: "启动失败",
      napcat_residual_port: "停止未完成",
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

    if (this._el.qqBadge) {
      this._el.qqBadge.className = "external-status-badge external-status-badge--" + phase;
      this._el.qqBadge.textContent = phaseText;
    }

    // QR code
    if (this._el.qrZone) {
      if (status.qrcode_available && (phase === "qr_pending" || phase === "qr_expired")) {
        this._el.qrZone.classList.remove("hidden");
        const expired = phase === "qr_expired";
        if (this._el.qrHint) this._el.qrHint.classList.toggle("hidden", !expired);
        if (expired) {
          // Ask NapCat for a brand-new QR once, then let normal polling
          // redraw the image; throttle so the 3s poll cannot spam renewals.
          const now = Date.now();
          if (now - this._autoRenewAt > 30000) {
            this._autoRenewAt = now;
            this._refreshQR(false, { forceRenew: true });
          }
        } else {
          this._ensureQrImage();
        }
        this._loadQuickAccounts();
      } else if (phase !== "qr_pending" && phase !== "qr_expired") {
        this._el.qrZone.classList.add("hidden");
        if (this._el.qrImg) this._el.qrImg.removeAttribute("src");
        if (this._el.qrHint) this._el.qrHint.classList.add("hidden");
        if (this._el.quickLogin) this._el.quickLogin.innerHTML = "";
        this._qrFetchAt = 0;
      }
    }
    if (this._el.startBtn) {
      this._el.startBtn.disabled = ["starting", "qr_pending", "qr_expired", "connected"].includes(phase);
    }
    if (this._el.downloadBtn) {
      const missing = phase === "error" && status.error_code === "launcher_not_found";
      this._el.downloadBtn.classList.toggle("hidden", !missing);
    }
    if (this._el.stopBtn) {
      this._el.stopBtn.disabled = status.owned !== true;
      this._el.stopBtn.title = status.owned === true
        ? "停止由 Aerie 启动的 NapCat"
        : "Aerie 不会停止外部启动的 NapCat";
    }
  }

  async _ensureQrImage() {
    // Throttle redraws so the 3s status poll does not refetch every tick.
    if (!this._el.qrImg || this._qrLoading) return;
    const now = Date.now();
    if (this._el.qrImg.getAttribute("src") && now - this._qrFetchAt < 5000) return;
    await this._refreshQR(false);
  }

  async _refreshQR(showLog, options = {}) {
    if (!this._el.qrImg || this._qrLoading) return;
    this._qrLoading = true;
    try {
      if (options.forceRenew && window.aerie.napcat.refreshQrCode) {
        const renew = await window.aerie.napcat.refreshQrCode();
        if (renew && renew.ok === false) {
          throw new Error(renew.message || "qrcode_renew_failed");
        }
        await new Promise((resolve) => setTimeout(resolve, 800));
      }
      const response = await window.aerie.napcat.getQrCode();
      if (!response || response.ok !== true || !response.dataUrl) {
        throw new Error(response && response.errorCode || "qrcode_unavailable");
      }
      this._qrFetchAt = Date.now();
      this._el.qrImg.src = response.dataUrl;
      if (this._el.qrHint) this._el.qrHint.classList.add("hidden");
      if (showLog) this._addLog("[系统] 二维码已刷新");
    } catch (error) {
      this._addLog("[错误] 二维码刷新失败: " + String(error && error.message || error));
    } finally {
      this._qrLoading = false;
    }
  }

  async _loadQuickAccounts() {
    if (!this._el.quickLogin || !window.aerie.napcat.getQuickAccounts) return;
    const now = Date.now();
    if (now - this._accountsAt < 60000) return;
    this._accountsAt = now;
    try {
      const accounts = await window.aerie.napcat.getQuickAccounts();
      const usable = (accounts || []).filter((item) => item.is_quick_login !== false && item.uin);
      if (!usable.length) {
        this._el.quickLogin.innerHTML = "";
        return;
      }
      this._el.quickLogin.innerHTML =
        '<p class="external-channel-hint">本机已登录账号可免扫码快捷登录：</p>'
        + usable.map((item) => {
          const label = item.nickname ? `${item.nickname}（${item.uin}）` : item.uin;
          return `<button type="button" class="btn btn-secondary btn-sm napcat-quick-login-btn" data-uin="${item.uin}">${label}</button>`;
        }).join("");
      this._el.quickLogin.querySelectorAll(".napcat-quick-login-btn").forEach((btn) => {
        btn.addEventListener("click", () => this._quickLogin(btn.dataset.uin));
      });
    } catch (_) {
      /* quick login is an enhancement; ignore transient failures */
    }
  }

  async _quickLogin(uin) {
    this._addLog(`[系统] 正在请求快捷登录 ${uin}…`);
    try {
      const resp = await window.aerie.napcat.quickLogin(uin);
      if (resp && resp.ok === false) {
        this._addLog("[错误] 快捷登录失败: " + (resp.message || ""));
        return;
      }
      this._addLog("[系统] 快捷登录请求已发送，请稍候");
      await this._poll();
    } catch (error) {
      this._addLog("[错误] 快捷登录失败: " + String(error && error.message || error));
    }
  }

  async start() {
    this._addLog("[系统] 正在启动 NapCat...");
    try {
      const resp = await window.aerie.napcat.start();
      this._addLog((resp && resp.ok === false ? "[错误] " : "[系统] ")
        + (resp.message || JSON.stringify(resp)));
      await this._poll();
    } catch (err) {
      this._addLog("[错误] 启动失败: " + err.message);
    }
  }

  async stop() {
    this._addLog("[系统] 正在停止 NapCat...");
    try {
      const resp = await window.aerie.napcat.stop();
      this._addLog((resp && resp.ok === false ? "[错误] " : "[系统] ")
        + (resp.message || JSON.stringify(resp)));
      await this._poll();
    } catch (err) {
      this._addLog("[错误] 停止失败: " + err.message);
    }
  }

  async download() {
    if (this._el.downloadBtn) {
      this._el.downloadBtn.disabled = true;
      this._el.downloadBtn.textContent = "下载中…";
    }
    this._addLog("[系统] 正在请求下载 NapCat…");
    try {
      const startResp = await window.aerie.api.request({
        method: "POST",
        path: "/api/napcat/download",
      });
      if (!startResp || startResp.ok !== true) {
        throw new Error((startResp && startResp.data && startResp.data.message) || "下载启动失败");
      }
      // 轮询下载进度（最长约 6 分钟）
      let lastMsg = "";
      let finished = false;
      for (let i = 0; i < 180; i++) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const st = await window.aerie.api.request({
          method: "GET",
          path: "/api/napcat/download/status",
        });
        const s = (st && st.data) || {};
        if (s.state === "done") {
          this._addLog("[系统] " + (s.message || "NapCat 下载完成"));
          finished = true;
          break;
        }
        if (s.state === "error") {
          throw new Error(s.error || s.message || "下载失败");
        }
        const msg = s.message || "";
        if (msg && msg !== lastMsg) {
          this._addLog("[系统] " + msg);
          lastMsg = msg;
        }
      }
      if (!finished) {
        throw new Error("下载超时，请稍后重试");
      }
      // 下载解压完成后自动启动
      await this.start();
    } catch (err) {
      this._addLog("[错误] " + String(err && err.message || err));
    } finally {
      if (this._el.downloadBtn) {
        this._el.downloadBtn.disabled = false;
        this._el.downloadBtn.textContent = "下载 NapCat";
      }
    }
  }

  async checkUpdate() {
    this._addLog("[系统] 正在检查 NapCat 更新…");
    try {
      const resp = await window.aerie.api.request({
        method: "GET",
        path: "/api/napcat/update/check",
      });
      const s = (resp && resp.data) || {};
      if (s.installed === false) {
        this._addLog("[系统] NapCat 尚未安装，可点击「下载 NapCat」安装。");
      } else if (s.has_update) {
        this._addLog(`[更新] 发现新版本：${s.latest}（当前 ${s.current}）`);
      } else if (s.latest) {
        this._addLog(`[系统] 已是最新版本：${s.latest}`);
      } else {
        this._addLog("[系统] 检查更新失败，请稍后重试");
      }
    } catch (err) {
      this._addLog("[错误] 检查更新失败: " + String(err && err.message || err));
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
