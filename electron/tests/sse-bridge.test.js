"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function extractFunction(source, name) {
  const start = source.indexOf(`function ${name}`);
  assert.notEqual(start, -1, `missing helper ${name}`);

  const braceStart = source.indexOf("{", start);
  assert.notEqual(braceStart, -1, `missing body for ${name}`);

  let depth = 0;
  for (let index = braceStart; index < source.length; index += 1) {
    const ch = source[index];
    if (ch === "{") depth += 1;
    if (ch === "}") depth -= 1;
    if (depth === 0) {
      return source.slice(start, index + 1);
    }
  }
  throw new Error(`unterminated helper ${name}`);
}

function loadSseHelpers() {
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "main.js"),
    "utf8",
  );
  const sandbox = { module: { exports: {} }, exports: {} };
  const snippet = [
    extractFunction(source, "buildSseHeaders"),
    extractFunction(source, "parseSseFrame"),
    "module.exports = { buildSseHeaders, parseSseFrame };",
  ].join("\n");
  vm.runInNewContext(snippet, sandbox);
  return sandbox.module.exports;
}

function readMainSource() {
  return fs.readFileSync(
    path.join(__dirname, "..", "src", "main.js"),
    "utf8",
  );
}

function loadForwardHelpers() {
  const source = readMainSource();
  const sandbox = { module: { exports: {} }, exports: {} };
  const snippet = [
    "const sent = [];",
    "const sseCursors = new Map();",
    "const BrowserWindow = { getAllWindows() { return [{ isDestroyed() { return false; }, webContents: { id: 77, send(_channel, payload) { sent.push(payload); } } }]; } };",
    extractFunction(source, "parseSseFrame"),
    extractFunction(source, "findWindowByWebContentsId"),
    extractFunction(source, "forwardSseFrame"),
    "module.exports = { forwardSseFrame, sent, sseCursors };",
  ].join("\n");
  vm.runInNewContext(snippet, sandbox);
  return sandbox.module.exports;
}

test("sse bridge builds Last-Event-ID header only when cursor exists", () => {
  const { buildSseHeaders } = loadSseHelpers();

  assert.deepEqual({ ...buildSseHeaders("evt_123") }, {
    Accept: "text/event-stream",
    "Last-Event-ID": "evt_123",
  });
  assert.deepEqual({ ...buildSseHeaders("") }, {
    Accept: "text/event-stream",
  });
  assert.deepEqual({ ...buildSseHeaders(null) }, {
    Accept: "text/event-stream",
  });
});

test("sse bridge parses id and data lines from a server-sent event frame", () => {
  const { parseSseFrame } = loadSseHelpers();

  const parsed = parseSseFrame(
    'id: evt_frame_1\nevent: message\ndata: {"event_id":"evt_frame_1","role":"assistant"}',
  );

  assert.equal(parsed.id, "evt_frame_1");
  assert.equal(parsed.data, '{"event_id":"evt_frame_1","role":"assistant"}');
});

test("sse bridge falls back to payload event_id and ignores heartbeats", () => {
  const { parseSseFrame } = loadSseHelpers();

  assert.equal(parseSseFrame(": heartbeat"), null);

  const parsed = parseSseFrame(
    'data: {"event_id":"evt_payload_1","role":"assistant"}',
  );

  assert.equal(parsed.id, "evt_payload_1");
  assert.equal(parsed.data, '{"event_id":"evt_payload_1","role":"assistant"}');
});

test("sse bridge stores parsed ids as reconnect cursors while forwarding payloads", () => {
  const { forwardSseFrame, sent, sseCursors } = loadForwardHelpers();

  forwardSseFrame(
    77,
    'id: evt_forward_1\ndata: {"event_id":"evt_forward_1","role":"assistant"}',
  );

  assert.equal(sseCursors.get(77), "evt_forward_1");
  assert.equal(sent[0], '{"event_id":"evt_forward_1","role":"assistant"}');
});

test("sse reconnect path builds headers from stored cursor", () => {
  assert.match(
    readMainSource(),
    /headers:\s*buildSseHeaders\(sseCursors\.get\(senderId\)\)/,
  );
});
