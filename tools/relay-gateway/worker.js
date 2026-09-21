// Aerie · 云栖 AI 中转网关（Cloudflare Worker）
//
// 设计前提：门卡（RELAY_TOKEN）是「按设计公开」的凭据——它必须随安装包分发
// 给每一个用户，任何人反编译安装包都能拿到。所以防滥用不能靠保密，只能落在
// 服务端。本网关承担三件事：
//
//   1. 单 IP 限流      —— 挡住单个滥用者刷额度
//   2. 每日配额        —— 给总花费兜底（全局 + 单 IP 双层）
//   3. 客户端版本绑定  —— 用于淘汰旧版本、识别非官方客户端
//
// 计数集中在一个 Durable Object 里，因为这三项都需要跨边缘节点的全局一致性。
//
// 路由：
//   GET  /health      存活探测（不计数）
//   POST /deepseek/** 走 DeepSeek
//   其余路径          走阿里云百炼 DashScope

const UPSTREAM_DEFAULT = {
  dashscope: "https://dashscope.aliyuncs.com/compatible-mode/v1",
  deepseek: "https://api.deepseek.com/v1",
};

// 配额与限流的唯一权威计数器。
//
// 单实例（idFromName("global")）串行处理，配合 Durable Object 的 input gate
// 语义（有存储操作在途时不再投递新事件），下面「读-改-写」的累加是安全的，
// 不需要额外的锁。
export class RelayGate {
  constructor(state, env) {
    this.storage = state.storage;
    this.env = env;
  }

  async fetch(request) {
    const { ip } = await request.json();

    const now = new Date();
    const day = now.toISOString().slice(0, 10);          // 2026-09-22
    const minute = now.toISOString().slice(0, 16);       // 2026-09-22T10:35

    const keys = {
      globalDay: `g:${day}`,
      ipDay: `i:${ip}:${day}`,
      ipMinute: `n:${ip}:${minute}`,
    };
    const limits = {
      globalDay: toLimit(this.env.DAILY_GLOBAL),
      ipDay: toLimit(this.env.DAILY_PER_IP),
      ipMinute: toLimit(this.env.RATE_PER_MINUTE),
    };

    const [usedGlobalDay, usedIpDay, usedIpMinute] = await Promise.all([
      this.storage.get(keys.globalDay),
      this.storage.get(keys.ipDay),
      this.storage.get(keys.ipMinute),
    ]);

    const counts = {
      globalDay: toCount(usedGlobalDay),
      ipDay: toCount(usedIpDay),
      ipMinute: toCount(usedIpMinute),
    };

    // 先判定后累加：被拒绝的请求不计入配额，否则一次误配的上限会让计数器
    // 越滚越大，恢复上限后仍持续拒绝。
    const denied = firstExceeded(counts, limits);
    if (denied) {
      return this.reply({
        allowed: false,
        reason: denied.reason,
        retryAfter: secondsUntilReset(denied.reason, now),
        remaining: { minute: remaining(counts.ipMinute, limits.ipMinute) },
      });
    }

    // 分钟桶只需活过这一分钟，日桶只需活过今天，靠 TTL 自动回收，不必写清理逻辑。
    await Promise.all([
      this.storage.put(keys.globalDay, counts.globalDay + 1, { expirationTtl: 172800 }),
      this.storage.put(keys.ipDay, counts.ipDay + 1, { expirationTtl: 172800 }),
      this.storage.put(keys.ipMinute, counts.ipMinute + 1, { expirationTtl: 120 }),
    ]);

    return this.reply({
      allowed: true,
      remaining: {
        minute: remaining(counts.ipMinute + 1, limits.ipMinute),
        ipDay: remaining(counts.ipDay + 1, limits.ipDay),
        globalDay: remaining(counts.globalDay + 1, limits.globalDay),
      },
    });
  }

  reply(payload) {
    return new Response(JSON.stringify(payload), {
      headers: { "content-type": "application/json; charset=utf-8" },
    });
  }
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/health") return new Response("ok");

    // ── 门卡校验 ──────────────────────────────────────────────
    const auth = request.headers.get("Authorization") || "";
    if (!env.RELAY_TOKEN || auth !== `Bearer ${env.RELAY_TOKEN}`) {
      return json({ error: "unauthorized" }, 401);
    }

    // ── 客户端版本绑定 ────────────────────────────────────────
    const versionRejection = rejectVersion(request, env);
    if (versionRejection) return versionRejection;

    // ── 限流与每日配额 ────────────────────────────────────────
    const gate = await checkGate(request, env);
    if (!gate.allowed) {
      return json(
        { error: "rate_limited", reason: gate.reason },
        429,
        {
          "retry-after": String(gate.retryAfter || 60),
          "x-aerie-reason": gate.reason || "rate_limited",
        },
      );
    }

