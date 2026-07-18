"use strict";
/* v13.0: Permission Approval Modal — 屏幕控制操作审批弹窗 */

class ApprovalModal {
  constructor() {
    this._pending = [];
    this._current = null;
    this._el = null;
    this._pollTimer = null;
    this._sseUnsub = null;
  }

  init() {
    this._buildDom();
    this._startPolling();

    // SSE 实时推送（如果可用）
    if (window.aerie && window.aerie.sse && window.aerie.sse.subscribe) {
      this._sseUnsub = window.aerie.sse.subscribe((ev) => {
        if (ev && ev.event === "computer_control_approval_requested") {
          this._onNewApproval(ev.data);
        }
      });
    }
  }

  _buildDom() {
    if (document.getElementById("approval-modal-overlay")) return;

    const overlay = document.createElement("div");
    overlay.id = "approval-modal-overlay";
    overlay.className = "approval-modal-overlay";
    overlay.innerHTML = `
      <div class="approval-modal">
        <div class="approval-modal__header">
          <div class="approval-modal__icon">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 2.333 2 1.732 3z"/>
            </svg>
          </div>
          <div class="approval-modal__titles">
            <h3 class="approval-modal__title">操作授权确认</h3>
            <p class="approval-modal__subtitle">伊塔请求执行以下操作，请确认</p>
          </div>
        </div>

        <div class="approval-modal__body">
          <div class="approval-modal__action-row">
            <span class="approval-modal__label">操作类型</span>
            <span class="approval-modal__value" id="approval-action-type">--</span>
          </div>
          <div class="approval-modal__action-row">
            <span class="approval-modal__label">风险等级</span>
            <span class="approval-modal__value">
              <span class="approval-risk-badge" id="approval-risk-badge">--</span>
            </span>
          </div>
          <div class="approval-modal__action-row approval-modal__params-row">
            <span class="approval-modal__label">操作详情</span>
            <div class="approval-modal__params" id="approval-params">--</div>
          </div>
          <div class="approval-modal__pending">
            <span id="approval-pending-count">还有 0 个待审批</span>
          </div>
        </div>

        <div class="approval-modal__footer">
          <button class="approval-btn approval-btn--reject" id="approval-reject-btn">
            拒绝
          </button>
          <button class="approval-btn approval-btn--approve" id="approval-approve-btn">
            允许执行
          </button>
        </div>
      </div>
    `;
    document.body.appendChild(overlay);

    this._el = overlay;

    // 按钮绑定
    overlay.querySelector("#approval-approve-btn").addEventListener("click", () => {
      this._approveCurrent();
    });
    overlay.querySelector("#approval-reject-btn").addEventListener("click", () => {
      this._rejectCurrent();
    });

    // 点击遮罩不关闭（必须明确选择）
  }

  async _startPolling() {
    // 先拉一次
    try {
      await this._fetchPending();
    } catch (_) {}

    // 每 3 秒轮询一次
    this._pollTimer = setInterval(() => {
      this._fetchPending().catch(() => {});
    }, 3000);
  }

  async _fetchPending() {
    if (!window.aerie || !window.aerie.api) return;

    const r = await window.aerie.api.request({
      method: "GET",
      path: "/api/computer_control/approvals/pending",
    });
    if (r && r.data && r.data.approvals) {
      const approvals = r.data.approvals;
      const existingIds = new Set(this._pending.map((a) => a.id));

      for (const a of approvals) {
        if (!existingIds.has(a.id)) {
          this._pending.push(a);
        }
      }

      // 清理已处理的
      const currentIds = new Set(approvals.map((a) => a.id));
      this._pending = this._pending.filter((a) => currentIds.has(a.id));

      if (this._pending.length > 0 && !this._current) {
        this._showNext();
      }
      this._updatePendingCount();
    }
  }

  _onNewApproval(approval) {
    if (!approval || !approval.id) return;
    if (this._pending.some((a) => a.id === approval.id)) return;

    this._pending.push(approval);
    if (!this._current) {
      this._showNext();
    }
    this._updatePendingCount();
  }

  _showNext() {
    if (this._pending.length === 0) {
      this._hide();
      return;
    }

    this._current = this._pending.shift();
    this._renderCurrent();
    this._show();
  }

  _renderCurrent() {
    if (!this._current) return;

    const actionNames = {
      screenshot: "屏幕截图",
      mouse_move: "移动鼠标",
      mouse_click: "鼠标点击",
      mouse_scroll: "滚轮滚动",
      key_press: "键盘按键",
      key_type: "输入文本",
      shell_cmd: "执行命令",
      window_info: "获取窗口列表",
      window_focus: "切换窗口",
      uia_action: "UI 自动化操作",
    };

    const actionType = this._current.action || "unknown";
    document.getElementById("approval-action-type").textContent =
      actionNames[actionType] || actionType;

    // 风险等级
    const risk = this._current.risk_level || "medium";
    const riskBadge = document.getElementById("approval-risk-badge");
    riskBadge.textContent = this._riskLabel(risk);
    riskBadge.className = "approval-risk-badge approval-risk-badge--" + risk;

    // 参数
    const paramsEl = document.getElementById("approval-params");
    const params = this._current.params || {};
    const keys = Object.keys(params);
    if (keys.length === 0) {
      paramsEl.textContent = "无额外参数";
    } else {
      paramsEl.innerHTML = keys.map((k) =>
        `<div class="approval-param"><span class="approval-param__key">${k}</span>` +
        `<span class="approval-param__value">${this._escapeHtml(String(params[k]))}</span></div>`
      ).join("");
    }
  }

  _riskLabel(risk) {
    const map = {
      safe: "安全",
      low: "低风险",
      medium: "中风险",
      high: "高风险",
      critical: "危险",
    };
    return map[risk] || risk;
  }

  _updatePendingCount() {
    const el = document.getElementById("approval-pending-count");
    if (!el) return;
    const total = this._pending.length + (this._current ? 1 : 0);
    if (total <= 1) {
      el.textContent = "";
    } else {
      el.textContent = `还有 ${this._pending.length} 个待审批`;
    }
  }

  async _approveCurrent() {
    if (!this._current) return;
    const id = this._current.id;

    try {
      await window.aerie.api.request({
        method: "POST",
        path: `/api/computer_control/approvals/${id}/approve`,
      });
    } catch (_) {}

    this._current = null;
    this._showNext();
  }

  async _rejectCurrent() {
    if (!this._current) return;
    const id = this._current.id;

    try {
      await window.aerie.api.request({
        method: "POST",
        path: `/api/computer_control/approvals/${id}/reject`,
      });
    } catch (_) {}

    this._current = null;
    this._showNext();
  }

  _show() {
    if (this._el) {
      this._el.classList.add("approval-modal-overlay--visible");
    }
  }

  _hide() {
    if (this._el) {
      this._el.classList.remove("approval-modal-overlay--visible");
    }
  }

  _escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s;
    return div.innerHTML;
  }
}

window.ApprovalModal = ApprovalModal;
