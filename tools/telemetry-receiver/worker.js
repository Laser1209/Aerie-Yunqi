// Aerie · 云栖 diagnostics receiver (Cloudflare Worker + R2)
//
// Receives raw diagnostic zip packages POSTed by the desktop app's
// `core/telemetry.py` and stores them in an R2 bucket. No multipart parsing
// is required: the zip bytes are the request body, metadata travels in headers.
//
//   POST /upload   — store a package
//   GET  /         — liveness probe

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/" && request.method === "GET") {
      return json({ ok: true, service: "aerie-diagnostics-receiver" });
    }

    if (url.pathname === "/upload" && request.method === "POST") {
      return handleUpload(request, env);
    }

    return json({ ok: false, error: "not_found" }, 404);
  },
};

async function handleUpload(request, env) {
  // Optional auth: only enforced when a token is configured as a Worker secret.
  const token = (env.DIAG_UPLOAD_TOKEN || "").trim();
  if (token) {
    const auth = request.headers.get("Authorization") || "";
    if (auth !== `Bearer ${token}`) {
      return json({ ok: false, error: "unauthorized" }, 401);
    }
  }

  const filename = sanitize(request.headers.get("X-Diagnostic-Filename") || "diag.zip");
  const deviceId = sanitize(request.headers.get("X-Device-Id") || "unknown");

  const body = await request.arrayBuffer();
  if (!body || body.byteLength === 0) {
    return json({ ok: false, error: "empty_body" }, 400);
  }

  const date = new Date().toISOString().slice(0, 10).replace(/-/g, "");
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  const key = `diagnostics/${date}/${stamp}-${deviceId}-${filename}`;

  try {
    await env.DIAG_BUCKET.put(key, body, {
      httpMetadata: { contentType: "application/zip" },
      customMetadata: { deviceId, filename },
    });
  } catch (e) {
    return json(
      { ok: false, error: "storage_error", detail: String((e && e.message) || e) },
      500,
    );
  }

  return json({
    ok: true,
    key,
    bytes: body.byteLength,
    receivedAt: new Date().toISOString(),
  });
}

function sanitize(value) {
  return String(value || "")
    .replace(/[^a-zA-Z0-9._-]/g, "_")
    .slice(0, 128);
}

function json(obj, status = 200) {
  return new Response(JSON.stringify(obj), {
    status,
    headers: { "content-type": "application/json; charset=utf-8" },
  });
}
