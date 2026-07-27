"use strict";

const crypto = require("crypto");

const WORLD_PLUGIN_ID = "aerie.world";
const WORLD_SIDECAR_FLAG = "world_sidecar_v1";

function createEnvFeatureFlags(env = process.env) {
  return {
    isEnabled(name) {
      const raw = env["AERIE_FEATURE_" + String(name || "").toUpperCase()];
      return ["1", "true", "yes", "on"].includes(String(raw || "").trim().toLowerCase());
    },
  };
}

function createWorldDashboardHost({
  featureFlags = createEnvFeatureFlags(),
  apiRequest = null,
  supervisor = null,
  pluginId = WORLD_PLUGIN_ID,
  now = () => Date.now(),
} = {}) {
  let visible = false;
  let runtimeEnabledOverride = null;
  let runtimeConfigRevision = 0;

  function isEnabled() {
    if (typeof runtimeEnabledOverride === "boolean") return runtimeEnabledOverride;
    try {
      return !!(featureFlags && featureFlags.isEnabled && featureFlags.isEnabled(WORLD_SIDECAR_FLAG));
    } catch (_) {
      return false;
    }
  }

  function publicPluginStatus() {
    try {
      if (supervisor && typeof supervisor.status === "function") {
        const status = supervisor.status(pluginId) || {};
        return {
          pluginId: String(status.pluginId || pluginId),
          state: String(status.state || "unknown"),
          crashCount: Number(status.crashCount || 0),
          lastHeartbeatAt: Number(status.lastHeartbeatAt || 0),
          lastCrashAt: Number(status.lastCrashAt || 0),
          configKeys: Array.isArray(status.configKeys) ? status.configKeys.map(String) : [],
          lastHeartbeatKeys: Array.isArray(status.lastHeartbeatKeys)
            ? status.lastHeartbeatKeys.map(String)
            : [],
          lastCrashKeys: Array.isArray(status.lastCrashKeys)
            ? status.lastCrashKeys.map(String)
            : [],
          enabled: status.enabled === true,
          desired: String(status.desired || "stopped"),
          actual: String(status.actual || "stopped"),
          adapter: String(status.adapter || "null"),
          revision: Number(status.revision || 0),
          instanceId: String(status.instanceId || ""),
          startupEpochMs: Number(status.startupEpochMs || 0),
          heartbeatStatus: String(status.heartbeatStatus || "unknown"),
          lastTickAt: String(status.lastTickAt || ""),
          lastCheckpointAt: String(status.lastCheckpointAt || ""),
          errorCode: String(status.errorCode || ""),
          fallbackAdapter: String(status.fallbackAdapter || "null"),
        };
      }
    } catch (_) {}
    return {
      pluginId: String(pluginId),
      state: "unknown",
      crashCount: 0,
      lastHeartbeatAt: 0,
      lastCrashAt: 0,
      configKeys: [],
      lastHeartbeatKeys: [],
      lastCrashKeys: [],
      enabled: false,
      desired: "stopped",
      actual: "stopped",
      adapter: "null",
      revision: 0,
      instanceId: "",
      startupEpochMs: 0,
      heartbeatStatus: "unknown",
      lastTickAt: "",
      lastCheckpointAt: "",
      errorCode: "",
      fallbackAdapter: "null",
    };
  }

  async function readBackendHealth(sideEffects, errors) {
    if (typeof apiRequest !== "function") {
      return { status: "unknown" };
    }
    sideEffects.apiCalled = true;
    try {
      const response = await apiRequest({ method: "GET", path: "/api/health" });
      const data = response && response.data && typeof response.data === "object"
        ? response.data
        : {};
      return {
        status: String(data.status || "unknown"),
        ready: data.status === "healthy" || data.status === "degraded",
      };
    } catch (_) {
      errors.push("backend_unreachable");
      return { status: "unreachable", ready: false };
    }
  }

  async function getStatus() {
    // A disabled plugin is a hard no-side-effect boundary. Runtime state is
    // applied by the main-process reconciler and by explicit lifecycle actions.
    if (isEnabled()) await refreshRuntimeConfig();
    const sideEffects = { apiCalled: false };
    if (!isEnabled()) {
      visible = false;
      return {
        status: "disabled",
        visible: false,
        plugin: {
          pluginId: String(pluginId),
          state: "hidden",
          crashCount: 0,
          configKeys: [],
          lastHeartbeatKeys: [],
          lastCrashKeys: [],
        },
        backend: { status: "not_checked" },
        panels: [],
        errors: [],
        chatPublishAvailable: true,
        lifecycle: {
          enabled: false,
          desired: "stopped",
          actual: "stopped",
          adapter: "null",
          revision: 0,
          configRevision: runtimeConfigRevision,
          health: "disabled",
          lastTickAt: "",
          lastCheckpointAt: "",
          errorCode: "",
        },
        sideEffects,
        updatedAt: now(),
      };
    }

    const errors = [];
    const plugin = publicPluginStatus();
    if (plugin.state === "fused") {
      errors.push("plugin_fused");
    }
    if (plugin.errorCode && !errors.includes(plugin.errorCode)) {
      errors.push(plugin.errorCode);
    }
    const backend = await readBackendHealth(sideEffects, errors);
    const status = errors.length > 0 ? "degraded" : (visible ? "ready" : "hidden");
    return {
      status,
      visible,
      plugin,
      backend,
      panels: [
        "world_summary",
        "relationship_state",
        "action_timeline",
        "image_candidates",
        "plugin_health",
        "creative_workshop",
        "release_status",
      ],
      errors,
      chatPublishAvailable: true,
      lifecycle: {
        enabled: isEnabled(),
        desired: plugin.desired,
        actual: plugin.actual,
        adapter: plugin.adapter,
        revision: plugin.revision,
        configRevision: runtimeConfigRevision,
        health: plugin.heartbeatStatus,
        lastTickAt: plugin.lastTickAt,
        lastCheckpointAt: plugin.lastCheckpointAt,
        errorCode: plugin.errorCode,
        fallbackAdapter: plugin.fallbackAdapter,
      },
      sideEffects,
      updatedAt: now(),
    };
  }

  async function getSnapshot() {
    if (!isEnabled()) {
      return sanitizedSnapshot({
        status: "disabled",
        worldSummary: {},
        relationshipState: {},
        selfModel: {},
        actionTimeline: [],
        imageCandidates: [],
      }, { apiCalled: false });
    }
    const sideEffects = { apiCalled: false };
    if (typeof apiRequest !== "function") {
      return sanitizedSnapshot({
        status: "backend_unavailable",
        worldSummary: {},
        relationshipState: {},
        selfModel: {},
        actionTimeline: [],
        imageCandidates: [],
      }, sideEffects);
    }
    sideEffects.apiCalled = true;
    try {
      const response = await apiRequest({
        method: "GET",
        path: "/api/world/dashboard/snapshot",
      });
      const data = response && response.data && typeof response.data === "object"
        ? response.data
        : {};
      return sanitizedSnapshot(data, sideEffects);
    } catch (_) {
      return sanitizedSnapshot({
        status: "backend_unreachable",
        worldSummary: {},
        relationshipState: {},
        selfModel: {},
        actionTimeline: [],
        imageCandidates: [],
      }, sideEffects);
    }
  }

  async function show() {
    if (isEnabled()) visible = true;
    return getStatus();
  }

  async function hide() {
    visible = false;
    return getStatus();
  }

  function applyRuntimeSnapshot(snapshot = {}) {
    const source = snapshot && typeof snapshot === "object" ? snapshot : {};
    const values = source.values && typeof source.values === "object"
      ? source.values
      : {};
    const sidecar = values.world_sidecar_v1;
    if (sidecar && typeof sidecar === "object") {
      runtimeEnabledOverride = sidecar.effectiveValue === true;
    }
    runtimeConfigRevision = Number(source.revision || runtimeConfigRevision || 0);
    return {
      enabled: isEnabled(),
      revision: runtimeConfigRevision,
      desired: safeText(
        values.world_desired && values.world_desired.effectiveValue || "stopped",
      ),
    };
  }

  async function refreshRuntimeConfig() {
    if (typeof apiRequest !== "function") return null;
    try {
      const response = await apiRequest({ method: "GET", path: "/api/runtime/snapshot" });
      const data = response && response.data && typeof response.data === "object"
        ? response.data
        : {};
      return applyRuntimeSnapshot(data);
    } catch (_) {
      return null;
    }
  }

  async function control(action, input = {}) {
    const command = safeText(action || input.action || "").toLowerCase();
    const allowed = ["enable", "disable", "start", "stop", "pause", "resume", "restart"];
    if (!allowed.includes(command)) {
      return controlResult(false, "unsupported_action", publicPluginStatus());
    }
    if (!supervisor || typeof supervisor.control !== "function") {
      return controlResult(false, "supervisor_unavailable", publicPluginStatus());
    }

    const idempotencyKey = safeText(input.idempotencyKey || input.idempotency_key || "");
    const expectedRevision = finiteRevision(input.expectedRevision ?? input.expected_revision);
    const configExpectedRevision = finiteRevision(
      input.configExpectedRevision ?? input.config_expected_revision ?? runtimeConfigRevision
    );

    if (command === "enable") {
      const persisted = await persistRuntimeEnabled(true, configExpectedRevision);
      if (!persisted.accepted) return persisted;
      runtimeEnabledOverride = true;
    }

    let plugin = publicPluginStatus();
    let supervisorExpected = expectedRevision;
    if (command === "start" && isEnabled() && plugin.enabled !== true) {
      const enabled = await supervisor.control(pluginId, "enable", {
        expectedRevision: supervisorExpected,
        idempotencyKey: idempotencyKey ? `${idempotencyKey}:enable` : "",
      });
      if (!enabled || enabled.accepted !== true) return sanitizeControlResult(enabled, plugin);
      plugin = publicPluginStatus();
      supervisorExpected = plugin.revision;
    }

    const result = await supervisor.control(pluginId, command, {
      expectedRevision: supervisorExpected,
      idempotencyKey,
      resetFuse: input.resetFuse === true,
    });
    const sanitized = sanitizeControlResult(result, publicPluginStatus());
    if (sanitized.accepted && !["enable", "disable"].includes(command)) {
      const desired = {
        start: "running",
        stop: "stopped",
        pause: "paused",
        resume: "running",
        restart: "running",
      }[command];
      const persisted = await persistRuntimeChanges(
        { world_desired: desired },
        runtimeConfigRevision,
      );
      if (!persisted.accepted) return { ...sanitized, ...persisted };
    }
    if (command === "disable" && sanitized.accepted) {
      const persisted = await persistRuntimeEnabled(false, configExpectedRevision);
      if (!persisted.accepted) return persisted;
      runtimeEnabledOverride = false;
    }
    return sanitized;
  }

  async function persistRuntimeEnabled(enabled, expectedRevision) {
    const changes = enabled
      ? {
          runtime_control_v1: true,
          world_sidecar_v1: true,
          world_process_supervision_v1: true,
          world_dashboard_control_v1: true,
          world_runtime_loop_v1: true,
          world_desired: "stopped",
        }
      : {
          world_dashboard_control_v1: false,
          world_runtime_loop_v1: false,
          world_process_supervision_v1: false,
          world_sidecar_v1: false,
          world_desired: "stopped",
        };
    return persistRuntimeChanges(changes, expectedRevision);
  }

  async function persistRuntimeChanges(changes, expectedRevision) {
    if (typeof apiRequest !== "function") {
      return controlResult(false, "runtime_config_unavailable", publicPluginStatus());
    }
    try {
      const response = await apiRequest({
        method: "PATCH",
        path: "/api/runtime/config",
        body: {
          changes,
          expected_revision: Number(expectedRevision || 0),
        },
      });
      const data = response && response.data && typeof response.data === "object"
        ? response.data
        : {};
      if (data.accepted === false || data.errorCode || data.error_code) {
        return controlResult(
          false,
          safeText(data.errorCode || data.error_code || "runtime_config_rejected"),
          publicPluginStatus(),
        );
      }
      runtimeConfigRevision = Number(data.revision || runtimeConfigRevision || 0);
      return { accepted: true };
    } catch (_) {
      return controlResult(false, "runtime_config_unavailable", publicPluginStatus());
    }
  }

  async function approveCandidate(input = {}) {
    if (!isEnabled()) {
      return {
        status: "disabled",
        candidateId: safeText(input.candidateId || input.candidate_id || ""),
        sideEffects: { apiCalled: false },
      };
    }
    const sideEffects = { apiCalled: false };
    const body = sanitizeCandidateApproval(input);
    if (typeof apiRequest !== "function") {
      return {
        status: "backend_unavailable",
        candidateId: body.candidate_id,
        sideEffects,
      };
    }
    sideEffects.apiCalled = true;
    try {
      const response = await apiRequest({
        method: "POST",
        path: "/api/world/candidates/approve",
        body,
      });
      const data = response && response.data && typeof response.data === "object"
        ? response.data
        : {};
      return {
        status: String(data.status || "submitted"),
        candidateId: body.candidate_id,
        ack: data.ack === true,
        sideEffects,
      };
    } catch (_) {
      return {
        status: "backend_unreachable",
        candidateId: body.candidate_id,
        sideEffects,
      };
    }
  }

  async function previewCreative(input = {}) {
    if (!isEnabled()) {
      return { status: "disabled", sideEffects: { apiCalled: false } };
    }
    const payload = input && typeof input === "object" ? input : {};
    const keys = Object.keys(payload).sort();
    return {
      status: "preview",
      draft: {
        kind: safeText(payload.kind || "world_note"),
        title: safeText(payload.title || ""),
        payloadKeys: keys,
        payloadSha256: stableDigest(payload),
      },
      sideEffects: { apiCalled: false },
    };
  }

  return {
    getStatus,
    getSnapshot,
    show,
    hide,
    control,
    applyRuntimeSnapshot,
    refreshRuntimeConfig,
    enable: (input) => control("enable", input),
    disable: (input) => control("disable", input),
    start: (input) => control("start", input),
    stop: (input) => control("stop", input),
    pause: (input) => control("pause", input),
    resume: (input) => control("resume", input),
    restart: (input) => control("restart", input),
    approveCandidate,
    previewCreative,
  };
}

