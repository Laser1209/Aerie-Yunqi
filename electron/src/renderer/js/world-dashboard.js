"use strict";

class WorldDashboardPanel {
  constructor() {
    this._visible = false;
    this._initialized = false;
    this._els = {};
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
    });
    this._renderSnapshot({});
    return Promise.resolve();
  }

  setVisible(visible) {
    this._visible = !!visible;
    if (this._visible) {
      this.refresh();
    }
  }

  async refresh() {
    const api = this._api();
    if (!api || typeof api.getStatus !== "function") {
      this._renderStatus({
        status: "unavailable",
        visible: false,
        plugin: { pluginId: "aerie.world", state: "missing_preload", crashCount: 0 },
        backend: { status: "not_checked" },
        panels: [],
        errors: ["preload_missing"],
        chatPublishAvailable: true,
      });
      return;
    }
    await this._withButton(this._els.refresh, async () => {
      try {
        this._renderStatus(await api.getStatus());
        if (typeof api.getSnapshot === "function") {
          this._renderSnapshot(await api.getSnapshot());
        } else {
          this._renderSnapshot({});
        }
      } catch (_) {
        this._renderStatus({
          status: "unavailable",
          visible: false,
          plugin: { pluginId: "aerie.world", state: "status_failed", crashCount: 0 },
          backend: { status: "unreachable" },
          panels: [],
          errors: ["status_failed"],
          chatPublishAvailable: true,
        });
        this._renderSnapshot({});
      }
    });
  }

  async show() {
    const api = this._api();
    if (!api || typeof api.show !== "function") return this.refresh();
    await this._withButton(this._els.show, async () => {
      this._renderStatus(await api.show());
    });
  }

  async hide() {
    const api = this._api();
    if (!api || typeof api.hide !== "function") return this.refresh();
    await this._withButton(this._els.hide, async () => {
      this._renderStatus(await api.hide());
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
        const draft = (result && result.draft && typeof result.draft === "object") ? result.draft : {};
        const keys = Array.isArray(draft.payloadKeys)
          ? draft.payloadKeys.map((key) => safeInput(key)).filter(Boolean)
          : [];
        setText(
          this._els.creativeResult,
          [
            safeInput(result && result.status),
            safeInput(draft.kind),
            safeInput(draft.title),
            safeInput(draft.payloadSha256),
            keys.length ? `keys: ${keys.join(", ")}` : "",
          ].filter(Boolean).join(" · ") || "preview",
        );
      } catch (_) {
        setText(this._els.creativeResult, "preview_failed");
      }
    });
  }

  _bindElements() {
    const byId = (id) => document.getElementById(id);
    this._els = {
      status: byId("world-dashboard-status"),
      visible: byId("world-dashboard-visible"),
      plugin: byId("world-dashboard-plugin"),
      backend: byId("world-dashboard-backend"),
      chatPublish: byId("world-dashboard-chat-publish"),
      panels: byId("world-dashboard-panels"),
      errors: byId("world-dashboard-errors"),
      updated: byId("world-dashboard-updated"),
      summary: byId("world-dashboard-summary"),
      relationship: byId("world-dashboard-relationship"),
      timeline: byId("world-dashboard-timeline"),
      candidates: byId("world-dashboard-candidates"),
      refresh: byId("world-dashboard-refresh"),
      show: byId("world-dashboard-show"),
      hide: byId("world-dashboard-hide"),
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
    };
  }

  _wireActions() {
    onClick(this._els.refresh, () => this.refresh());
    onClick(this._els.show, () => this.show());
    onClick(this._els.hide, () => this.hide());
    onClick(this._els.candidateApprove, () => this.approveCandidate());
    onClick(this._els.creativePreview, () => this.previewCreative());
  }

  _renderStatus(status) {
    const safeStatus = status && typeof status === "object" ? status : {};
    const plugin = safeStatus.plugin && typeof safeStatus.plugin === "object" ? safeStatus.plugin : {};
    const backend = safeStatus.backend && typeof safeStatus.backend === "object" ? safeStatus.backend : {};
    const panels = Array.isArray(safeStatus.panels) ? safeStatus.panels : [];
    const errors = Array.isArray(safeStatus.errors) ? safeStatus.errors : [];

    setText(this._els.status, safeInput(safeStatus.status || "unknown"));
    setText(this._els.visible, safeStatus.visible ? "visible" : "hidden");
    setText(
      this._els.plugin,
      `${safeInput(plugin.pluginId || "aerie.world")} · ${safeInput(plugin.state || "unknown")} · crashes ${Number(plugin.crashCount || 0)}`,
    );
    setText(this._els.backend, `backend ${safeInput(backend.status || "unknown")}`);
    setText(this._els.chatPublish, safeStatus.chatPublishAvailable === false ? "unavailable" : "available");
    setText(this._els.panels, panels.length ? panels.map((item) => safeInput(item)).filter(Boolean).join(" · ") : "暂无数据");
    setText(this._els.errors, errors.length ? errors.map((item) => safeInput(item)).filter(Boolean).join(" · ") : "");
    setText(this._els.updated, formatUpdatedAt(safeStatus.updatedAt));
  }

  _renderSnapshot(snapshot) {
    const safeSnapshot = snapshot && typeof snapshot === "object" ? snapshot : {};
    const summary = safeSnapshot.worldSummary && typeof safeSnapshot.worldSummary === "object"
      ? safeSnapshot.worldSummary
      : {};
    const relationship = safeSnapshot.relationshipState && typeof safeSnapshot.relationshipState === "object"
      ? safeSnapshot.relationshipState
      : {};
    const timeline = Array.isArray(safeSnapshot.actionTimeline) ? safeSnapshot.actionTimeline : [];
    const candidates = Array.isArray(safeSnapshot.imageCandidates) ? safeSnapshot.imageCandidates : [];

    setText(this._els.summary, compactParts([
      summary.status,
      summary.phase,
      summary.location,
      summary.activity,
    ]));
    setText(this._els.relationship, compactParts([
      relationship.persona_id || relationship.personaId,
      relationship.warmth !== undefined ? `warmth ${safeInput(relationship.warmth)}` : "",
      relationship.summary,
    ]));
    const firstEvent = timeline[0] && typeof timeline[0] === "object" ? timeline[0] : {};
    setText(this._els.timeline, compactParts([
      firstEvent.sequence,
      firstEvent.topic,
      firstEvent.eventType || firstEvent.event_type,
    ]));
    const firstCandidate = candidates[0] && typeof candidates[0] === "object" ? candidates[0] : {};
    setText(this._els.candidates, compactParts([
      firstCandidate.candidateId || firstCandidate.candidate_id,
      firstCandidate.promptKey || firstCandidate.prompt_key,
      firstCandidate.scene,
    ]));
  }

  _api() {
    return window.aerie && window.aerie.worldDashboard ? window.aerie.worldDashboard : null;
  }

  async _withButton(button, fn) {
    if (button) button.disabled = true;
    try {
      await fn();
    } finally {
      if (button) button.disabled = false;
    }
  }
}

function onClick(element, handler) {
  if (!element || typeof element.addEventListener !== "function") return;
  element.addEventListener("click", (event) => {
    if (event && typeof event.preventDefault === "function") event.preventDefault();
    return handler();
  });
}

function setText(element, value) {
  if (!element) return;
  element.textContent = safeInput(value, 500);
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
  } catch (_) {
    return {};
  }
}

function formatUpdatedAt(value) {
  const numeric = Number(value || 0);
  if (!numeric) return "not refreshed";
  try {
    return new Date(numeric).toISOString();
  } catch (_) {
    return "not refreshed";
  }
}

window.WorldDashboardPanel = WorldDashboardPanel;
