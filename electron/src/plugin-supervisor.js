"use strict";

const crypto = require("crypto");
const http = require("http");
const os = require("os");
const path = require("path");
const { spawn } = require("child_process");

const WORLD_PROTOCOL = "aerie.world";
const WORLD_PROTOCOL_VERSION = "1.0";

function nowDefault() {
  return Date.now();
}

function sanitizeKeys(value) {
  const source = value && typeof value === "object" ? value : {};
  return Object.keys(source).sort();
}

function safeText(value, limit = 200) {
  return String(value || "").replace(/\0/g, "").trim().slice(0, limit);
}

function createPluginSupervisor(options = {}) {
  const maxCrashes = Number.isFinite(options.maxCrashes) ? Math.max(1, options.maxCrashes) : 3;
  const now = typeof options.now === "function" ? options.now : nowDefault;
  const spawnFn = typeof options.spawn === "function" ? options.spawn : spawn;
  const requestFn = typeof options.request === "function" ? options.request : requestJson;
  const startupTimeoutMs = finite(options.startupTimeoutMs, 10000, 100);
  const stopTimeoutMs = finite(options.stopTimeoutMs, 3000, 100);
  const heartbeatIntervalMs = finite(options.heartbeatIntervalMs, 2000, 100);
  const heartbeatFailuresBeforeRestart = finite(options.heartbeatFailuresBeforeRestart, 3, 1);
  const tokenTtlMs = finite(options.tokenTtlMs, 10 * 60 * 1000, 10 * 1000);
  const tokenRotateBeforeMs = finite(options.tokenRotateBeforeMs, 30 * 1000, 1000);
  const baseRestartDelayMs = finite(options.baseRestartDelayMs, 500, 0);
  const maxRestartDelayMs = finite(options.maxRestartDelayMs, 15000, baseRestartDelayMs);
  const plugins = new Map();

  function ensure(pluginId) {
    const id = safeText(pluginId) || "unknown";
    if (!plugins.has(id)) {
      plugins.set(id, {
        pluginId: id,
        state: "registered",
        command: "",
        args: [],
        cwd: "",
        dataDir: "",
        configEnv: {},
        registeredAt: now(),
        enabled: false,
        desired: "stopped",
        actual: "stopped",
        adapter: "null",
        revision: 0,
        sidecarRevision: 0,
        process: null,
        endpoint: "",
        token: "",
        tokenExpiresAt: 0,
        instanceId: "",
        startupEpochMs: 0,
        lastHeartbeatAt: 0,
        heartbeatStatus: "unknown",
        lastTickAt: "",
        lastCheckpointAt: "",
        lastCrashAt: 0,
        crashCount: 0,
        heartbeatFailures: 0,
        fusedAt: 0,
        errorCode: "",
        audit: [],
        idempotency: new Map(),
        heartbeatTimer: null,
        rotationTimer: null,
        restartTimer: null,
        intentionalStop: false,
        generation: 0,
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
      enabled: record.enabled,
      desired: record.desired,
      actual: record.actual,
      adapter: record.adapter,
      revision: record.revision,
      instanceId: record.instanceId,
      startupEpochMs: record.startupEpochMs,
      lastHeartbeatAt: record.lastHeartbeatAt,
      heartbeatStatus: record.heartbeatStatus,
      lastTickAt: record.lastTickAt,
      lastCheckpointAt: record.lastCheckpointAt,
      lastCrashAt: record.lastCrashAt,
      crashCount: record.crashCount,
      fusedAt: record.fusedAt,
      errorCode: record.errorCode,
      fallbackAdapter: record.adapter === "remote" ? "in_process" : "null",
      audit: record.audit.slice(-20),
    };
  }

  function audit(record, type, detail = {}) {
    record.audit.push({ type, at: now(), ...detail });
    if (record.audit.length > 100) record.audit.splice(0, record.audit.length - 100);
  }

  function clearTimer(record, key) {
    if (record[key]) clearTimeout(record[key]);
    record[key] = null;
  }

  function clearRuntimeTimers(record) {
    clearTimer(record, "heartbeatTimer");
    clearTimer(record, "rotationTimer");
    clearTimer(record, "restartTimer");
  }

  function remember(record, key, result) {
    if (!key) return;
    record.idempotency.set(key, { ...result });
    while (record.idempotency.size > 200) {
      record.idempotency.delete(record.idempotency.keys().next().value);
    }
  }

  function reject(record, errorCode) {
    return {
      accepted: false,
      rejected: true,
      desired: record.desired,
      actual: record.actual,
      enabled: record.enabled,
      revision: record.revision,
      adapter: record.adapter,
      fallbackAdapter: record.adapter === "remote" ? "in_process" : "null",
      errorCode,
      plugin: publicStatus(record),
    };
  }

  function accept(record, extra = {}) {
    return {
      accepted: true,
      rejected: false,
      desired: record.desired,
      actual: record.actual,
      enabled: record.enabled,
      revision: record.revision,
      adapter: record.adapter,
      fallbackAdapter: record.adapter === "remote" ? "in_process" : "null",
      errorCode: "",
      plugin: publicStatus(record),
      ...extra,
    };
  }

  function validateWrite(record, expectedRevision, idempotencyKey) {
    const idem = safeText(idempotencyKey);
    if (idem && record.idempotency.has(idem)) {
      return { cached: { ...record.idempotency.get(idem) }, idem };
    }
    if (expectedRevision !== undefined && expectedRevision !== null && Number(expectedRevision) !== record.revision) {
      return { error: reject(record, "revision_conflict"), idem };
    }
    return { idem };
  }

  function register(pluginId, config = {}) {
    const record = ensure(pluginId);
    record.command = safeText(config.command || process.env.AERIE_PYTHON || process.env.PYTHON || "python", 500);
    record.args = Array.isArray(config.args) ? config.args.map((item) => String(item)) : [];
    record.cwd = safeText(config.cwd || path.resolve(__dirname, "..", ".."), 1000);
    record.dataDir = safeText(config.dataDir || path.join(os.tmpdir(), "aerie-world-sidecar"), 1000);
    record.configEnv = config.env && typeof config.env === "object" ? { ...config.env } : {};
    record.state = record.state === "fused" ? "fused" : "registered";
    audit(record, "registered", { configKeys: sanitizeKeys(config) });
    return publicStatus(record);
  }

  function recordHeartbeat(pluginId, heartbeat = {}) {
    const record = ensure(pluginId);
    if (record.state !== "fused") record.state = "healthy";
    record.lastHeartbeatAt = now();
    record.heartbeatStatus = safeText(heartbeat.status || "unknown");
    if (heartbeat.actual) record.actual = safeText(heartbeat.actual);
    record.heartbeatFailures = 0;
    audit(record, "heartbeat", {
      status: record.heartbeatStatus,
      detailKeys: sanitizeKeys(heartbeat),
    });
    return publicStatus(record);
  }

  function recordCrash(pluginId, detail = {}) {
    const record = ensure(pluginId);
    record.crashCount += 1;
    record.lastCrashAt = now();
    record.state = record.crashCount >= maxCrashes ? "fused" : "crashed";
    record.actual = "degraded";
    record.adapter = "null";
    record.errorCode = record.state === "fused" ? "plugin_fused" : "plugin_crashed";
    if (record.state === "fused") record.fusedAt = now();
    audit(record, "crash", { detailKeys: sanitizeKeys(detail) });
    return publicStatus(record);
  }

  async function enable(pluginId, optionsForWrite = {}) {
    const record = ensure(pluginId);
    const checked = validateWrite(record, optionsForWrite.expectedRevision, optionsForWrite.idempotencyKey);
    if (checked.cached) return checked.cached;
    if (checked.error) return checked.error;
    if (!record.enabled) {
      record.enabled = true;
      record.revision += 1;
      record.errorCode = "";
      audit(record, "enabled");
    }
    const result = accept(record);
    remember(record, checked.idem, result);
    return result;
  }

  async function disable(pluginId, optionsForWrite = {}) {
    const record = ensure(pluginId);
    const checked = validateWrite(record, optionsForWrite.expectedRevision, optionsForWrite.idempotencyKey);
    if (checked.cached) return checked.cached;
    if (checked.error) return checked.error;
    await stopInternal(record, { preserveDesired: false });
    const changed = record.enabled || record.desired !== "stopped";
    record.enabled = false;
    record.desired = "stopped";
    record.actual = "stopped";
    record.adapter = "null";
    record.state = "disabled";
    record.errorCode = "";
    if (changed) record.revision += 1;
    audit(record, "disabled");
    const result = accept(record);
    remember(record, checked.idem, result);
    return result;
  }

  async function start(pluginId, optionsForWrite = {}) {
    const record = ensure(pluginId);
    const checked = validateWrite(record, optionsForWrite.expectedRevision, optionsForWrite.idempotencyKey);
    if (checked.cached) return checked.cached;
    if (checked.error) return checked.error;
    if (!record.enabled) return reject(record, "world_disabled");
    if (record.state === "fused") return reject(record, "plugin_fused");
    if (record.process && record.actual === "running") {
      const result = accept(record);
      remember(record, checked.idem, result);
      return result;
    }
    record.desired = "running";
    const launched = await startInternal(record);
    if (!launched.accepted) return launched;
    record.revision += 1;
    const result = accept(record);
    remember(record, checked.idem, result);
    return result;
  }

  async function stop(pluginId, optionsForWrite = {}) {
    const record = ensure(pluginId);
    const checked = validateWrite(record, optionsForWrite.expectedRevision, optionsForWrite.idempotencyKey);
    if (checked.cached) return checked.cached;
    if (checked.error) return checked.error;
    const changed = record.process || record.desired !== "stopped" || record.actual !== "stopped";
    record.desired = "stopped";
    await stopInternal(record, { preserveDesired: false });
    if (changed) record.revision += 1;
    const result = accept(record);
    remember(record, checked.idem, result);
    return result;
  }

  async function remoteControl(pluginId, action, optionsForWrite = {}) {
    const record = ensure(pluginId);
    const checked = validateWrite(record, optionsForWrite.expectedRevision, optionsForWrite.idempotencyKey);
    if (checked.cached) return checked.cached;
    if (checked.error) return checked.error;
    if (!record.enabled) return reject(record, "world_disabled");
    if (!record.process || !record.endpoint || !record.token) return reject(record, "sidecar_unavailable");
    try {
      const response = await requestFn(record, "POST", "/control", {
        action,
        expectedRevision: record.sidecarRevision,
        idempotencyKey: checked.idem,
      }, { allowStatuses: [409] });
      if (response.accepted !== true) {
        const result = reject(record, safeText(response.errorCode || "control_rejected"));
        remember(record, checked.idem, result);
        return result;
      }
      record.sidecarRevision = Number(response.revision || record.sidecarRevision);
      record.desired = safeText(response.desired || (action === "pause" ? "paused" : "running"));
      record.actual = safeText(response.actual || record.desired);
      record.state = record.actual === "paused" ? "paused" : "healthy";
      record.adapter = "remote";
      record.errorCode = "";
      record.revision += 1;
      audit(record, action);
      const result = accept(record);
      remember(record, checked.idem, result);
      return result;
    } catch (_) {
      record.errorCode = "sidecar_unavailable";
      return reject(record, record.errorCode);
    }
  }

  async function restart(pluginId, optionsForWrite = {}) {
    const record = ensure(pluginId);
    const checked = validateWrite(record, optionsForWrite.expectedRevision, optionsForWrite.idempotencyKey);
    if (checked.cached) return checked.cached;
    if (checked.error) return checked.error;
    if (!record.enabled) return reject(record, "world_disabled");
    if (record.state === "fused" && optionsForWrite.resetFuse !== true) return reject(record, "plugin_fused");
    if (optionsForWrite.resetFuse === true) {
      record.crashCount = 0;
      record.fusedAt = 0;
      record.state = "registered";
    }
    record.desired = "running";
    await stopInternal(record, { preserveDesired: true });
    const launched = await startInternal(record);
    if (!launched.accepted) return launched;
    record.revision += 1;
    audit(record, "restarted");
    const result = accept(record);
    remember(record, checked.idem, result);
    return result;
  }

  async function control(pluginId, action, optionsForWrite = {}) {
    const command = safeText(action).toLowerCase();
    if (command === "enable") return enable(pluginId, optionsForWrite);
    if (command === "disable") return disable(pluginId, optionsForWrite);
    if (command === "start") return start(pluginId, optionsForWrite);
    if (command === "stop") return stop(pluginId, optionsForWrite);
    if (command === "pause" || command === "resume") return remoteControl(pluginId, command, optionsForWrite);
    if (command === "restart") return restart(pluginId, optionsForWrite);
    return reject(ensure(pluginId), "unsupported_action");
  }

  async function startInternal(record) {
    if (!record.command) register(record.pluginId, {});
    clearRuntimeTimers(record);
    record.generation += 1;
    const generation = record.generation;
    record.intentionalStop = false;
    record.state = "starting";
    record.actual = "starting";
    record.adapter = "null";
    record.errorCode = "";
    record.token = crypto.randomBytes(32).toString("base64url");
    record.tokenExpiresAt = now() + tokenTtlMs;
    const args = record.args.length
      ? record.args.slice()
      : [
          "-m",
          "world_service.main",
          "--host",
          "127.0.0.1",
          "--port",
          "0",
          "--data-dir",
          record.dataDir,
        ];
    const childEnv = {
      ...process.env,
      ...record.configEnv,
      AERIE_WORLD_TOKEN: record.token,
      AERIE_WORLD_TOKEN_EXPIRES_AT_MS: String(record.tokenExpiresAt),
    };
    audit(record, "spawn", { command: record.command, argCount: args.length, envKeys: sanitizeKeys(record.configEnv) });

    let child;
    try {
      child = spawnFn(record.command, args, {
        cwd: record.cwd,
        env: childEnv,
        windowsHide: true,
        stdio: ["ignore", "pipe", "pipe"],
      });
    } catch (_) {
      clearSecrets(record);
      recordCrash(record.pluginId, { stage: "spawn" });
      return reject(record, "spawn_failed");
    }
    record.process = child;

    child.once("exit", (code, signal) => {
      onChildExit(record, child, generation, code, signal);
    });

    try {
      const ready = await waitForReadyLine(child, startupTimeoutMs);
      if (record.process !== child || generation !== record.generation) {
        return reject(record, "stale_startup");
      }
      record.endpoint = `http://127.0.0.1:${Number(ready.port)}`;
      const hello = await requestFn(record, "GET", "/hello", null, { timeoutMs: startupTimeoutMs });
      if (
        hello.protocol !== WORLD_PROTOCOL
        || hello.protocol_version !== WORLD_PROTOCOL_VERSION
        || !hello.instance_id
      ) {
        throw new Error("incompatible_handshake");
      }
      const state = await requestFn(record, "GET", "/state", null, { timeoutMs: startupTimeoutMs });
      record.instanceId = safeText(hello.instance_id);
      record.startupEpochMs = Number(hello.startup_epoch_ms || ready.startupEpochMs || 0);
      record.sidecarRevision = Number(state.revision || 0);
      record.actual = safeText(state.actual || state.status || "running");
      record.desired = safeText(state.desired || record.desired || "running");
      record.lastTickAt = safeText(state.last_tick_at || "");
      record.lastCheckpointAt = safeText(state.last_checkpoint_at || "");
      record.adapter = "remote";
      record.state = record.actual === "paused" ? "paused" : "healthy";
      record.heartbeatStatus = "ready";
      record.lastHeartbeatAt = now();
      record.heartbeatFailures = 0;
      record.errorCode = "";
      scheduleHeartbeat(record, generation);
      scheduleTokenRotation(record, generation);
      audit(record, "handshake", {
        protocol: hello.protocol,
        protocolVersion: hello.protocol_version,
        capabilityCount: Array.isArray(hello.capabilities) ? hello.capabilities.length : 0,
      });
      return accept(record);
    } catch (error) {
      record.errorCode = safeText(error && error.message) === "incompatible_handshake"
        ? "incompatible_protocol"
        : "startup_failed";
      record.intentionalStop = true;
      try { child.kill(); } catch (_) {}
      if (record.process === child) record.process = null;
      clearSecrets(record);
      recordCrash(record.pluginId, { stage: "handshake" });
      return reject(record, record.errorCode || "startup_failed");
    }
  }

  async function stopInternal(record, { preserveDesired }) {
    clearRuntimeTimers(record);
    const child = record.process;
    record.intentionalStop = true;
    if (record.endpoint && record.token) {
      try {
        await requestFn(record, "POST", "/shutdown", {}, { timeoutMs: Math.min(1000, stopTimeoutMs) });
      } catch (_) {}
    }
    if (child) {
      await waitForExitOrKill(child, stopTimeoutMs);
    }
    if (record.process === child) record.process = null;
    clearSecrets(record);
    record.actual = "stopped";
    record.adapter = "null";
    record.state = record.enabled ? "stopped" : "disabled";
    record.heartbeatStatus = "stopped";
    record.errorCode = "";
    if (!preserveDesired) record.desired = "stopped";
    audit(record, "stopped");
  }

  function onChildExit(record, child, generation, code, signal) {
    if (record.process !== child || generation !== record.generation) return;
    record.process = null;
    clearTimer(record, "heartbeatTimer");
    clearTimer(record, "rotationTimer");
    clearSecrets(record);
    if (record.intentionalStop || record.desired === "stopped" || !record.enabled) {
      record.actual = "stopped";
      record.adapter = "null";
      record.state = record.enabled ? "stopped" : "disabled";
      return;
    }
    recordCrash(record.pluginId, { code, signal });
    if (record.state !== "fused" && record.enabled && record.desired === "running") {
      const delay = Math.min(maxRestartDelayMs, baseRestartDelayMs * (2 ** Math.max(0, record.crashCount - 1)));
      audit(record, "restart_scheduled", { delayMs: delay });
      record.restartTimer = setTimeout(() => {
        record.restartTimer = null;
        startInternal(record).catch(() => {});
      }, delay);
      if (record.restartTimer && typeof record.restartTimer.unref === "function") record.restartTimer.unref();
    }
  }

  function scheduleHeartbeat(record, generation) {
    clearTimer(record, "heartbeatTimer");
    record.heartbeatTimer = setTimeout(async () => {
      record.heartbeatTimer = null;
      if (!record.process || record.generation !== generation) return;
      try {
        const heartbeat = await requestFn(record, "GET", "/health", null, {
          timeoutMs: Math.min(heartbeatIntervalMs, 1500),
        });
        const state = await requestFn(record, "GET", "/state", null, {
          timeoutMs: Math.min(heartbeatIntervalMs, 1500),
        });
        recordHeartbeat(record.pluginId, heartbeat);
        record.actual = safeText(state.actual || state.status || record.actual);
        record.desired = safeText(state.desired || record.desired);
        record.sidecarRevision = Number(state.revision || record.sidecarRevision);
        record.lastTickAt = safeText(state.last_tick_at || record.lastTickAt);
        record.lastCheckpointAt = safeText(state.last_checkpoint_at || record.lastCheckpointAt);
        record.adapter = "remote";
      } catch (_) {
        record.heartbeatFailures += 1;
        audit(record, "heartbeat_failed", { failureCount: record.heartbeatFailures });
        if (record.heartbeatFailures >= heartbeatFailuresBeforeRestart && record.process) {
          record.errorCode = "heartbeat_timeout";
          try { record.process.kill(); } catch (_) {}
          return;
        }
      }
      scheduleHeartbeat(record, generation);
    }, heartbeatIntervalMs);
    if (record.heartbeatTimer && typeof record.heartbeatTimer.unref === "function") record.heartbeatTimer.unref();
  }

  function scheduleTokenRotation(record, generation) {
    clearTimer(record, "rotationTimer");
    const delay = Math.max(1000, record.tokenExpiresAt - now() - tokenRotateBeforeMs);
    record.rotationTimer = setTimeout(() => {
      record.rotationTimer = null;
      if (!record.process || record.generation !== generation || record.desired !== "running") return;
      restart(record.pluginId, { expectedRevision: record.revision }).catch(() => {});
    }, delay);
    if (record.rotationTimer && typeof record.rotationTimer.unref === "function") record.rotationTimer.unref();
  }

  function clearSecrets(record) {
    record.endpoint = "";
    record.token = "";
    record.tokenExpiresAt = 0;
  }

  async function dispose() {
    for (const record of plugins.values()) {
      record.desired = "stopped";
      await stopInternal(record, { preserveDesired: false });
    }
  }

  return {
    register,
    recordHeartbeat,
    recordCrash,
    status(pluginId) {
      return publicStatus(ensure(pluginId));
    },
    enable,
    disable,
    start,
    stop,
    pause(pluginId, opts = {}) {
      return remoteControl(pluginId, "pause", opts);
    },
    resume(pluginId, opts = {}) {
      return remoteControl(pluginId, "resume", opts);
    },
    restart,
    control,
    connection(pluginId) {
      const record = ensure(pluginId);
      if (!record.endpoint || !record.token) return null;
      return {
        endpoint: record.endpoint,
        token: record.token,
        expiresAt: record.tokenExpiresAt,
        instanceId: record.instanceId,
      };
    },
    dispose,
  };
}

function finite(value, fallback, minimum) {
  return Number.isFinite(value) ? Math.max(minimum, Number(value)) : fallback;
}

function waitForReadyLine(child, timeoutMs) {
  return new Promise((resolve, reject) => {
    let buffer = "";
    let settled = false;
    const finish = (error, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.stdout && child.stdout.off("data", onData);
      child.off("error", onError);
      child.off("exit", onExit);
      if (error) reject(error); else resolve(value);
    };
    const onData = (chunk) => {
      buffer += String(chunk || "");
      if (buffer.length > 64 * 1024) return finish(new Error("startup_output_too_large"));
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || "";
      for (const line of lines) {
        try {
          const parsed = JSON.parse(line);
          if (parsed && parsed.type === "world-sidecar-ready" && Number(parsed.port) > 0) {
            return finish(null, parsed);
          }
        } catch (_) {}
      }
    };
    const onError = () => finish(new Error("spawn_failed"));
    const onExit = () => finish(new Error("sidecar_exited_before_ready"));
    const timer = setTimeout(() => finish(new Error("startup_timeout")), timeoutMs);
    child.stdout && child.stdout.on("data", onData);
    child.once("error", onError);
    child.once("exit", onExit);
  });
}

function waitForExitOrKill(child, timeoutMs) {
  return new Promise((resolve) => {
    if (!child || child.exitCode !== null || child.killed) return resolve();
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      child.off("exit", finish);
      resolve();
    };
    child.once("exit", finish);
    const timer = setTimeout(() => {
      try { child.kill(); } catch (_) {}
      setTimeout(finish, 250).unref?.();
    }, timeoutMs);
  });
}

function requestJson(record, method, requestPath, payload = null, options = {}) {
  return new Promise((resolve, reject) => {
    if (!record.endpoint || !record.token) return reject(new Error("sidecar_unavailable"));
    const target = new URL(requestPath, record.endpoint);
    if (target.protocol !== "http:" || target.hostname !== "127.0.0.1") {
      return reject(new Error("non_loopback_endpoint"));
    }
    const body = payload === null ? null : Buffer.from(JSON.stringify(payload), "utf8");
    const request = http.request({
      protocol: target.protocol,
      hostname: target.hostname,
      port: target.port,
      path: target.pathname + target.search,
      method,
      headers: {
        Authorization: `Bearer ${record.token}`,
        Accept: "application/json",
        ...(body ? { "Content-Type": "application/json", "Content-Length": body.length } : {}),
      },
      timeout: finite(options.timeoutMs, 2000, 100),
    }, (response) => {
      const chunks = [];
      let size = 0;
      response.on("data", (chunk) => {
        size += chunk.length;
        if (size <= 1024 * 1024) chunks.push(chunk);
      });
      response.on("end", () => {
        if (size > 1024 * 1024) return reject(new Error("response_too_large"));
        let parsed;
        try { parsed = JSON.parse(Buffer.concat(chunks).toString("utf8") || "{}"); }
        catch (_) { return reject(new Error("invalid_response")); }
        const allowed = Array.isArray(options.allowStatuses) ? options.allowStatuses : [];
        if ((response.statusCode || 500) >= 400 && !allowed.includes(response.statusCode)) {
          return reject(new Error(safeText(parsed.errorCode || `http_${response.statusCode}`)));
        }
        resolve(parsed && typeof parsed === "object" ? parsed : {});
      });
    });
    request.on("timeout", () => request.destroy(new Error("request_timeout")));
    request.on("error", reject);
    if (body) request.write(body);
    request.end();
  });
}

module.exports = {
  createPluginSupervisor,
};
