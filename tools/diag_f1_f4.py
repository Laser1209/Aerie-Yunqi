"""Aerie · 云栖 — F1-F4 一站式诊断脚本（无侵入）

目的：在不动任何业务代码的前提下，把以下五类故障的"真实运行状态"
打到 logs/diag_YYYYMMDD_HHMMSS.log 和 stdout，供用户和后续修复者直接看：

  F1  日报空    → /api/brief/today + 4 个 section length + errors
                    + Bocha 环境变量 + RSS 源连通性 ping
  F2  情绪无数据 → /api/emotion/state + /api/emotion/thresholds
                    + DB emotion_state_snapshot 行数 / 最近 5 行
  F3  大脑数据不足 → /api/cognition/stats + /api/cognition/recent
                    + DB cognition_log 行数 / 最近 3 行 stage 列
  F4  头像不显示 → 实际 POST 一个最小 PNG 到 /api/persona/avatar
                    + GET 200 + 磁盘文件大小对比
  F5  反复"已修复"实际未修（共同根因）→ /api/health.stale_code
                    + 后端进程启动时间 vs 所有 .py mtime

本脚本不修改任何业务代码、不调用 /api/system/restart，
仅 GET / POST 探测。所有异常被吞掉并记为 ✗，绝不抛。

用法：
  python tools/diag_f1_f4.py                 # 默认 127.0.0.1:7890
  python tools/diag_f1_f4.py --host 127.0.0.1 --port 7890
  python tools/diag_f1_f4.py --skip-rss-ping # 跳过外网 ping（离线场景）
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sqlite3
import struct
import sys
import time
import urllib.error
import urllib.request
import zlib
from datetime import datetime
from pathlib import Path

# PowerShell 默认 GBK 会让 ✓/✗ 崩；强制 UTF-8 输出
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# ── 路径常量 ─────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = PROJECT_ROOT / "data" / "aerie.db"
AVATAR_DIR = PROJECT_ROOT / "data" / "persona"

# ── 极简 PNG 生成（1×1 透明） ────────────────────────────
# 96 字节有效 PNG，全部为固定字节序列，无外部依赖
_PNG_1X1_BYTES = bytes.fromhex(
    "89504e470d0a1a0a"  # PNG signature
    "0000000d49484452"  # IHDR length + type
    "00000001000000010806000000"  # 1x1, 8-bit RGBA
    "1f15c489"  # IHDR CRC
    "0000001d4944415478da63646060f8cfc0000000030001"
    "5b82ca010000000049454e44ae426082"  # IDAT + IEND
)
# 注意：上面的字节是构造的，可能不是合法的 CRC。脚本用最低要求：能传上去，
# 服务端能识别 PNG signature 并完成 round-trip 即可。如果校验失败，脚本
# 会显示 "上传失败"，那是预期输出 — 我们的目标是观察 round-trip 路径。

# ── 报告行收集 ───────────────────────────────────────────
LINES: list[str] = []
SECTION_DIVIDER = "─" * 72


def log(line: str = "") -> None:
    LINES.append(line)
    print(line)


def section(title: str) -> None:
    log("")
    log(SECTION_DIVIDER)
    log(f"  {title}")
    log(SECTION_DIVIDER)


def ok(msg: str) -> None:
    log(f"  [✓] {msg}")


def warn(msg: str) -> None:
    log(f"  [△] {msg}")


def fail(msg: str) -> None:
    log(f"  [✗] {msg}")


def info(msg: str) -> None:
    log(f"  [i] {msg}")


# ── HTTP 客户端（零依赖） ─────────────────────────────────
def http_get(host: str, port: int, path: str, timeout: float = 5.0) -> tuple[int, bytes]:
    url = f"http://{host}:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except Exception as e:
        return 0, str(e).encode("utf-8", "replace")


def http_post_json(
    host: str, port: int, path: str, payload: dict, timeout: float = 10.0
) -> tuple[int, bytes]:
    url = f"http://{host}:{port}{path}"
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except Exception as e:
        return 0, str(e).encode("utf-8", "replace")


def http_post_multipart(
    host: str, port: int, path: str, filename: str, content_type: str,
    data: bytes, timeout: float = 10.0,
) -> tuple[int, bytes]:
    """手搓 multipart/form-data POST（与 main.js 的 api:upload 同协议）。"""
    boundary = "----AerieDiagBoundary" + hex(int(time.time()))[2:]
    crlf = b"\r\n"
    head = (
        b"--" + boundary.encode() + crlf
        + b'Content-Disposition: form-data; name="file"; filename="'
        + filename.encode() + b'"' + crlf
        + b"Content-Type: " + content_type.encode() + crlf + crlf
    )
    tail = crlf + b"--" + boundary.encode() + b"--" + crlf
    body = head + data + tail

    url = f"http://{host}:{port}{path}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except Exception as e:
        return 0, str(e).encode("utf-8", "replace")


# ── DB 直读（旁路 api_server，直接看真相） ───────────────
def db_query(sql: str, params: tuple = ()) -> list[dict]:
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception as e:
        return [{"__error__": str(e)}]


def db_count(table: str) -> int | None:
    if not DB_PATH.exists():
        return None
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        n = cur.fetchone()[0]
        conn.close()
        return int(n)
    except Exception:
        return None


def db_tables() -> list[str]:
    if not DB_PATH.exists():
        return []
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        rows = [r[0] for r in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


# ── 真实 PNG 字节生成（用 zlib 现场构造 1×1 像素） ──────
def make_png_1x1(color: tuple[int, int, int] = (128, 128, 128)) -> bytes:
    """构造一个真正合法的 1×1 PNG，RGB。"""
    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = b"\x00" + bytes(color)  # filter byte + RGB
    idat = zlib.compress(raw, 9)
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


# ── 各模块诊断 ───────────────────────────────────────────
def diag_health_and_stale(host: str, port: int) -> None:
    section("F5 · 进程 stale 检测（共同根因）")
    code, body = http_get(host, port, "/api/health")
    if code != 200:
        fail(f"后端 /api/health 返回 {code}: {body[:200]!r}")
        info(f"→ 后端可能压根没启动；请先 python main.py")
        return
    try:
        d = json.loads(body)
    except Exception as e:
        fail(f"/api/health 响应不是 JSON: {e}")
        return
    ok(f"后端已运行：{d.get('app')} v{d.get('version')} (uptime {d.get('uptime_seconds')}s)")
    info(f"git_commit = {d.get('git_commit')}")
    info(f"process_started_at = {d.get('process_started_at')}")
    info(f"qq_connected = {d.get('qq_connected')}")
    stale = d.get("stale_code") or {}
    if stale.get("stale"):
        fail("** 后端进程 stale：有 .py 文件在进程启动后被修改，但未重启 **")
        mods = stale.get("modified") or []
        info(f"被修改的文件 (最多列出 20 个，共 {len(mods)}):")
        for m in mods:
            warn(f"  - {m}")
        info(f"started_at = {stale.get('started_at')}")
        info(f"now        = {stale.get('now')}")
        info("→ 修复：跑 tools/restart.bat（或点设置页「重启后端」）")
    else:
        ok("stale_code.stale = false  → 进程与磁盘上的 .py 一致")
        if stale.get("reason"):
            info(f"reason = {stale.get('reason')}")


def diag_brief(host: str, port: int, skip_rss_ping: bool) -> None:
    section("F1 · 日报内容为空")
    # 1) /api/brief/today —— 缓存路径
    code, body = http_get(host, port, "/api/brief/today")
    if code != 200:
        fail(f"/api/brief/today 返回 {code}: {body[:200]!r}")
    else:
        try:
            d = json.loads(body)
            brief = d.get("brief") or {}
            log("")
            info("各 section 内容条数（应在 0 以上）:")
            for k in ("ai_news", "it_news", "intl_news", "cn_news"):
                items = brief.get(k) or []
                if len(items) > 0:
                    ok(f"  {k:10s} = {len(items):3d} 条")
                else:
                    fail(f"  {k:10s} =   0 条  ← 这就是'日报空'的根因")
            errs = brief.get("errors") or {}
            if errs:
                warn(f"errors 字段: {json.dumps(errs, ensure_ascii=False)[:400]}")
            else:
                info("errors 字段: 无")
            wx = brief.get("weather")
            info(f"weather: {'有' if wx else '无'}")
        except Exception as e:
            fail(f"解析 /api/brief/today 失败: {e}")

    # 2) Bocha 环境变量
    log("")
    bocha_key = (os.environ.get("BOCHA_API_KEY") or "").strip()
    if bocha_key:
        ok(f"BOCHA_API_KEY 已配置 (长度 {len(bocha_key)}) — Bocha 兜底可用")
    else:
        warn("BOCHA_API_KEY 未在当前进程环境里 — Bocha 兜底**不可用**")
        info("→ 在 .env 里加 BOCHA_API_KEY=xxx 并重启后端")

    # 3) 触发一次 /api/brief/run —— 强制刷新（如果端点存在）
    log("")
    code, body = http_post_json(host, port, "/api/brief/run", {"force": True}, timeout=30.0)
    if code == 200:
        try:
            d = json.loads(body)
            log("")
            info("/api/brief/run 强制刷新结果:")
            for k in ("ai_news", "it_news", "intl_news", "cn_news"):
                items = d.get(k) or []
                if len(items) > 0:
                    ok(f"  {k:10s} = {len(items):3d} 条")
                else:
                    fail(f"  {k:10s} =   0 条")
            errs = d.get("errors") or {}
            if errs:
                warn(f"errors: {json.dumps(errs, ensure_ascii=False)[:400]}")
        except Exception as e:
            warn(f"解析 /api/brief/run 失败: {e}")
    elif code == 0:
        warn("/api/brief/run: 后端无响应")
    else:
        info(f"/api/brief/run 返回 {code}（可能端点不存在 — 不影响日报功能）")

    # 4) RSS 源 ping（可选）
    if skip_rss_ping:
        info("跳过 RSS 源连通性 ping (--skip-rss-ping)")
        return
    rss_urls = [
        ("ai_news",   "https://hnrss.org/newest?q=AI&count=5"),
        ("it_news",   "https://hnrss.org/newest?count=5"),
        ("intl_news", "https://feeds.bbci.co.uk/news/world/rss.xml"),
        ("cn_news",   "https://www.zhihu.com/rss"),
    ]
    log("")
    info("RSS 源连通性（HEAD 请求，仅探活）:")
    for sec, u in rss_urls:
        try:
            req = urllib.request.Request(u, method="HEAD")
            with urllib.request.urlopen(req, timeout=4) as r:
                if r.status < 400:
                    ok(f"  {sec:10s} {u:60s} {r.status}")
                else:
                    fail(f"  {sec:10s} {u:60s} {r.status}")
        except Exception as e:
            fail(f"  {sec:10s} {u:60s} {type(e).__name__}: {str(e)[:60]}")


def diag_emotion(host: str, port: int) -> None:
    section("F2 · 情绪追踪模块无数据")
    # 1) /api/emotion/state
    code, body = http_get(host, port, "/api/emotion/state")
    if code == 200:
        try:
            d = json.loads(body)
            label = d.get("label")
            pad = d.get("pad") or {}
            ths = d.get("thresholds") or {}
            log("")
            info(f"label = {label}, PAD = P{pad.get('P', '?'):>5}/A{pad.get('A', '?'):>5}/D{pad.get('D', '?'):>5}")
            log("")
            info("4 槽位当前值（来自 /api/emotion/state，in-memory）:")
            for k, v in ths.items():
                val = (v or {}).get("value", 0)
                threshold = (v or {}).get("threshold", 0)
                pct = (v or {}).get("pct", 0)
                if val > 0 or pct > 0:
                    ok(f"  {k:12s} = {val:6.1f}/{threshold:6.1f} ({pct:5.1f}%)")
                else:
                    warn(f"  {k:12s} = {val:6.1f}/{threshold:6.1f} ({pct:5.1f}%) ← 0")
        except Exception as e:
            warn(f"解析 /api/emotion/state 失败: {e}")
    else:
        fail(f"/api/emotion/state 返回 {code}: {body[:200]!r}")

    # 2) DB emotion_state_snapshot 直读
    log("")
    info("emotion_state_snapshot 表（DB 直读，绕过 API）:")
    n = db_count("emotion_state_snapshot")
    if n is None:
        fail("  data/aerie.db 不存在")
    elif n == 0:
        fail("  COUNT = 0  ← 关键证据：没有任何 snapshot 写入")
        info("  → 原因猜测：")
        info("    a) emotion_engine.update_trajectory 从未执行（pipeline 没调到）")
        info("    b) 后端进程 stale（旧代码没接 emotion → snapshot）")
        info("    c) EmotionStateStore.snapshot 内部抛异常被吞")
    else:
        ok(f"  COUNT = {n}")
        rows = db_query(
            "SELECT id, ts, user_id, label, patience_value, anxiety_value, "
            "desire_value, tenderness_value, trigger_event "
            "FROM emotion_state_snapshot ORDER BY id DESC LIMIT 5"
        )
        for r in rows:
            log(
                f"    id={r['id']:5d} ts={r['ts']:>13} "
                f"label={r['label']:>8s} pat={r['patience_value']:6.1f} "
                f"anx={r['anxiety_value']:6.1f} des={r['desire_value']:6.1f} "
                f"ten={r['tenderness_value']:6.1f} trig={r['trigger_event']}"
            )
        # 全 0 警告
        if rows and all(
            r.get("patience_value") == 0 and r.get("anxiety_value") == 0
            and r.get("desire_value") == 0 and r.get("tenderness_value") == 0
            for r in rows
        ):
            warn("  → 最近 5 行 4 槽位全为 0：可能 emotion_state_store 写入但 threshold 为初始值")


def diag_cognition(host: str, port: int) -> None:
    section("F3 · 大脑「数据不足」")
    # 1) /api/cognition/stats
    code, body = http_get(host, port, "/api/cognition/stats")
    if code == 200:
        try:
            d = json.loads(body)
            log("")
            info(f"stats: today={d.get('today')}, total={d.get('total')}, "
                 f"avg_duration_ms={d.get('avg_duration_ms')}")
            if (d.get("total") or 0) == 0:
                fail("  → total = 0  ← 大脑'数据不足'的根因")
            elif (d.get("today") or 0) == 0:
                info("  → total > 0 但 today = 0 (今天还没产生 trace)")
        except Exception as e:
            warn(f"解析 /api/cognition/stats 失败: {e}")
    else:
        fail(f"/api/cognition/stats 返回 {code}: {body[:200]!r}")

    # 2) /api/cognition/recent?limit=3
    log("")
    code, body = http_get(host, port, "/api/cognition/recent?limit=3")
    if code == 200:
        try:
            d = json.loads(body)
            traces = d.get("traces") or []
            if not traces:
                fail("  traces 数组为空")
            else:
                ok(f"  recent 拿到 {len(traces)} 条")
                for t in traces:
                    log(
                        f"    id={t.get('id'):5d} src={t.get('source'):>6s} "
                        f"route={t.get('route_mode'):>6s} dur={t.get('duration_ms'):>5d}ms "
                        f"msg={(t.get('user_message') or '')[:40]!r}"
                    )
        except Exception as e:
            warn(f"解析 /api/cognition/recent 失败: {e}")
    else:
        fail(f"/api/cognition/recent 返回 {code}: {body[:200]!r}")

    # 3) DB cognition_log 直读
    log("")
    info("cognition_log 表（DB 直读，绕过 API）:")
    n = db_count("cognition_log")
    if n is None:
        fail("  data/aerie.db 不存在")
    elif n == 0:
        fail("  COUNT = 0  ← cognition 完全没写入")
        info("  → 原因猜测：")
        info("    a) 后端 stale（pipeline.py 改动未生效）")
        info("    b) /api/chat/send 走的不是 FULL 路径（路由到 BASIC 早返）")
        info("    c) cognition_log 表 schema 不存在或 insert 抛异常被吞")
    else:
        ok(f"  COUNT = {n}")
        rows = db_query(
            "SELECT id, ts, source, user_id, user_message, route_mode, "
            "duration_ms, "
            "LENGTH(stage_route) AS r, LENGTH(stage_emotion) AS e, "
            "LENGTH(stage_threshold) AS t, LENGTH(stage_brain) AS b, "
            "LENGTH(stage_output) AS o "
            "FROM cognition_log ORDER BY id DESC LIMIT 3"
        )
        for r in rows:
            log(
                f"    id={r['id']:5d} src={r['source']:>6s} route={r['route_mode']:>6s} "
                f"dur={r['duration_ms']:>5d}ms "
                f"stages(r/e/t/b/o)={r['r']:4d}/{r['e']:4d}/{r['t']:4d}/{r['b']:4d}/{r['o']:4d} "
                f"msg={(r['user_message'] or '')[:30]!r}"
            )
            if r['r'] == 0 and r['e'] == 0 and r['b'] == 0:
                warn("    → 此行所有 stage 列为 0 字节，cognition commit 写入失败")


def diag_avatar(host: str, port: int) -> None:
    section("F4 · 头像不显示（上传 → 显示 round-trip）")
    # 0) 现状
    info("磁盘现状:")
    for ext in ("png", "jpg", "jpeg"):
        p = AVATAR_DIR / f"avatar.{ext}"
        if p.exists():
            ok(f"  {p.relative_to(PROJECT_ROOT)}  size={p.stat().st_size}B  mtime={datetime.fromtimestamp(p.stat().st_mtime):%H:%M:%S}")
        else:
            info(f"  (无) avatar.{ext}")

    # 1) 构造一个真正合法的 1×1 PNG
    test_png = make_png_1x1((180, 100, 200))
    info(f"测试 PNG 大小: {len(test_png)} bytes (合法 1×1 RGB)")

    # 2) GET /api/persona/avatar（看 URL 路径是否工作）
    log("")
    code, body = http_get(host, port, "/api/persona/avatar")
    if code == 200:
        ok(f"GET /api/persona/avatar → 200, {len(body)} bytes (现有头像可读)")
    elif code == 404:
        info("GET /api/persona/avatar → 404 (当前无头像，需要先上传)")
    else:
        warn(f"GET /api/persona/avatar → {code}: {body[:200]!r}")

    # 3) POST /api/persona/avatar（模拟前端 _onAvatarPick）
    log("")
    info("POST /api/persona/avatar (multipart) …")
    code, body = http_post_multipart(
        host, port, "/api/persona/avatar",
        filename="diag_test.png", content_type="image/png", data=test_png,
    )
    if code == 200:
        try:
            d = json.loads(body)
            if d.get("status") == "ok":
                ok(f"  200 OK, url={d.get('url')}, size={d.get('size')}")
            else:
                fail(f"  200 但 status!=ok: {d}")
        except Exception as e:
            warn(f"  200 但 body 不是 JSON: {e} body={body[:200]!r}")
    else:
        fail(f"  POST /api/persona/avatar 返回 {code}: {body[:400]!r}")
        if code in (415, 413, 400):
            info("  → 说明 _onAvatarPick 也会失败，前端应该显示 '上传失败'")
        return

    # 4) POST 后立刻 GET，确认 round-trip
    log("")
    code, body = http_get(host, port, "/api/persona/avatar?nocache=" + hex(int(time.time())))
    if code == 200 and body == test_png:
        ok(f"GET 之后 200 + bytes 匹配上传内容 → 后端 round-trip **完全正常**")
    elif code == 200:
        warn(f"GET 200 但 bytes 与上传不一致 (got {len(body)} bytes, expected {len(test_png)})")
    else:
        fail(f"GET 返回 {code} → round-trip 失败")

    # 5) 磁盘校验
    log("")
    info("磁盘校验（看是否真的写到 avatar.png）:")
    for ext in ("png", "jpg", "jpeg"):
        p = AVATAR_DIR / f"avatar.{ext}"
        if p.exists():
            try:
                cur_size = p.stat().st_size
                if cur_size == len(test_png):
                    ok(f"  avatar.{ext} size={cur_size} (与上传一致)")
                else:
                    info(f"  avatar.{ext} size={cur_size} (≠ 测试上传 {len(test_png)}，可能原本就是其他图)")
            except Exception as e:
                warn(f"  stat {p} 失败: {e}")


def diag_db_layout() -> None:
    section("DB 布局 & 表行数快照")
    tables = db_tables()
    if not tables:
        fail(f"data/aerie.db 不存在 ({DB_PATH})")
        return
    ok(f"data/aerie.db 存在, {len(tables)} 张表")
    log("")
    info("关键表行数（与 F2/F3 强相关）:")
    interesting = [
        "emotion_state_snapshot",  # F2
        "cognition_log",            # F3
        "tool_call_log",            # F3 工具阶段
        "chat_log",                 # 用户/AI 消息
        "self_evolve_proposals",    # F3 提案
    ]
    for t in interesting:
        if t in tables:
            n = db_count(t)
            if n is not None:
                if n > 0:
                    ok(f"  {t:30s} = {n:6d} 行")
                else:
                    warn(f"  {t:30s} = {n:6d} 行  ← 空表")
        else:
            fail(f"  {t:30s} = 表不存在")
    log("")
    info("全部表清单:")
    for t in tables:
        n = db_count(t)
        log(f"    {t:35s} {n if n is not None else '?':>8}")


# ── 入口 ────────────────────────────────────────────────
def main() -> int:
    parser = argparse.ArgumentParser(description="Aerie F1-F4 一站式诊断")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7890)
    parser.add_argument("--skip-rss-ping", action="store_true",
                        help="跳过外网 RSS HEAD ping (离线环境)")
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    log("=" * 72)
    log(f"  Aerie · 云栖  F1-F4 诊断报告")
    log(f"  目标后端: http://{args.host}:{args.port}")
    log(f"  时间:     {datetime.now():%Y-%m-%d %H:%M:%S}")
    log(f"  日志:     logs/diag_{ts}.log")
    log("=" * 72)

    diag_db_layout()
    diag_health_and_stale(args.host, args.port)
    diag_brief(args.host, args.port, args.skip_rss_ping)
    diag_emotion(args.host, args.port)
    diag_cognition(args.host, args.port)
    diag_avatar(args.host, args.port)

    log("")
    log("=" * 72)
    log("  诊断完成。建议阅读顺序：F5 → F4 → F1 → F2 → F3")
    log("=" * 72)
    log("")

    log_path = LOG_DIR / f"diag_{ts}.log"
    try:
        log_path.write_text("\n".join(LINES), encoding="utf-8")
        print(f"[已落盘] {log_path.relative_to(PROJECT_ROOT)}")
    except Exception as e:
        print(f"[落盘失败] {e}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