function finiteRevision(value) {
  if (value === undefined || value === null || value === "") return undefined;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 0 ? parsed : undefined;
}

function controlResult(accepted, errorCode, plugin) {
  const status = plugin && typeof plugin === "object" ? plugin : {};
  return {
    accepted: accepted === true,
    rejected: accepted !== true,
    enabled: status.enabled === true,
    desired: String(status.desired || "stopped"),
    actual: String(status.actual || "stopped"),
    adapter: String(status.adapter || "null"),
    revision: Number(status.revision || 0),
    fallbackAdapter: String(status.fallbackAdapter || "null"),
    errorCode: safeText(errorCode || ""),
  };
}

function sanitizeControlResult(result, fallbackPlugin) {
  const source = result && typeof result === "object" ? result : {};
  const plugin = source.plugin && typeof source.plugin === "object"
    ? source.plugin
    : fallbackPlugin;
  const base = controlResult(source.accepted === true, source.errorCode || "", plugin);
  return {
    ...base,
    enabled: source.enabled === true || (source.enabled === undefined && base.enabled),
    desired: String(source.desired || base.desired),
    actual: String(source.actual || base.actual),
    adapter: String(source.adapter || base.adapter),
    revision: Number(source.revision || base.revision || 0),
    fallbackAdapter: String(source.fallbackAdapter || base.fallbackAdapter),
  };
}

