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
    this._renderSnapshot({});
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
        this._renderSnapshot(typeof api.getSnapshot === "function" ? await api.getSnapshot() : {});
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

  async approveCandidate() {
    const api = this._api();
    const payload = {
      candidateId: safeInput(this._els.candidateId && this._els.candidateId.value),
      action: safeAction(this._els.candidateAction && this._els.candidateAction.value),
      reasonCode: safeInput(this._els.candidateReason && this._els.candidateReason.value),
      idempotencyKey: safeInput(this._els.candidateIdempotency && this._els.candidateIdempotency.value),
    };
    if (!api || typeof api.approveCandidate !== "function") {
      setText(this._els.candidateResult, "disabled · preload unavailable");
      return;
    }
    await this._withButton(this._els.candidateApprove, async () => {
      try {
        const result = await api.approveCandidate(payload);
        const parts = [
          safeInput(result && result.status),
          safeInput((result && (result.candidateId || result.candidate_id)) || payload.candidateId),
        ].filter(Boolean);
        if (result && result.ack === true) parts.push("ack");
        setText(this._els.candidateResult, parts.join(" · ") || "submitted");
      } catch (_) {
        setText(this._els.candidateResult, "backend_unreachable");
      }
    });
  }

  async previewCreative() {
    const api = this._api();
    const payload = {
      kind: safeInput(this._els.creativeKind && this._els.creativeKind.value) || "world_note",
      title: safeInput(this._els.creativeTitle && this._els.creativeTitle.value),
      payload: parseJsonObject(this._els.creativePayload && this._els.creativePayload.value),
    };
    if (!api || typeof api.previewCreative !== "function") {
      setText(this._els.creativeResult, "disabled · preload unavailable");
      return;
    }
    await this._withButton(this._els.creativePreview, async () => {
      try {
        const result = await api.previewCreative(payload);
        const draft = result && result.draft && typeof result.draft === "object" ? result.draft : {};
        const keys = Array.isArray(draft.payloadKeys)
          ? draft.payloadKeys.map((key) => safeInput(key)).filter(Boolean)
          : [];
        setText(this._els.creativeResult, [
          safeInput(result && result.status),
          safeInput(draft.kind),
          safeInput(draft.title),
          safeInput(draft.payloadSha256),
          keys.length ? `keys: ${keys.join(", ")}` : "",
        ].filter(Boolean).join(" · ") || "preview");
      } catch (_) {
        setText(this._els.creativeResult, "preview_failed");
      }
    });
  }

  _bindElements() {
    const byId = (id) => document.getElementById(id);
    const ids = [
      "status", "visible", "plugin", "backend", "chat-publish", "panels", "errors", "updated",
      "summary", "relationship", "timeline", "candidates", "refresh", "show", "hide",
      "enabled", "desired", "actual", "adapter", "revision", "runtime-health", "last-tick",
      "last-checkpoint", "runtime-error", "enable", "disable", "start", "stop", "pause", "resume", "restart",
    ];
    ids.forEach((suffix) => { this._els[toCamel(suffix)] = byId(`world-dashboard-${suffix}`); });
    Object.assign(this._els, {
      candidateId: byId("world-candidate-id"),
      candidateAction: byId("world-candidate-action"),
      candidateReason: byId("world-candidate-reason"),
      candidateIdempotency: byId("world-candidate-idempotency"),
      candidateResult: byId("world-candidate-result"),
      candidateApprove: byId("world-candidate-approve"),
      creativeKind: byId("world-creative-kind"),
      creativeTitle: byId("world-creative-title"),
      creativePayload: byId("world-creative-payload"),
      creativeResult: byId("world-creative-result"),
      creativePreview: byId("world-creative-preview"),
    });
  }

  _wireActions() {
    ["refresh", "show", "hide"].forEach((action) => onClick(this._els[action], () => this[action]()));
    ["enable", "disable", "start", "stop", "pause", "resume", "restart"].forEach((action) => {
      onClick(this._els[action], () => this.control(action));
    });
    onClick(this._els.candidateApprove, () => this.approveCandidate());
    onClick(this._els.creativePreview, () => this.previewCreative());
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
    this._renderSnapshot({});
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

  _renderSnapshot(snapshot) {
    const safeSnapshot = objectValue(snapshot);
    const summary = objectValue(safeSnapshot.worldSummary);
    const relationship = objectValue(safeSnapshot.relationshipState);
    const timeline = Array.isArray(safeSnapshot.actionTimeline) ? safeSnapshot.actionTimeline : [];
    const candidates = Array.isArray(safeSnapshot.imageCandidates) ? safeSnapshot.imageCandidates : [];
    setText(this._els.summary, compactParts([summary.status, summary.phase, summary.location, summary.activity]));
    setText(this._els.relationship, compactParts([
      relationship.persona_id || relationship.personaId,
      relationship.warmth !== undefined ? `warmth ${safeInput(relationship.warmth)}` : "",
      relationship.summary,
    ]));
    const firstEvent = objectValue(timeline[0]);
    setText(this._els.timeline, compactParts([firstEvent.sequence, firstEvent.topic, firstEvent.eventType || firstEvent.event_type]));
    const firstCandidate = objectValue(candidates[0]);
    setText(this._els.candidates, compactParts([
      firstCandidate.candidateId || firstCandidate.candidate_id,
      firstCandidate.promptKey || firstCandidate.prompt_key,
      firstCandidate.scene,
    ]));
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

function compactParts(parts) {
  const rendered = (parts || []).map((part) => safeInput(part)).filter(Boolean);
  return rendered.length ? rendered.join(" · ") : "暂无数据";
}

function safeInput(value, limit = 200) {
  return String(value || "").replace(/\0/g, "").trim().slice(0, limit);
}

function safeAction(value) {
  const normalized = safeInput(value).toLowerCase();
  return ["approve", "reject", "postpone"].includes(normalized) ? normalized : "reject";
}

function parseJsonObject(value) {
  const raw = safeInput(value, 4000);
  if (!raw) return {};
  try {
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? parsed : {};
  } catch (_) { return {}; }
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
