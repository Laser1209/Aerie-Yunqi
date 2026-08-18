#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH stdio JSON-RPC 连通性 + 资源占用最小 PoC(Windows, node 模式)。

目标(对应 M0 里程碑第一道坎):
  1. 验证 node 模式下 DSH 运行时能否通过 stdio JSON-RPC 握手并跑通一次 prompt
  2. 实测子进程 RSS / CPU / 启动-握手延迟 / 端到端延迟

设计取舍:
  - 不依赖 deepseek-harness-sdk,避免引入 pydantic>=2.12 与 Aerie 主 venv 的
    依赖冲突风险(整合文档 V7)。直接 subprocess + 手写 JSON-RPC 帧驱动 node 入口。
  - 复用主仓库已 build 的 packaged-bin.js,不构建独立 runtime/node 闭包,
    也不走 pip install,零环境污染。
  - stdout 只承载 JSON-RPC 帧(换行分隔),stderr 是诊断,二者严格分离。

用法:
  python tools/dsh_poc.py                 # 完整链路(initialize + 一次 say hi + 资源采样)
  python tools/dsh_poc.py --connect-only  # 仅握手,不调模型(无 key 也能测连通性)
  python tools/dsh_poc.py --model deepseek-chat --timeout 90
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

try:
    import psutil
except ImportError:  # 环境无 psutil 时给出明确提示
    psutil = None

DSH_ROOT = Path(r"E:\DeepSeek Hermes")
ENTRY = (
    DSH_ROOT / "python" / "sdk-runtime" / "src" / "deepseek_harness_runtime"
    / "runtime" / "node" / "node_modules" / "@deepseek-ai"
    / "dsh-sdk-jsonrpc-demo" / "lib" / "packaged-bin.js"
)
CORDIS = DSH_ROOT / "python" / "sdk-runtime" / "src" / "deepseek_harness_runtime" / "runtime" / "cordis.yml"
AERIE_ENV = Path(r"E:\Agent_reply\.env")


def load_aerie_env() -> dict[str, str]:
    """从 Aerie .env 读取 DEEPSEEK key/base_url(只进子进程环境,不打印明文)。"""
    out: dict[str, str] = {}
    if not AERIE_ENV.exists():
        return out
    for line in AERIE_ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


class ResourceSampler:
    """后台采样子进程 RSS / CPU,记录峰值。"""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._stop = threading.Event()
        self.peak_rss_mb = 0.0
        self.last_cpu_pct = 0.0
        self.samples = 0
        self._thread = threading.Thread(target=self._loop, name="dsh-poc-sampler", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=1.0)

    def _loop(self) -> None:
        proc = psutil.Process(self.pid)
        try:
            proc.cpu_percent(interval=None)
        except psutil.NoSuchProcess:
            return
        while not self._stop.is_set():
            try:
                rss_mb = proc.memory_info().rss / (1024 * 1024)
                self.peak_rss_mb = max(self.peak_rss_mb, rss_mb)
                self.last_cpu_pct = proc.cpu_percent(interval=None)
                self.samples += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return
            self._stop.wait(0.1)


