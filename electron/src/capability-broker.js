"use strict";

const crypto = require("crypto");

const WORLD_CAPABILITY_WHITELIST = Object.freeze([
  "world.read",
  "world.control",
  "relationship.read",
  "image.preview",
  "events.subscribe",
  "checkpoint",
  "message.candidate.publish",
]);

function uniqueStrings(values) {
  const seen = new Set();
  const result = [];
  for (const value of Array.isArray(values) ? values : []) {
    const normalized = String(value || "").trim();
    if (!normalized || seen.has(normalized)) continue;
    seen.add(normalized);
    result.push(normalized);
  }
  return result;
}

function sha256(value) {
  return crypto
    .createHash("sha256")
    .update(JSON.stringify(value))
    .digest("hex");
}

function createCapabilityBroker(options = {}) {
  const whitelist = new Set(
    uniqueStrings(options.whitelist || WORLD_CAPABILITY_WHITELIST)
  );

  return {
    negotiate(pluginId, requested, metadata = {}) {
      const plugin = String(pluginId || "").trim() || "unknown";
      const requestedUnique = uniqueStrings(requested);
      const granted = requestedUnique.filter((cap) => whitelist.has(cap));
      const denied = requestedUnique.filter((cap) => !whitelist.has(cap));
      const metadataKeys = Object.keys(metadata || {}).sort();

      return {
        pluginId: plugin,
        granted,
        denied,
        audit: {
          pluginId: plugin,
          requestedCount: requestedUnique.length,
          granted,
          denied,
          metadataKeys,
          metadataKeysSha256: sha256(metadataKeys),
          createdAt: new Date().toISOString(),
        },
      };
    },
  };
}

module.exports = {
  WORLD_CAPABILITY_WHITELIST,
  createCapabilityBroker,
};