    const response = await proxy(request, url, env);
    return withQuotaHeaders(response, gate.remaining);
  },
};

/**
 * 版本绑定：ALLOWED_VERSIONS 为空表示不校验（灰度期默认如此）。
 *
 * 为什么默认放行而不是默认拦截：已分发出去的安装包不会自己升级，一旦默认
 * 拦截且列表配错，所有老用户会立刻全部不可用。先观察，再收紧。
 */
function rejectVersion(request, env) {
  const allowed = String(env.ALLOWED_VERSIONS || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  if (allowed.length === 0) return null;

  const reported = (request.headers.get("X-Aerie-Version") || "").trim();
  if (allowed.some((prefix) => reported.startsWith(prefix))) return null;

  return json(
    {
      error: "client_version_rejected",
      detail: reported ? `version ${reported} is not served` : "missing X-Aerie-Version",
      allowed,
    },
    426,
  );
}

async function checkGate(request, env) {
  const ip = request.headers.get("CF-Connecting-IP") || "unknown";
  const stub = env.RELAY_GATE.get(env.RELAY_GATE.idFromName("global"));
  const response = await stub.fetch("https://relay-gate/check", {
    method: "POST",
    body: JSON.stringify({ ip }),
  });
  return response.json();
}

async function proxy(request, url, env) {
  const isDeepseek = url.pathname === "/deepseek" || url.pathname.startsWith("/deepseek/");

  let base, key;
  if (isDeepseek) {
    base = env.DEEPSEEK_BASE || UPSTREAM_DEFAULT.deepseek;
    key = env.DEEPSEEK_KEY;
    url.pathname = url.pathname.replace(/^\/deepseek/, "") || "/";
  } else {
    base = env.DASHSCOPE_BASE || UPSTREAM_DEFAULT.dashscope;
    key = env.DASHSCOPE_KEY;
  }
  if (!key) return json({ error: "no upstream key" }, 500);

  // 客户端可能带 /v1 前缀，而上游 base 里已含 /v1，重复会 404。
  let upstreamPath = url.pathname;
  if (upstreamPath.startsWith("/v1/")) upstreamPath = upstreamPath.replace(/^\/v1/, "");

  try {
    // 先完整读出请求体再转发：直接流转发在流式响应场景下会丢 body。
    const body = await request.arrayBuffer();

    const headers = new Headers(request.headers);
    headers.set("Authorization", `Bearer ${key}`);
    headers.delete("Host");
    headers.delete("Content-Length");

    const upstream = base.replace(/\/$/, "") + upstreamPath + url.search;
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: body.byteLength > 0 ? body : undefined,
      redirect: "follow",
    });

    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete("content-length");
    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch (e) {
    return json(
      { error: "upstream error", detail: String((e && e.message) || e) },
      502,
    );
  }
}

// 把剩余额度透回客户端：出问题时能直接看到是「被限了」还是「上游挂了」。
function withQuotaHeaders(response, remaining) {
  if (!remaining) return response;
  const headers = new Headers(response.headers);
  headers.set("x-aerie-quota", JSON.stringify(remaining));
  return new Response(response.body, { status: response.status, headers });
}

function firstExceeded(counts, limits) {
  if (limits.ipMinute > 0 && counts.ipMinute >= limits.ipMinute) {
    return { reason: "ip_rate_limit" };
  }
  if (limits.ipDay > 0 && counts.ipDay >= limits.ipDay) {
    return { reason: "ip_daily_quota" };
  }
  if (limits.globalDay > 0 && counts.globalDay >= limits.globalDay) {
    return { reason: "global_daily_quota" };
  }
  return null;
}

function remaining(used, limit) {
  return limit > 0 ? Math.max(0, limit - used) : -1; // -1 表示不限
}

// 告诉调用方还要等多久，避免客户端立刻重试造成雪崩。
function secondsUntilReset(reason, now) {
  if (reason === "ip_rate_limit") {
    return Math.max(1, 60 - now.getUTCSeconds());
  }
  const endOfDay = Date.UTC(
    now.getUTCFullYear(),
    now.getUTCMonth(),
    now.getUTCDate() + 1,
  );
  return Math.max(1, Math.ceil((endOfDay - now.getTime()) / 1000));
}

function toLimit(value) {
  const parsed = Number.parseInt(value, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : 0;
}

function toCount(value) {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : 0;
}

function json(obj, status = 200, extraHeaders = {}) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8", ...extraHeaders },
  });
}