class DshPoc:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.proc: subprocess.Popen[str] | None = None
        self._responses: dict[str, threading.Event] = {}
        self._response_payloads: dict[str, object] = {}
        self._notifications: list[dict] = []
        self._notif_cv = threading.Condition()
        self._stderr: list[str] = []
        self.sampler: ResourceSampler | None = None

    def start(self) -> None:
        entry = Path(self.args.entry)
        cordis = Path(self.args.cordis)
        if not entry.is_file():
            sys.exit(f"[fatal] node 入口不存在: {entry}")
        if not cordis.is_file():
            sys.exit(f"[fatal] cordis 配置不存在: {cordis}")

        env = os.environ.copy()
        if not self.args.connect_only:
            aerie = load_aerie_env()
            env["DEEPSEEK_API_KEY"] = aerie.get("DEEPSEEK_API_KEY", "")
            env["DEEPSEEK_BASE_URL"] = aerie.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
        env["DSH_CORDIS_CONFIG"] = str(cordis)
        env["DSH_SESSION_ROOT"] = self.args.session_root
        env["DSH_CWD"] = self.args.cwd
        env["DSH_RUNTIME_MODE"] = "node"

        t0 = time.monotonic()
        self.proc = subprocess.Popen(
            ["node", str(entry)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            cwd=str(DSH_ROOT),
            env=env,
            bufsize=1,
        )
        self.spawn_s = time.monotonic() - t0
        if psutil is not None:
            self.sampler = ResourceSampler(self.proc.pid)
            self.sampler.start()
        threading.Thread(target=self._read_loop, args=(self.proc.stdout,), name="dsh-poc-stdout", daemon=True).start()
        threading.Thread(target=self._stderr_loop, args=(self.proc.stderr,), name="dsh-poc-stderr", daemon=True).start()

    def close(self) -> None:
        proc = self.proc
        if proc is None:
            return
        try:
            self.request("shutdown", None, timeout=5.0)
        except Exception:
            pass
        if proc.stdin:
            try:
                proc.stdin.close()
            except Exception:
                pass
        if proc.poll() is None:
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self.sampler is not None:
            self.sampler.stop()
        self.proc = None

    def _read_loop(self, stream: object) -> None:
        assert stream is not None
        for line in stream:  # type: ignore[union-attr]
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(msg, dict):
                continue
            msg_id = msg.get("id")
            method = msg.get("method")
            if isinstance(msg_id, (str, int)) and isinstance(method, str):
                with self._notif_cv:
                    self._notifications.append({"incoming_request": method, "id": msg_id})
                    self._notif_cv.notify_all()
                continue
            if isinstance(msg_id, (str, int)):
                key = str(msg_id)
                self._response_payloads[key] = msg.get("result", msg.get("error"))
                ev = self._responses.get(key)
                if ev is not None:
                    ev.set()
                continue
            if isinstance(method, str):
                with self._notif_cv:
                    self._notifications.append(msg)
                    self._notif_cv.notify_all()

    def _stderr_loop(self, stream: object) -> None:
        assert stream is not None
        for line in stream:  # type: ignore[union-attr]
            self._stderr.append(line.rstrip())

    def _write(self, message: dict) -> None:
        if self.proc is None or self.proc.stdin is None:
            raise RuntimeError("runtime not running")
        self.proc.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
        self.proc.stdin.flush()

    def request(self, method: str, params: object, *, timeout: float) -> object:
        req_id = str(int(time.time() * 1_000_000))
        ev = threading.Event()
        self._responses[req_id] = ev
        msg: dict = {"jsonrpc": "2.0", "id": req_id, "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)
        if not ev.wait(timeout):
            raise TimeoutError(f"{method} 超时({timeout}s)")
        return self._response_payloads.get(req_id)

    def wait_for_idle(self, session_id: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        events: list[dict] = []
        while time.monotonic() < deadline:
            with self._notif_cv:
                self._notif_cv.wait(timeout=0.2)
            while True:
                with self._notif_cv:
                    if not self._notifications:
                        break
                    n = self._notifications.pop(0)
                m = n.get("method")
                p = n.get("params") or {}
                if m == "session.event" and p.get("sessionId") == session_id:
                    events.append(p.get("event") or {})
                elif m == "session.status" and p.get("sessionId") == session_id and p.get("status") == "idle":
                    return {"events": events, "finish_reason": _finish_reason(events), "final_response": _final_response(events)}
                elif m == "session.status" and p.get("sessionId") == session_id and p.get("status") == "error":
                    return {"events": events, "finish_reason": "error", "final_response": ""}
        return {"events": events, "finish_reason": None, "final_response": ""}

    def run(self) -> None:
        print("== DSH stdio JSON-RPC PoC ==")
        print(f"  entry   : {self.args.entry}")
        print(f"  cordis  : {self.args.cordis}")
        print(f"  sampler : {'psutil' if psutil is not None else '无(未采样)'}")

        self.start()
        print(f"[1/4] spawn 完成: {self.spawn_s:.2f}s")

        t = time.monotonic()
        self.request(
            "initialize",
            {"cwd": self.args.cwd, "provider": self.args.provider, "model": self.args.model},
            timeout=self.args.timeout,
        )
        print(f"[2/4] initialize 握手成功: {time.monotonic() - t:.2f}s")

        if self.args.connect_only:
            print("[3/4] --connect-only: 跳过模型调用,连通性已验证")
        else:
            session_id = "dsh-poc-session"
            t = time.monotonic()
            self.request(
                "session/prompt",
                {"sessionId": session_id, "contentBlocks": [{"type": "text", "text": self.args.prompt}]},
                timeout=self.args.timeout,
            )
            result = self.wait_for_idle(session_id, self.args.timeout)
            print(f"[3/4] prompt 完成: {time.monotonic() - t:.2f}s | finish_reason={result['finish_reason']}")
            reply = result["final_response"].strip().replace("\n", " ")
            print(f"      回复: {reply[:120]}")

        rss = self.sampler.peak_rss_mb if self.sampler else 0.0
        cpu = self.sampler.last_cpu_pct if self.sampler else 0.0
        n = self.sampler.samples if self.sampler else 0
        print(f"[4/4] 资源: 峰值 RSS={rss:.1f} MB | 最后 CPU={cpu:.1f}% | 采样={n}")

        if self._stderr:
            print("\n== stderr 尾部(诊断) ==")
            for line in self._stderr[-12:]:
                print(f"  {line}")

        self.close()
        print("\n== 完成 ==")


def _final_response(events: list[dict]) -> str:
    for ev in reversed(events):
        if ev.get("type") != "assistant/message":
            continue
        data = ev.get("data")
        if not isinstance(data, dict):
            continue
        message = data.get("message")
        content_owner = message if isinstance(message, dict) else data
        content = content_owner.get("content")
        if not isinstance(content, list):
            continue
        parts = [str(b.get("text") or "") for b in content if isinstance(b, dict) and b.get("type") == "text"]
        return "".join(parts)
    return ""


def _finish_reason(events: list[dict]) -> str | None:
    for ev in reversed(events):
        if ev.get("type") != "turn/end":
            continue
        data = ev.get("data")
        if isinstance(data, dict):
            reason = data.get("reason")
            if isinstance(reason, dict) and isinstance(reason.get("kind"), str):
                return reason["kind"]
    return None


def main() -> None:
    p = argparse.ArgumentParser(description="DSH stdio JSON-RPC 连通性 + 资源占用 PoC")
    p.add_argument("--entry", default=str(ENTRY), help="node 入口 packaged-bin.js 路径")
    p.add_argument("--cordis", default=str(CORDIS), help="cordis.yml 路径")
    p.add_argument("--connect-only", action="store_true", help="仅握手,不调模型")
    p.add_argument("--model", default="deepseek-chat", help="DeepSeek 模型名")
    p.add_argument("--provider", default="deepseek-official", help="DSH provider 路由名")
    p.add_argument("--prompt", default="Say hi in one short sentence.", help="测试 prompt")
    p.add_argument("--timeout", type=int, default=90, help="单请求超时(秒)")
    p.add_argument("--cwd", default=str(DSH_ROOT), help="DSH_CWD")
    p.add_argument("--session-root", default=tempfile.mkdtemp(prefix="dsh-poc-"), help="DSH_SESSION_ROOT")
    args = p.parse_args()

    if psutil is None:
        print("[warn] 未安装 psutil,资源占用无法采样(连通性不受影响)")
    poc = DshPoc(args)
    try:
        poc.run()
    except TimeoutError as exc:
        print(f"\n[fatal] {exc}")
        for line in poc._stderr[-20:]:
            print(f"  {line}")
        poc.close()
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\n[fatal] {type(exc).__name__}: {exc}")
        for line in poc._stderr[-20:]:
            print(f"  {line}")
        poc.close()
        sys.exit(1)


if __name__ == "__main__":
    main()
