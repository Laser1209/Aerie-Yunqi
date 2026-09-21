// 中转网关的离线测试。
//
// 用真实 worker.js 代码跑，只把「外部世界」桩掉：
//   - Durable Object 用真 RelayGate 类 + Map 版 storage（保留全部计数逻辑）
//   - 上游 fetch 换成本地桩，记录被请求的 URL，不发真实网络请求
// 这样能验证限流/配额/版本绑定的真实行为，而不是验证桩的行为。

import { test } from "node:test";
import assert from "node:assert/strict";

import worker, { RelayGate } from "./worker.js";

const TOKEN = "aerie-test-token";

/**
 * 造一个环境：真 RelayGate 实例 + 可观测的 storage。
 *
 * 默认给一个上游 Key：本文件绝大多数用例关心的是「闸门放不放行」，
 * 若不给 Key 会先撞上 500「上游未配置」，掩盖真正的断言目标。
 */
function makeEnv(vars = {}) {
  const storage = new Map();
  const env = { RELAY_TOKEN: TOKEN, DASHSCOPE_KEY: "real-dashscope-key", ...vars };

  const gate = new RelayGate(
    {
      storage: {
        async get(key) {
          return storage.get(key);
        },
        async put(key, value) {
          storage.set(key, value);
        },
      },
    },
    env,
  );

  env.RELAY_GATE = {
    idFromName: (name) => name,
    get: () => ({
      fetch: (url, init) => gate.fetch(new Request(url, init)),
    }),
  };

  return { env, storage };
}