function sanitizeCandidateApproval(input = {}) {
  const action = safeText(input.action || "approve").toLowerCase();
  const allowedAction = ["approve", "reject", "postpone"].includes(action)
    ? action
    : "reject";
  return {
    candidate_id: safeText(input.candidateId || input.candidate_id || ""),
    action: allowedAction,
    idempotency_key: safeText(
      input.idempotencyKey || input.idempotency_key || input.candidateId || input.candidate_id || ""
    ),
    reason_code: safeText(input.reasonCode || input.reason_code || ""),
  };
}

function stableDigest(value) {
  return crypto
    .createHash("sha256")
    .update(JSON.stringify(sortJson(value)))
    .digest("hex");
}

function sanitizedSnapshot(data = {}, sideEffects = { apiCalled: false }) {
  const snapshot = data && typeof data === "object" ? data : {};
  const result = {
    status: safeText(snapshot.status || "unknown"),
    worldSummary: pickPublic(snapshot.worldSummary || snapshot.world_summary, [
      ["status", "status"],
      ["source", "source"],
      ["instanceId", "instanceId", "instance_id"],
      ["protocol", "protocol"],
      ["protocolVersion", "protocolVersion", "protocol_version"],
      ["phase", "phase"],
      ["location", "location"],
      ["activity", "activity"],
      ["sequence", "sequence"],
      ["revision", "revision"],
      ["paused", "paused"],
      ["generatedAt", "generatedAt", "generated_at"],
      ["capabilities", "capabilities"],
    ]),
    relationshipState: pickPublic(snapshot.relationshipState || snapshot.relationship_state, [
      ["user_id", "user_id", "userId"],
      ["persona_id", "persona_id", "personaId"],
      ["warmth", "warmth"],
      ["trust", "trust"],
      ["affinity", "affinity"],
      ["tension", "tension"],
      ["familiarity", "familiarity"],
      ["conflict", "conflict"],
      ["closeness", "closeness"],
      ["summary", "summary"],
      ["updated_at", "updated_at", "updatedAt"],
    ]),
    selfModel: pickPublic(snapshot.selfModel || snapshot.self_model, [
      ["mood", "mood"],
      ["energy", "energy"],
      ["focus", "focus"],
      ["stability", "stability"],
      ["summary", "summary"],
      ["updated_at", "updated_at", "updatedAt"],
    ]),
    actionTimeline: publicList(snapshot.actionTimeline || snapshot.action_timeline, [
      ["eventId", "eventId", "event_id"],
      ["topic", "topic"],
      ["eventType", "eventType", "event_type"],
      ["sequence", "sequence"],
      ["occurredAt", "occurredAt", "occurred_at"],
      ["payloadKeys", "payloadKeys", "payload_keys"],
      ["payloadSha256", "payloadSha256", "payload_sha256"],
    ]),
    imageCandidates: publicList(snapshot.imageCandidates || snapshot.image_candidates, [
      ["candidateId", "candidateId", "candidate_id"],
      ["idempotencyKey", "idempotencyKey", "idempotency_key"],
      ["scene", "scene"],
      ["ownerId", "ownerId", "owner_id"],
      ["channel", "channel"],
      ["target", "target"],
      ["promptKey", "promptKey", "prompt_key"],
      ["reasonCode", "reasonCode", "reason_code"],
      ["source", "source"],
      ["score", "score"],
      ["expiresAt", "expiresAt", "expires_at"],
      ["createdAt", "createdAt", "created_at"],
      ["sequence", "sequence"],
      ["eventId", "eventId", "event_id"],
      ["payloadKeys", "payloadKeys", "payload_keys"],
      ["sensitiveKeys", "sensitiveKeys", "sensitive_keys"],
      ["sensitiveSha256", "sensitiveSha256", "sensitive_sha256"],
    ]),
    sideEffects: { apiCalled: !!sideEffects.apiCalled },
  };
  const updatedAt = publicScalar(snapshot.updatedAt || snapshot.updated_at);
  if (updatedAt !== "") result.updatedAt = updatedAt;
  return result;
}

