"use strict";

class WorldDashboardPanel {
  constructor() {
    this._visible = false;
    this._initialized = false;
    this._els = {};
    this._pollTimer = null;
    this._operationSequence = 0;
    this._lifecycle = defaultLifecycle();
  }

  init() {
    if (this._initialized) return Promise.resolve();
    this._initialized = true;
    this._bindElements();
    this._wireActions();
    this._renderStatus({
      status: "idle",
      visible: false,
      plugin: { pluginId: "aerie.world", state: "not_checked", crashCount: 0 },
      backend: { status: "not_checked" },
      panels: [],
      errors: [],
      chatPublishAvailable: true,
      lifecycle: defaultLifecycle(),
    });
    return Promise.resolve();
  }

  setVisible(visible) {
    this._visible = !!visible;
    if (this._visible) {
      this.refresh();
      this._startPolling();
    } else {
      this._stopPolling();
    }
  }

  async refresh() {
    const api = this._api();
    if (!api || typeof api.getStatus !== "function") {
      this._renderUnavailable("preload_missing");
      return;
    }
    await this._withButton(this._els.refresh, async () => {
      try {
        this._renderStatus(await api.getStatus());
      } catch (_) {
        this._renderUnavailable("status_failed");
      }
    });
  }

  async show() {
    const api = this._api();
    if (!api || typeof api.show !== "function") return this.refresh();
    await this._withButton(this._els.show, async () => this._renderStatus(await api.show()));
  }

  async hide() {
    const api = this._api();
    if (!api || typeof api.hide !== "function") return this.refresh();
    await this._withButton(this._els.hide, async () => this._renderStatus(await api.hide()));
  }

  async control(action) {
    const api = this._api();
    const command = safeInput(action).toLowerCase();
    const invoke = api && (typeof api.control === "function"
      ? (payload) => api.control(command, payload)
      : (typeof api[command] === "function" ? (payload) => api[command](payload) : null));
    if (!invoke) {
      setText(this._els.runtimeError || this._els.errors, "lifecycle_unsupported");
      return;
    }
    await this._withButton(this._els[command], async () => {
      try {
        const result = await invoke({
          expectedRevision: Number(this._lifecycle.revision || 0),
          configExpectedRevision: Number(this._lifecycle.configRevision || 0),
          idempotencyKey: this._operationId(command),
        });
        setText(
          this._els.runtimeError || this._els.errors,
          result && result.accepted === true ? "" : safeInput(result && result.errorCode) || "control_rejected",
        );
      } catch (_) {
        setText(this._els.runtimeError || this._els.errors, "control_failed");
      }
      await this.refresh();
    });
  }

  _bindElements() {
    const byId = (id) => document.getElementById(id);
    const ids = [
      "status", "visible", "plugin", "backend", "chat-publish", "panels", "errors", "updated",
      "refresh", "show", "hide",
      "enabled", "desired", "actual", "adapter", "revision", "runtime-health", "last-tick",
      "last-checkpoint", "runtime-error", "enable", "disable", "start", "stop", "pause", "resume", "restart",
    ];
    ids.forEach((suffix) => { this._els[toCamel(suffix)] = byId(`world-dashboard-${suffix}`); });
  }

  _wireActions() {
    ["refresh", "show", "hide"].forEach((action) => onClick(this._els[action], () => this[action]()));
    ["enable", "disable", "start", "stop", "pause", "resume", "restart"].forEach((action) => {
      onClick(this._els[action], () => this.control(action));
    });
  }

  _renderUnavailable(errorCode) {
    this._renderStatus({
      status: "unavailable",
      visible: false,
      plugin: { pluginId: "aerie.world", state: errorCode, crashCount: 0 },
      backend: { status: "unreachable" },
      panels: [],
      errors: [errorCode],
      chatPublishAvailable: true,
      lifecycle: { ...defaultLifecycle(), errorCode },
    });
  }

