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
  const audit = JSON.stringify(status);
  if (status.status !== "disabled") throw new Error("expected disabled");
  if (status.visible !== false) throw new Error("expected hidden");
  if (status.chatPublishAvailable !== true) throw new Error("chat publish should stay available");
  if (status.sideEffects.apiCalled !== false) throw new Error("status should not call API when disabled");
  if (apiCalls !== 0) throw new Error("backend was called while flag off");
  if (audit.includes("secret prompt")) throw new Error("sensitive field leaked");
})().catch((err) => { console.error(err); process.exit(1); });
"""
    _run_node(script)


def test_world_dashboard_defaults_to_inprocess_capability_without_sidecar():
    script = r"""
const { createWorldDashboardHost } = require("./electron/src/world-dashboard-host");
(async () => {
  const host = createWorldDashboardHost({
    featureFlags: { isEnabled: (name) => name === "world_inprocess_v1" },
    apiRequest: async () => ({ status: 200, data: { status: "healthy" } }),
  });
  const status = await host.getStatus();
  if (status.status !== "hidden") throw new Error("in-process dashboard should be visible-capable");
  if (status.chatPublishAvailable !== true) throw new Error("chat publish should stay available");
  const effective = host.applyRuntimeSnapshot({ values: {
    world_sidecar_v1: { effectiveValue: false },
    world_inprocess_v1: { effectiveValue: true },
    world_desired: { effectiveValue: "stopped" },
  }});
  if (effective.enabled !== true) throw new Error("in-process world should enable dashboard");
  if (effective.sidecarEnabled !== false) throw new Error("sidecar should remain off");
  if (effective.inprocessEnabled !== true) throw new Error("in-process flag missing");
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


def test_main_and_preload_expose_world_dashboard_without_generic_plugin_escape():
    main = (ROOT / "electron" / "src" / "main.js").read_text(encoding="utf-8")
    preload = (ROOT / "electron" / "src" / "preload.js").read_text(encoding="utf-8")

    assert "createWorldDashboardHost" in main
    assert 'ipcMain.handle("world-dashboard:get-status"' in main
    assert "world-dashboard:raw" not in main
    assert "worldDashboard" in preload
    assert 'ipcRenderer.invoke("world-dashboard:get-status")' in preload
    assert 'ipcRenderer.invoke("api:request", opts)' in preload
