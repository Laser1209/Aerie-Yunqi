"use strict";

// Renderer-only state adapter. Visuals and Live2D are intentionally separate:
// this module turns Aerie results into stable states that a future desktop pet
// or conversation panel can consume without owning business logic.

const DEFAULT_STATE = Object.freeze({
  service: "companion-studio",
  status: "unknown",
  reply: "",
  speaking: false,
  transcript: "",
});

function createCompanionStudioState(api) {
  if (!api || typeof api.health !== "function" || typeof api.talk !== "function") {
    throw new TypeError("a Companion Studio API bridge is required");
  }

  let state = { ...DEFAULT_STATE };
  const listeners = new Set();
  const publish = (patch) => {
    state = { ...state, ...patch };
    for (const listener of listeners) {
      try { listener({ ...state }); } catch (_) {}
    }
    return { ...state };
  };

  return Object.freeze({
    getState: () => ({ ...state }),
    subscribe: (listener) => {
      if (typeof listener !== "function") throw new TypeError("listener must be a function");
      listeners.add(listener);
      listener({ ...state });
      return () => listeners.delete(listener);
    },
    async refresh() {
      const result = await api.health();
      return publish({ status: result.status || "unavailable" });
    },
    async talk(text, source = "text") {
      const result = await api.talk(text, source);
      return publish({
        status: result.status || "unavailable",
        reply: typeof result.reply === "string" ? result.reply : "",
      });
    },
    setSpeaking(speaking) {
      return publish({ speaking: Boolean(speaking) });
    },
    setTranscript(transcript) {
      return publish({ transcript: typeof transcript === "string" ? transcript : "" });
    },
  });
}

function getCompanionStudioState() {
  return createCompanionStudioState(window.aerie && window.aerie.companionStudio);
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { DEFAULT_STATE, createCompanionStudioState };
}

if (typeof window !== "undefined") {
  window.aerieCompanionStudio = Object.freeze({ createCompanionStudioState, getCompanionStudioState });
}
