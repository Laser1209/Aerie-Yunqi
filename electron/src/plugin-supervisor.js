"use strict";

function nowDefault() {
  return Date.now();
}

function sanitizeKeys(value) {
  const source = value && typeof value === "object" ? value : {};
  return Object.keys(source).sort();
}

function createPluginSupervisor(options = {}) {
  const maxCrashes = Number.isFinite(options.maxCrashes) ? options.maxCrashes : 3;
  const now = typeof options.now === "function" ? options.now : nowDefault;
  const plugins = new Map();

  function ensure(pluginId) {
    const id = String(pluginId || "").trim() || "unknown";
    if (!plugins.has(id)) {
      plugins.set(id, {
        pluginId: id,
        state: "registered",
        command: "",
        registeredAt: now(),
        lastHeartbeatAt: 0,
        heartbeatStatus: "unknown",
        crashCount: 0,
        fusedAt: 0,
        audit: [],
      });
    }
    return plugins.get(id);
  }

  function publicStatus(record) {
    return {
      pluginId: record.pluginId,
      state: record.state,
      command: record.command,
      registeredAt: record.registeredAt,
      lastHeartbeatAt: record.lastHeartbeatAt,
      heartbeatStatus: record.heartbeatStatus,
      crashCount: record.crashCount,
      fusedAt: record.fusedAt,
      audit: record.audit.slice(-20),
    };
  }

  return {
    register(pluginId, config = {}) {
      const record = ensure(pluginId);
      record.command = String(config.command || "");
      record.state = "registered";
      record.audit.push({
        type: "registered",
        at: now(),
        configKeys: sanitizeKeys(config),
      });
      return publicStatus(record);
    },

    recordHeartbeat(pluginId, heartbeat = {}) {
      const record = ensure(pluginId);
      if (record.state !== "fused") record.state = "healthy";
      record.lastHeartbeatAt = now();
      record.heartbeatStatus = String(heartbeat.status || "unknown");
      record.audit.push({
        type: "heartbeat",
        at: record.lastHeartbeatAt,
        status: record.heartbeatStatus,
        detailKeys: sanitizeKeys(heartbeat),
      });
      return publicStatus(record);
    },

    recordCrash(pluginId, detail = {}) {
      const record = ensure(pluginId);
      record.crashCount += 1;
      record.state = record.crashCount >= maxCrashes ? "fused" : "crashed";
      if (record.state === "fused") record.fusedAt = now();
      record.audit.push({
        type: "crash",
        at: now(),
        detailKeys: sanitizeKeys(detail),
      });
      return publicStatus(record);
    },

    status(pluginId) {
      return publicStatus(ensure(pluginId));
    },
  };
}

module.exports = {
  createPluginSupervisor,
};