/** 桩掉上游 fetch，返回被请求的 URL 列表。 */
function stubUpstream(behavior) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url, init) => {
    calls.push({ url: String(url), init });
    if (behavior) return behavior(String(url), init);
    return new Response(JSON.stringify({ ok: true }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  };
  return { calls, restore: () => (globalThis.fetch = original) };
}

function relayRequest(path = "/chat/completions", { token = TOKEN, version, ip } = {}) {
  const headers = new Headers({ "content-type": "application/json" });
  if (token !== null) headers.set("Authorization", `Bearer ${token}`);
  if (version !== undefined) headers.set("X-Aerie-Version", version);
  if (ip !== undefined) headers.set("CF-Connecting-IP", ip);
  return new Request(`https://api.etta.top${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify({ model: "x", messages: [] }),
  });
}

// ── 存活探测 ──────────────────────────────────────────────

test("health 无需门卡", async () => {
  const { env } = makeEnv();
  const res = await worker.fetch(new Request("https://api.etta.top/health"), env);
  assert.equal(res.status, 200);
  assert.equal(await res.text(), "ok");
});

// ── 门卡校验 ──────────────────────────────────────────────

test("门卡错误返回 401", async () => {
  const { env } = makeEnv();
  const res = await worker.fetch(relayRequest("/x", { token: "wrong" }), env);
  assert.equal(res.status, 401);
  assert.equal((await res.json()).error, "unauthorized");
});

test("RELAY_TOKEN 未配置时一律拒绝（不给空 Bearer 开门）", async () => {
  const { env } = makeEnv();
  delete env.RELAY_TOKEN;
  const res = await worker.fetch(relayRequest("/x", { token: null }), env);
  assert.equal(res.status, 401);
});

// ── 版本绑定 ──────────────────────────────────────────────

test("ALLOWED_VERSIONS 为空时不校验版本（灰度期默认放行）", async () => {
  const { env } = makeEnv();
  const stub = stubUpstream();
  try {
    const res = await worker.fetch(relayRequest("/x"), env);
    assert.equal(res.status, 200);
  } finally {
    stub.restore();
  }
});

test("版本不在允许列表时返回 426 并带上上报值", async () => {
  const { env } = makeEnv({ ALLOWED_VERSIONS: "0.3.2-beta.0904-A12" });
  const res = await worker.fetch(relayRequest("/x", { version: "0.0.1-ancient" }), env);
  assert.equal(res.status, 426);
  const body = await res.json();
  assert.equal(body.error, "client_version_rejected");
  assert.match(body.detail, /0\.0\.1-ancient/);
});

test("缺少版本头且列表非空时返回 426", async () => {
  const { env } = makeEnv({ ALLOWED_VERSIONS: "0.3.2" });
  const res = await worker.fetch(relayRequest("/x"), env);
  assert.equal(res.status, 426);
  assert.match((await res.json()).detail, /missing/);
});

test("版本前缀命中即放行，且可配多个", async () => {
  const { env } = makeEnv({ ALLOWED_VERSIONS: "0.3.1, 0.3.2" });
  const stub = stubUpstream();
  try {
    const res = await worker.fetch(relayRequest("/x", { version: "0.3.2-beta.0904-A12" }), env);
    assert.equal(res.status, 200);
  } finally {
    stub.restore();
  }
});

// ── 限流与配额 ────────────────────────────────────────────

test("单 IP 分钟限流：超限返回 429 且带 retry-after", async () => {
  const { env } = makeEnv({ RATE_PER_MINUTE: "2" });
  const stub = stubUpstream();
  try {
    const first = await worker.fetch(relayRequest("/x", { ip: "1.1.1.1" }), env);
    const second = await worker.fetch(relayRequest("/x", { ip: "1.1.1.1" }), env);
    const third = await worker.fetch(relayRequest("/x", { ip: "1.1.1.1" }), env);

    assert.equal(first.status, 200);
    assert.equal(second.status, 200);
    assert.equal(third.status, 429);

    const body = await third.json();
    assert.equal(body.reason, "ip_rate_limit");
    assert.ok(Number(third.headers.get("retry-after")) >= 1);
  } finally {
    stub.restore();
  }
});

test("分钟限流按 IP 隔离：另一个 IP 不受影响", async () => {
  const { env } = makeEnv({ RATE_PER_MINUTE: "1" });
  const stub = stubUpstream();
  try {
    assert.equal((await worker.fetch(relayRequest("/x", { ip: "1.1.1.1" }), env)).status, 200);
    assert.equal((await worker.fetch(relayRequest("/x", { ip: "1.1.1.1" }), env)).status, 429);
    assert.equal((await worker.fetch(relayRequest("/x", { ip: "2.2.2.2" }), env)).status, 200);
  } finally {
    stub.restore();
  }
});

test("单 IP 日配额：超限返回 ip_daily_quota", async () => {
  const { env } = makeEnv({ DAILY_PER_IP: "1" });
  const stub = stubUpstream();
  try {
    assert.equal((await worker.fetch(relayRequest("/x", { ip: "3.3.3.3" }), env)).status, 200);
    const second = await worker.fetch(relayRequest("/x", { ip: "3.3.3.3" }), env);
    assert.equal(second.status, 429);
    assert.equal((await second.json()).reason, "ip_daily_quota");
  } finally {
    stub.restore();
  }
});

test("全局日配额：跨 IP 累加，触顶后所有人被拒", async () => {
  const { env } = makeEnv({ DAILY_GLOBAL: "2" });
  const stub = stubUpstream();
  try {
    assert.equal((await worker.fetch(relayRequest("/x", { ip: "1.1.1.1" }), env)).status, 200);
    assert.equal((await worker.fetch(relayRequest("/x", { ip: "2.2.2.2" }), env)).status, 200);
    const third = await worker.fetch(relayRequest("/x", { ip: "3.3.3.3" }), env);
    assert.equal(third.status, 429);
    assert.equal((await third.json()).reason, "global_daily_quota");
  } finally {
    stub.restore();
  }
});

test("被拒绝的请求不占用配额（否则误配上限后无法自行恢复）", async () => {
  const { env, storage } = makeEnv({ RATE_PER_MINUTE: "1" });
  const stub = stubUpstream();
  try {
    for (let i = 0; i < 5; i += 1) {
      await worker.fetch(relayRequest("/x", { ip: "9.9.9.9" }), env);
    }
    const minuteKey = [...storage.keys()].find((k) => k.startsWith("n:"));
    assert.ok(minuteKey, "分钟桶应已写入");
    assert.equal(storage.get(minuteKey), 1, "只应计入 1 次放行");
  } finally {
    stub.restore();
  }
});

test("配额为 0 表示不限", async () => {
  const { env } = makeEnv({
    RATE_PER_MINUTE: "0",
    DAILY_PER_IP: "0",
    DAILY_GLOBAL: "0",
  });
  const stub = stubUpstream();
  try {
    for (let i = 0; i < 5; i += 1) {
      assert.equal((await worker.fetch(relayRequest("/x", { ip: "4.4.4.4" }), env)).status, 200);
    }
  } finally {
    stub.restore();
  }
});

test("放行响应带回剩余额度头", async () => {
  const { env } = makeEnv({ RATE_PER_MINUTE: "10" });
  const stub = stubUpstream();
  try {
    const res = await worker.fetch(relayRequest("/x", { ip: "5.5.5.5" }), env);
    const quota = JSON.parse(res.headers.get("x-aerie-quota"));
    assert.equal(quota.minute, 9);
  } finally {
    stub.restore();
  }
});

// ── 转发 ──────────────────────────────────────────────────

test("默认路由走 DashScope，并替换 Authorization 为真实 Key", async () => {
  const { env } = makeEnv({ DASHSCOPE_KEY: "real-dashscope-key" });
  const stub = stubUpstream();
  try {
    await worker.fetch(relayRequest("/chat/completions"), env);
    assert.equal(stub.calls.length, 1);
    assert.match(stub.calls[0].url, /^https:\/\/dashscope\.aliyuncs\.com\/compatible-mode\/v1\/chat\/completions$/);
    assert.match(stub.calls[0].init.headers.get("Authorization"), /^Bearer real-dashscope-key$/);
  } finally {
    stub.restore();
  }
});

test("/deepseek 前缀被剥离并改走 DeepSeek 上游", async () => {
  const { env } = makeEnv({ DEEPSEEK_KEY: "real-deepseek-key" });
  const stub = stubUpstream();
  try {
    await worker.fetch(relayRequest("/deepseek/chat/completions"), env);
    assert.match(stub.calls[0].url, /^https:\/\/api\.deepseek\.com\/v1\/chat\/completions$/);
    assert.match(stub.calls[0].init.headers.get("Authorization"), /^Bearer real-deepseek-key$/);
  } finally {
    stub.restore();
  }
});

test("客户端多余的 /v1 前缀被去掉（上游 base 已含 /v1）", async () => {
  const { env } = makeEnv({ DASHSCOPE_KEY: "k" });
  const stub = stubUpstream();
  try {
    await worker.fetch(relayRequest("/v1/chat/completions"), env);
    assert.match(stub.calls[0].url, /compatible-mode\/v1\/chat\/completions$/);
    assert.ok(!stub.calls[0].url.includes("/v1/v1/"));
  } finally {
    stub.restore();
  }
});

test("上游未配置 Key 时返回 500 而不是把空 Key 发出去", async () => {
  const { env } = makeEnv();
  delete env.DASHSCOPE_KEY;
  const res = await worker.fetch(relayRequest("/x"), env);
  assert.equal(res.status, 500);
  assert.equal((await res.json()).error, "no upstream key");
});

test("上游抛错时返回 502 并带原因", async () => {
  const { env } = makeEnv({ DASHSCOPE_KEY: "k" });
  const stub = stubUpstream(() => {
    throw new Error("boom");
  });
  try {
    const res = await worker.fetch(relayRequest("/x"), env);
    assert.equal(res.status, 502);
    const body = await res.json();
    assert.equal(body.error, "upstream error");
    assert.match(body.detail, /boom/);
  } finally {
    stub.restore();
  }
});

test("查询串被原样转发", async () => {
  const { env } = makeEnv({ DASHSCOPE_KEY: "k" });
  const stub = stubUpstream();
  try {
    await worker.fetch(relayRequest("/chat/completions?stream=true"), env);
    assert.match(stub.calls[0].url, /\?stream=true$/);
  } finally {
    stub.restore();
  }
});
