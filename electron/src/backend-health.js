"use strict";

const fs = require("fs");
const path = require("path");

function canonicalPathForComparison(value) {
  if (!value) return null;
  let resolved = path.resolve(String(value));
  try {
    resolved = fs.realpathSync.native(resolved);
  } catch (_) {
    try { resolved = fs.realpathSync(resolved); } catch (_) {}
  }
  resolved = path.normalize(resolved).replace(/[\\/]+$/, "");
  return process.platform === "win32" ? resolved.toLocaleLowerCase("en-US") : resolved;
}

function backendHealthMatches({
  payload,
  expectedDbPath,
  expectedInstanceId,
  legacyDbPath = null,
}) {
  const data = payload && typeof payload === "object" ? payload : {};
  const healthy = data.status === "healthy" || data.status === "degraded";
  if (!healthy) return false;

  const expected = canonicalPathForComparison(expectedDbPath);
  const advertised = canonicalPathForComparison(data.data_path_id);
  const legacy = canonicalPathForComparison(legacyDbPath);
  const isAerie = data.app === "Aerie Companion" || data.app === "Aerie · 云栖";
  const pathMatches = !expected
    || (advertised ? advertised === expected : isAerie && legacy === expected);
  if (!pathMatches) return false;

  if (!expectedInstanceId) return true;
  const advertisedInstance = String(data.backend_instance_id || "").trim();
  if (advertisedInstance) return advertisedInstance === expectedInstanceId;

  // Pre-instance-id Aerie backends are accepted only after the product and
  // legacy stats endpoint both prove that they own the expected database.
  return isAerie && Boolean(expected) && legacy === expected;
}

module.exports = {
  backendHealthMatches,
  canonicalPathForComparison,
};
