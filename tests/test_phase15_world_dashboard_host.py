"""Phase 15 Electron world dashboard host contracts."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _run_node(script: str) -> None:
    subprocess.run(
        ["node", "-e", script],
        cwd=str(ROOT),
        check=True,
        capture_output=True,
        text=True,
    )


def test_world_dashboard_flag_off_hides_plugin_without_side_effects():
    script = r"""
const { createWorldDashboardHost } = require("./electron/src/world-dashboard-host");
(async () => {
  let apiCalls = 0;
  const host = createWorldDashboardHost({
    featureFlags: { isEnabled: () => false },
    apiRequest: async () => { apiCalls += 1; throw new Error("should not call backend"); },
  });
  const status = await host.getStatus();
  const approval = await host.approveCandidate({
    candidateId: "cand-1",
    action: "approve",
    rawPrompt: "secret prompt",
  });
  const audit = JSON.stringify({ status, approval });
  if (status.status !== "disabled") throw new Error("expected disabled");
  if (status.visible !== false) throw new Error("expected hidden");
  if (status.chatPublishAvailable !== true) throw new Error("chat publish should stay available");
  if (status.sideEffects.apiCalled !== false) throw new Error("status should not call API when disabled");
  if (approval.status !== "disabled") throw new Error("approval should be disabled");
  if (approval.sideEffects.apiCalled !== false) throw new Error("approval should not call API");
  if (apiCalls !== 0) throw new Error("backend was called while flag off");
  if (audit.includes("secret prompt")) throw new Error("sensitive field leaked");
})().catch((err) => { console.error(err); process.exit(1); });
"""
    _run_node(script)


def test_world_dashboard_hide_preserves_chat_publish_and_plugin_health():
    script = r"""
const { createWorldDashboardHost } = require("./electron/src/world-dashboard-host");
const { createPluginSupervisor } = require("./electron/src/plugin-supervisor");
(async () => {
  const supervisor = createPluginSupervisor();
  supervisor.register("aerie.world", { command: "python", token: "secret-token" });
  supervisor.recordHeartbeat("aerie.world", { status: "ready", token: "secret-token" });
  const host = createWorldDashboardHost({
    featureFlags: { isEnabled: (name) => name === "world_sidecar_v1" },
    supervisor,
    apiRequest: async () => ({ status: 200, data: { status: "healthy" } }),
  });
  await host.show();
  await host.hide();
  const status = await host.getStatus();
  const audit = JSON.stringify(status);
  if (status.visible !== false) throw new Error("expected dashboard hidden");
  if (status.status !== "hidden") throw new Error("expected hidden status: " + status.status);
  if (status.chatPublishAvailable !== true) throw new Error("chat publish should remain available");
  if (status.plugin.state !== "healthy") throw new Error("expected healthy plugin");
  if (audit.includes("secret-token")) throw new Error("supervisor secret leaked");
})().catch((err) => { console.error(err); process.exit(1); });
"""
    _run_node(script)


def test_world_dashboard_reports_degraded_exception_state_without_leaking_values():
    script = r"""
const { createWorldDashboardHost } = require("./electron/src/world-dashboard-host");
const { createPluginSupervisor } = require("./electron/src/plugin-supervisor");
(async () => {
  const supervisor = createPluginSupervisor({ maxCrashes: 1 });
  supervisor.register("aerie.world", { token: "secret-token" });
  supervisor.recordCrash("aerie.world", { detail: "secret-crash" });
  const host = createWorldDashboardHost({
    featureFlags: { isEnabled: () => true },
    supervisor,
    apiRequest: async () => { throw new Error("backend secret unreachable"); },
  });
  await host.show();
  const status = await host.getStatus();
  const audit = JSON.stringify(status);
  if (status.status !== "degraded") throw new Error("expected degraded: " + status.status);
  if (!status.errors.includes("plugin_fused")) throw new Error("missing plugin_fused");
  if (!status.errors.includes("backend_unreachable")) throw new Error("missing backend_unreachable");
  if (audit.includes("secret-token") || audit.includes("secret-crash") || audit.includes("backend secret")) {
    throw new Error("sensitive value leaked");
  }
})().catch((err) => { console.error(err); process.exit(1); });
"""
    _run_node(script)


def test_world_dashboard_candidate_approval_uses_sanitized_backend_contract():
    script = r"""
