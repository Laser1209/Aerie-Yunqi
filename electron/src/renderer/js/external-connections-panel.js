"use strict";

class ExternalConnectionsPanel {
  constructor(options = {}) {
    this.bridge = options.bridge || (window.aerie || {});
    this.statuses = {
      qq: { phase: "idle" },
      ilink: { phase: "disabled" },
    };
    this.actionPhases = new Set(["qr_pending", "scanned", "pairing_required", "session_expired", "error"]);
    this.lastAutoExpandedPhase = { qq: "", ilink: "" };
    this.elements = this.readElements();
    this.bindCollapsibles();
    this.bindPrimaryChannel();
    this.bindILinkActions();
    this.poll();
    this.interval = setInterval(() => this.poll(), 3000);
  }

  static aggregateStatuses(qqStatus = {}, ilinkStatus = {}) {
    const statuses = [qqStatus, ilinkStatus];
    const connected = statuses.filter((status) => status.phase === "connected").length;
    const errors = statuses.filter((status) => ["error", "session_expired"].includes(status.phase)).length;
    if (errors) return { connected, total: 2, errors, text: errors + " 个异常", phase: "error" };
    return {
      connected,
      total: 2,
      errors: 0,
      text: connected + "/2 " + (connected ? "已连接" : "未连接"),
      phase: connected === 2 ? "connected" : connected === 1 ? "partial" : "idle",
    };
  }

  readElements() {
    return {
      aggregate: document.getElementById("stats-external-connections"),
      aggregateBadge: document.getElementById("external-connections-badge"),
      outer: document.getElementById("external-connections-section"),
      outerToggle: document.getElementById("external-connections-toggle"),
      qq: document.getElementById("external-channel-qq"),
      qqToggle: document.getElementById("external-channel-qq-toggle"),
      ilink: document.getElementById("external-channel-ilink"),
      ilinkToggle: document.getElementById("external-channel-ilink-toggle"),
      ilinkBadge: document.getElementById("status-ilink-badge"),
      ilinkDot: document.getElementById("ilink-gateway-phase-dot"),
      ilinkText: document.getElementById("ilink-gateway-phase-text"),
      ilinkStart: document.getElementById("ilink-gateway-start-btn"),
      ilinkStop: document.getElementById("ilink-gateway-stop-btn"),
      ilinkQrImage: document.getElementById("ilink-gateway-qr-img"),
      ilinkLogs: document.getElementById("ilink-gateway-logs"),
      primaryInputs: Array.from(document.querySelectorAll('input[name="proactive-primary-channel"]')),
      primaryMessage: document.getElementById("primary-channel-message"),
    };
  }

  bindCollapsibles() {
    this.bindToggle(this.elements.outerToggle, this.elements.outer, () => this.poll());
    this.bindToggle(this.elements.qqToggle, this.elements.qq);
    this.bindToggle(this.elements.ilinkToggle, this.elements.ilink);
  }

  bindToggle(button, container, onExpand) {
    if (!button || !container) return;
    button.addEventListener("click", () => {
      const expanded = button.getAttribute("aria-expanded") !== "true";
      this.setExpanded(button, container, expanded);
      if (expanded && onExpand) onExpand();
    });
  }

  setExpanded(button, container, expanded) {
    button.setAttribute("aria-expanded", String(expanded));
    container.classList.toggle("collapsed", !expanded);
  }

  bindILinkActions() {
    if (this.elements.ilinkStart) this.elements.ilinkStart.addEventListener("click", () => this.runILinkAction("start"));
    if (this.elements.ilinkStop) this.elements.ilinkStop.addEventListener("click", () => this.runILinkAction("stop"));
  }

  bindPrimaryChannel() {
    this.loadPrimaryChannel();
    for (const input of this.elements.primaryInputs) {
      input.addEventListener("change", () => this.savePrimaryChannel(input.value));
    }
  }

  async loadPrimaryChannel() {
    const settings = this.bridge.settings && await this.bridge.settings.get();
    const channel = settings && settings.proactive && settings.proactive.primary_channel || "desktop";
    this.selectPrimaryChannel(channel);
  }

  async savePrimaryChannel(channel) {
    const previous = this.elements.primaryInputs.find((input) => input.defaultChecked || input.dataset.saved === "true");
    const status = this.statuses[channel];
    if (status && status.phase !== "connected") {
      this.selectPrimaryChannel(previous ? previous.value : "desktop");
      this.expandChannel(channel);
      this.showPrimaryMessage("请先连接对应渠道");
      return;
    }
    const result = this.bridge.settings && await this.bridge.settings.set({ proactive: { primary_channel: channel } });
    if (!result || result.error) {
      this.selectPrimaryChannel(previous ? previous.value : "desktop");
      this.showPrimaryMessage("主渠道保存失败");
      return;
    }
    this.selectPrimaryChannel(channel);
    this.showPrimaryMessage("主渠道已更新");
  }