  _renderStatus(status) {
    const safeStatus = status && typeof status === "object" ? status : {};
    const plugin = objectValue(safeStatus.plugin);
    const backend = objectValue(safeStatus.backend);
    const lifecycleSource = safeStatus.lifecycle && typeof safeStatus.lifecycle === "object"
      ? safeStatus.lifecycle
      : plugin;
    this._lifecycle = {
      enabled: lifecycleSource.enabled === true,
      desired: safeInput(lifecycleSource.desired || "stopped"),
      actual: safeInput(lifecycleSource.actual || "stopped"),
      adapter: safeInput(lifecycleSource.adapter || "null"),
      revision: Number(lifecycleSource.revision || 0),
      configRevision: Number(lifecycleSource.configRevision || 0),
    };
    const panels = Array.isArray(safeStatus.panels) ? safeStatus.panels : [];
    const errors = Array.isArray(safeStatus.errors) ? safeStatus.errors : [];
    setText(this._els.status, safeInput(safeStatus.status || "unknown"));
    setText(this._els.visible, safeStatus.visible ? "visible" : "hidden");
    setText(this._els.plugin, `${safeInput(plugin.pluginId || "aerie.world")} · ${safeInput(plugin.state || "unknown")} · crashes ${Number(plugin.crashCount || 0)}`);
    setText(this._els.backend, `backend ${safeInput(backend.status || "unknown")}`);
    setText(this._els.chatPublish, safeStatus.chatPublishAvailable === false ? "unavailable" : "available");
    setText(this._els.panels, panels.length ? panels.map((item) => safeInput(item)).filter(Boolean).join(" · ") : "暂无数据");
    setText(this._els.errors, errors.length ? errors.map((item) => safeInput(item)).filter(Boolean).join(" · ") : "");
    setText(this._els.updated, formatUpdatedAt(safeStatus.updatedAt));
    setText(this._els.enabled, this._lifecycle.enabled ? "enabled" : "disabled");
    setText(this._els.desired, this._lifecycle.desired);
    setText(this._els.actual, this._lifecycle.actual);
    setText(this._els.adapter, this._lifecycle.adapter);
    setText(this._els.revision, String(this._lifecycle.revision));
    setText(this._els.runtimeHealth, safeInput(lifecycleSource.health || lifecycleSource.heartbeatStatus || "unknown"));
    setText(this._els.lastTick, formatTimestamp(lifecycleSource.lastTickAt));
    setText(this._els.lastCheckpoint, formatTimestamp(lifecycleSource.lastCheckpointAt));
    setText(this._els.runtimeError, safeInput(lifecycleSource.errorCode || ""));
    this._syncControlButtons();
  }

  _api() {
    return window.aerie && window.aerie.worldDashboard ? window.aerie.worldDashboard : null;
  }

  _startPolling() {
    if (this._pollTimer || typeof window.setInterval !== "function") return;
    this._pollTimer = window.setInterval(() => { if (this._visible) this.refresh(); }, 3000);
  }

  _stopPolling() {
    if (!this._pollTimer || typeof window.clearInterval !== "function") return;
    window.clearInterval(this._pollTimer);
    this._pollTimer = null;
  }

  _syncControlButtons() {
    const { enabled, actual } = this._lifecycle;
    setDisabled(this._els.enable, enabled);
    setDisabled(this._els.disable, !enabled);
    setDisabled(this._els.start, !enabled || ["running", "starting", "paused"].includes(actual));
    setDisabled(this._els.stop, !enabled || actual === "stopped");
    setDisabled(this._els.pause, !enabled || actual !== "running");
    setDisabled(this._els.resume, !enabled || actual !== "paused");
    setDisabled(this._els.restart, !enabled || ["starting", "stopping"].includes(actual));
  }

  _operationId(action) {
    this._operationSequence += 1;
    return `world-ui:${safeInput(action)}:${Date.now()}:${this._operationSequence}`;
  }

  async _withButton(button, fn) {
    if (button) button.disabled = true;
    try { await fn(); }
    finally {
      if (button) button.disabled = false;
      this._syncControlButtons();
    }
  }
}

function defaultLifecycle() {
  return { enabled: false, desired: "stopped", actual: "stopped", adapter: "null", revision: 0, configRevision: 0 };
}

function objectValue(value) {
  return value && typeof value === "object" ? value : {};
}

function toCamel(value) {
  return String(value).replace(/-([a-z])/g, (_match, char) => char.toUpperCase());
}

function onClick(element, handler) {
  if (!element || typeof element.addEventListener !== "function") return;
  element.addEventListener("click", (event) => {
    if (event && typeof event.preventDefault === "function") event.preventDefault();
    return handler();
  });
}

function setText(element, value) {
  if (element) element.textContent = safeInput(value, 500);
}

function setDisabled(element, value) {
  if (element) element.disabled = !!value;
}

function safeInput(value, limit = 200) {
  return String(value || "").replace(/\0/g, "").trim().slice(0, limit);
}

function formatUpdatedAt(value) {
  const numeric = Number(value || 0);
  if (!numeric) return "not refreshed";
  try { return new Date(numeric).toISOString(); }
  catch (_) { return "not refreshed"; }
}

function formatTimestamp(value) {
  const raw = safeInput(value);
  if (!raw) return "not available";
  const parsed = new Date(raw);
  return Number.isNaN(parsed.getTime()) ? raw : parsed.toISOString();
}

window.WorldDashboardPanel = WorldDashboardPanel;
