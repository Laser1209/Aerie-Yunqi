"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function loadPanel(request) {
  const sandbox = {
    window: {
      aerie: { api: { request } },
      addEventListener() {},
      dispatchEvent() {},
    },
    document: {
      getElementById() { return null; },
      querySelectorAll() { return []; },
    },
    console,
    alert() {},
    confirm() { return true; },
    CustomEvent: class CustomEvent {},
    Blob: class Blob {},
    URL: { createObjectURL() {}, revokeObjectURL() {} },
    Uint8Array,
  };
  const source = fs.readFileSync(
    path.join(__dirname, "..", "src", "renderer", "js", "persona-hub.js"),
    "utf8",
  );
  vm.runInNewContext(source, sandbox);
  return { panel: new sandbox.window.PersonaHubPanel(), sandbox };
}

test("editing a persona fetches the full hub model", async () => {
  const calls = [];
  const full = { id: "p1", basic: { name: "完整人设" } };
  const { panel } = loadPanel(async (options) => {
    calls.push(options);
    return { data: { status: "ok", persona: full } };
  });
  let filled = null;
  panel._fillForm = (persona) => { filled = persona; };
  panel._showEditor = () => {};
  panel._personas = [{ id: "p1", name: "仅摘要" }];

  await panel._editPersona("p1");

  assert.equal(calls[0].path, "/api/persona/hub/p1");
  assert.deepEqual(filled, full);
});

test("flat editor values map to the nested hub schema", () => {
  const { panel } = loadPanel(async () => ({}));

  const nested = panel._toHubModel({
    name: "伊塔",
    english_name: "Ita",
    age: 26,
    core_traits: "温柔\n主动",
    speech_style: "温柔直球",
    user_address: "宝贝",
    big_five: { extraversion: 0.8 },
    system_prompt: "自定义提示词",
  });

  assert.equal(nested.basic.name, "伊塔");
  assert.equal(nested.basic.age, 26);
  assert.equal(nested.personality.cores[0].name, "温柔");
  assert.equal(nested.personality.speech_style, "温柔直球");
  assert.deepEqual(
    JSON.parse(JSON.stringify(nested.personality.big_five)),
    { extraversion: 0.8 },
  );
  assert.deepEqual(
    Array.from(nested.relationship.user_intimate_terms),
    ["宝贝"],
  );
  assert.equal(nested.prompt_overrides.system_prompt, "自定义提示词");
});

test("save accepts the persona_id success contract", async () => {
  const { panel } = loadPanel(async () => ({
    data: { status: "ok", persona_id: "p1" },
  }));
  panel._currentId = "p1";
  panel._collectForm = () => ({ basic: { name: "伊塔" } });
  panel._loadList = async () => {};
  let returned = false;
  panel._showList = () => { returned = true; };

  await panel._saveCurrent();

  assert.equal(returned, true);
});