  selectPrimaryChannel(channel) {
    for (const input of this.elements.primaryInputs) {
      input.checked = input.value === channel;
      input.defaultChecked = input.checked;
      input.dataset.saved = String(input.checked);
    }
  }

  showPrimaryMessage(message) {
    if (this.elements.primaryMessage) this.elements.primaryMessage.textContent = message;
  }

  async readILinkStatus() {
    const gateway = this.bridge && this.bridge.ilinkGateway;
    if (!gateway || typeof gateway.getStatus !== "function") {
      return { phase: "disabled", configured: false, connected: false, mockSafe: true };
    }
    try {
      return await gateway.getStatus();
    } catch (_) {
      return { phase: "error", configured: false, connected: false, error_code: "backend_unreachable" };
    }
  }

  async poll() {
    const napcat = this.bridge && this.bridge.napcat;
    const qqPromise = napcat && typeof napcat.getStatus === "function"
      ? napcat.getStatus().catch(() => ({ phase: "error" }))
      : Promise.resolve({ phase: "idle" });
    const [qqStatus, ilinkStatus] = await Promise.all([qqPromise, this.readILinkStatus()]);
    this.updateStatus("qq", qqStatus || { phase: "idle" });
    this.updateStatus("ilink", ilinkStatus || { phase: "disabled" });
    this.renderAggregate();
    this.renderILink();
  }

  updateStatus(channel, status) {
    const previousPhase = this.statuses[channel].phase;
    this.statuses[channel] = status;
    const phase = status.phase || "idle";
    if (this.actionPhases.has(phase) && phase !== previousPhase && this.lastAutoExpandedPhase[channel] !== phase) {
      this.lastAutoExpandedPhase[channel] = phase;
      this.expandChannel(channel);
    }
    window.dispatchEvent(new CustomEvent("external-connection-status", { detail: { channel, status } }));
  }

  expandChannel(channel) {
    const container = this.elements[channel];
    const toggle = this.elements[channel + "Toggle"];
    if (container && toggle) this.setExpanded(toggle, container, true);
    if (this.elements.outer && this.elements.outerToggle) this.setExpanded(this.elements.outerToggle, this.elements.outer, true);
  }

  renderAggregate() {
    const aggregate = ExternalConnectionsPanel.aggregateStatuses(this.statuses.qq, this.statuses.ilink);
    if (this.elements.aggregate) this.elements.aggregate.textContent = aggregate.text;
    if (this.elements.aggregateBadge) {
      this.elements.aggregateBadge.textContent = aggregate.text;
      this.elements.aggregateBadge.className = "external-status-badge external-status-badge--" + aggregate.phase;
    }
  }

  renderILink() {
    const status = this.statuses.ilink;
    const phase = status.phase || "disabled";
    const labels = {
      disabled: "未启用",
      idle: "未连接",
      starting: "连接中…",
      connected: "已连接",
      session_expired: "会话已失效",
      error: "连接错误",
    };
    const label = labels[phase] || "未连接";
    if (this.elements.ilinkBadge) {
      this.elements.ilinkBadge.textContent = label;
      this.elements.ilinkBadge.className = "external-status-badge external-status-badge--" + phase;
    }
    if (this.elements.ilinkDot) this.elements.ilinkDot.className = "phase-dot phase-dot--" + phase;
    if (this.elements.ilinkText) this.elements.ilinkText.textContent = label;
    if (this.elements.ilinkStart) this.elements.ilinkStart.disabled = ["starting", "connected"].includes(phase) || !status.configured;
    if (this.elements.ilinkStop) this.elements.ilinkStop.disabled = phase !== "connected";
    if (phase !== "qr_pending" && this.elements.ilinkQrImage) this.elements.ilinkQrImage.removeAttribute("src");
    if (this.elements.ilinkLogs) this.elements.ilinkLogs.textContent = status.error_code || (status.mockSafe ? "等待后端连接能力" : label);
  }

  async runILinkAction(action) {
    const gateway = this.bridge && this.bridge.ilinkGateway;
    if (!gateway || typeof gateway[action] !== "function") return;
    await gateway[action]();
    await this.poll();
  }
}

window.ExternalConnectionsPanel = ExternalConnectionsPanel;
window.addEventListener("DOMContentLoaded", () => {
  window._externalConnectionsPanel = new ExternalConnectionsPanel();
});
