"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const contract = require(path.join(__dirname, "..", "src", "companion-studio-contract.js"));
const renderer = require(path.join(__dirname, "..", "src", "renderer", "js", "companion-studio-bridge.js"));

test("Companion Studio contract only calls Aerie integration paths", async () => {
  const calls = [];
  const api = contract.createCompanionStudioApi(async (opts) => {
    calls.push(opts);
    return { status: 200, data: { ok: true, status: "healthy", reply: "ready" } };
  });

  await api.health();
  await api.talk("hello");
  await api.speak("hello", false);
  await api.asr("base64", "wav");

  assert.deepEqual(calls.map(({ method, path: requestPath }) => ({ method, path: requestPath })), [
    { method: "GET", path: contract.PATHS.health },
    { method: "POST", path: contract.PATHS.talk },
    { method: "POST", path: contract.PATHS.speak },
    { method: "POST", path: contract.PATHS.asr },
  ]);
  assert.equal(calls[1].body.text, "hello");
  assert.equal(calls[2].body.echo, false);
});

test("Companion Studio contract validates input and normalizes backend errors", async () => {
  const api = contract.createCompanionStudioApi(async () => ({ status: 0, data: { error: "offline" } }));
  assert.throws(() => api.talk(""), /text must be a non-empty string/);
  assert.throws(() => api.speak("hello", "false"), /echo must be a boolean/);
  assert.deepEqual(await api.health(), { ok: false, status: "unavailable", error: "offline" });
});

test("Renderer state adapter exposes health, talk and speaking state", async () => {
  const api = {
    health: async () => ({ ok: true, status: "healthy" }),
    talk: async () => ({ ok: true, status: "healthy", reply: "hello" }),
  };
  const state = renderer.createCompanionStudioState(api);
  const seen = [];
  const unsubscribe = state.subscribe((value) => seen.push(value));
  await state.refresh();
  await state.talk("hi");
  state.setSpeaking(true);
  unsubscribe();
  assert.equal(state.getState().reply, "hello");
  assert.equal(state.getState().speaking, true);
  assert.ok(seen.length >= 4);
});

test("main renderer loads the Companion Studio bridge without a second service", () => {
  const html = fs.readFileSync(path.join(__dirname, "..", "src", "renderer", "index.html"), "utf8");
  assert.match(html, /js\/companion-studio-bridge\.js/);
  assert.doesNotMatch(html, /127\.0\.0\.1:8899/);
});
