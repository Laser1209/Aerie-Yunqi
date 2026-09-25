"use strict";

// Shared by the Electron preload and Renderer integration tests. The module
// deliberately exposes only the four Aerie-owned Companion Studio contracts;
// callers cannot supply an arbitrary URL or IPC channel.

const PATHS = Object.freeze({
  health: "/api/integrations/companion-studio",
  talk: "/api/integrations/companion-studio/talk",
  speak: "/api/integrations/companion-studio/speak",
  asr: "/api/integrations/companion-studio/asr",
});

function ensureText(value, field) {
  if (typeof value !== "string" || value.trim() === "") {
    throw new TypeError(`${field} must be a non-empty string`);
  }
  return value;
}

function normalizeResult(result) {
  if (!result || typeof result !== "object") {
    return { ok: false, status: "unavailable", reason: "invalid_response" };
  }
  const body = result.data && typeof result.data === "object"
    ? result.data
    : result;
  return {
    ...body,
    ok: body.ok === true,
    status: typeof body.status === "string" ? body.status : "unavailable",
  };
}

function createCompanionStudioApi(request) {
  if (typeof request !== "function") {
    throw new TypeError("request must be a function");
  }

  const call = (method, path, body) => request({
    method,
    path,
    ...(body === undefined ? {} : { body }),
  }).then(normalizeResult);

  return Object.freeze({
    health: () => call("GET", PATHS.health),
    talk: (text, source = "text") => call("POST", PATHS.talk, {
      text: ensureText(text, "text"),
      source: ensureText(source, "source"),
    }),
    speak: (text, echo) => {
      const body = { text: ensureText(text, "text") };
      if (echo !== undefined) {
        if (typeof echo !== "boolean") throw new TypeError("echo must be a boolean");
        body.echo = echo;
      }
      return call("POST", PATHS.speak, body);
    },
    asr: (audioBase64, audioFormat = "wav") => call("POST", PATHS.asr, {
      audioBase64: ensureText(audioBase64, "audioBase64"),
      format: ensureText(audioFormat, "audioFormat"),
    }),
  });
}

module.exports = { PATHS, createCompanionStudioApi, normalizeResult };
