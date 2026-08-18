#!/usr/bin/env python3
"""模拟前端滑块切换,验证后端 DSH 工作模式热加载(无需重启)。

流程:
  1. 读 /api/dsh/status 初始状态
  2. PUT /api/settings {dsh.enabled} 反转开关(等价于设置页滑块)
  3. 读 /api/dsh/status 验证 enabled/initialized 是否真的变了
  4. 恢复原状态

前置:后端已运行在 127.0.0.1:7890(启动 start-dev.bat 后执行)。
用法: python tools/dsh_hot_reload_test.py
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:7890"
TIMEOUT = 5


def _request(method: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def get(path: str) -> dict:
    return _request("GET", path)


def put(path: str, body: dict) -> dict:
    return _request("PUT", path, body)


def _fmt(s: dict) -> str:
    return f"enabled={s.get('enabled')} initialized={s.get('initialized')} running={s.get('running')}"


def main() -> int:
    # 1. 读初始状态
    try:
        s0 = get("/api/dsh/status")
    except (urllib.error.URLError, OSError) as exc:
        print(f"[fatal] 后端未运行或无法访问 ({BASE}): {exc}")
        print("        请先启动后端(start-dev.bat)再执行本脚本")
        return 1
    print(f"[1] 初始状态: {_fmt(s0)}")

    # 2. 模拟滑块切换(反转到相反状态)
    target = not bool(s0.get("enabled"))
    resp = put("/api/settings", {"dsh": {"enabled": target}})
    print(f"[2] PUT /api/settings dsh.enabled={target} -> {resp.get('status')}")
    time.sleep(0.5)  # 等热应用完成

    # 3. 验证热加载
    s1 = get("/api/dsh/status")
    print(f"[3] 切换后状态: {_fmt(s1)}")

    # 4. 断言
    ok = s1.get("enabled") == target
    # enabled=true 时 DSH 组件应已初始化;false 时应已清空
    init_ok = (s1.get("initialized") is True) if target else (s1.get("initialized") is False)
    if ok and init_ok:
        print(f"[PASS] 热加载生效: enabled {s0.get('enabled')} -> {s1.get('enabled')}, initialized={s1.get('initialized')}")
    else:
        print(f"[FAIL] 热加载异常: 期望 enabled={target} initialized={target}, 实际 {_fmt(s1)}")
        # 仍尝试恢复原状态,避免留下异常配置
        try:
            put("/api/settings", {"dsh": {"enabled": bool(s0.get("enabled"))}})
        except Exception:
            pass
        return 1

    # 5. 恢复原状态
    put("/api/settings", {"dsh": {"enabled": bool(s0.get("enabled"))}})
    s2 = get("/api/dsh/status")
    print(f"[5] 已恢复原状态: {_fmt(s2)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