function publicList(value, fields) {
  const rows = Array.isArray(value) ? value : [];
  return rows.slice(0, 25)
    .filter((item) => item && typeof item === "object")
    .map((item) => pickPublic(item, fields));
}

function pickPublic(value, fields) {
  const source = value && typeof value === "object" ? value : {};
  const result = {};
  fields.forEach(([outputKey, ...inputKeys]) => {
    const raw = firstValue(source, inputKeys);
    const publicValue = publicScalar(raw);
    if (publicValue !== "" && !(Array.isArray(publicValue) && publicValue.length === 0)) {
      result[outputKey] = publicValue;
    }
  });
  return result;
}

function firstValue(source, keys) {
  for (const key of keys) {
    if (Object.prototype.hasOwnProperty.call(source, key)) return source[key];
  }
  return "";
}

function publicScalar(value) {
  if (typeof value === "boolean" || typeof value === "number") return value;
  if (Array.isArray(value)) return value.slice(0, 25).map((item) => safeText(item, 120));
  return safeText(value);
}

function sortJson(value) {
  if (Array.isArray(value)) return value.map(sortJson);
  if (value && typeof value === "object") {
    return Object.keys(value).sort().reduce((acc, key) => {
      acc[key] = sortJson(value[key]);
      return acc;
    }, {});
  }
  return value;
}

function safeText(value, limit = 200) {
  return String(value || "").replace(/\0/g, "").trim().slice(0, limit);
}

module.exports = {
  createEnvFeatureFlags,
  createWorldDashboardHost,
};