const { createWorldDashboardHost } = require("./electron/src/world-dashboard-host");
(async () => {
  let captured = null;
  const host = createWorldDashboardHost({
    featureFlags: { isEnabled: () => true },
    apiRequest: async (opts) => {
      captured = opts;
      return { status: 200, data: { status: "queued", ack: false } };
    },
  });
  const result = await host.approveCandidate({
    candidateId: "cand-1",
    action: "approve",
    idempotencyKey: "approve-1",
    rawPrompt: "secret prompt",
  });
  const requestText = JSON.stringify(captured);
  if (result.status !== "queued") throw new Error("expected queued");
  if (result.sideEffects.apiCalled !== true) throw new Error("expected api call");
  if (captured.path !== "/api/world/candidates/approve") throw new Error("wrong path");
  if (captured.body.candidate_id !== "cand-1") throw new Error("missing candidate_id");
  if (captured.body.action !== "approve") throw new Error("missing action");
  if (captured.body.idempotency_key !== "approve-1") throw new Error("missing idempotency_key");
  if (requestText.includes("secret prompt") || requestText.includes("rawPrompt")) {
    throw new Error("raw prompt leaked into backend request");
  }
})().catch((err) => { console.error(err); process.exit(1); });
"""
    _run_node(script)


def test_world_dashboard_snapshot_uses_redacted_backend_contract():
    script = r"""
const { createWorldDashboardHost } = require("./electron/src/world-dashboard-host");
(async () => {
  let captured = null;
  const host = createWorldDashboardHost({
    featureFlags: { isEnabled: () => true },
    apiRequest: async (opts) => {
      captured = opts;
      return {
        status: 200,
        data: {
          status: "ready",
          worldSummary: {
            status: "running",
            phase: "evening",
            location: "studio",
            activity: "drawing",
            rawPrompt: "redacted-token-should-not-render",
          },
          relationshipState: { persona_id: "default", warmth: 0.73, secret: "redacted-token-should-not-render" },
          selfModel: { mood: "focused", energy: 0.62, rawThought: "redacted-token-should-not-render" },
          actionTimeline: [{ eventId: "evt-1", topic: "observations", eventType: "world.observation.recorded", sequence: 1, payload: { secret: "redacted-token-should-not-render" } }],
          imageCandidates: [{ candidateId: "cand-1", promptKey: "evening_home", rawPrompt: "redacted-token-should-not-render" }],
        },
      };
    },
  });
  const result = await host.getSnapshot();
  const audit = JSON.stringify({ result, captured });
  if (captured.path !== "/api/world/dashboard/snapshot") throw new Error("wrong path");
  if (captured.method !== "GET") throw new Error("wrong method");
  if (result.status !== "ready") throw new Error("expected ready");
  if (result.worldSummary.phase !== "evening") throw new Error("missing world summary");
  if (result.imageCandidates[0].candidateId !== "cand-1") throw new Error("missing candidate");
  if (audit.includes("redacted-token") || audit.includes("rawPrompt") || audit.includes("rawThought")) {
    throw new Error("sensitive dashboard snapshot leaked");
  }
})().catch((err) => { console.error(err); process.exit(1); });
"""
    _run_node(script)


def test_main_and_preload_expose_world_dashboard_without_generic_plugin_escape():
    main = (ROOT / "electron" / "src" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "electron" / "src" / "preload.js").read_text(encoding="utf-8")

    assert "createWorldDashboardHost" in main
    assert 'ipcMain.handle("world-dashboard:get-status"' in main
    assert 'ipcMain.handle("world-dashboard:get-snapshot"' in main
    assert 'ipcMain.handle("world-dashboard:approve-candidate"' in main
    assert "world-dashboard:raw" not in main
    assert "worldDashboard" in preload
    assert 'ipcRenderer.invoke("world-dashboard:get-status")' in preload
    assert 'ipcRenderer.invoke("world-dashboard:get-snapshot")' in preload
    assert 'ipcRenderer.invoke("world-dashboard:approve-candidate"' in preload
    assert 'ipcRenderer.invoke("api:request", opts)' in preload
