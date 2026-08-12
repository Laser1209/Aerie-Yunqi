"""P2 写入校验门（ConsistencyGate）PoC 脚本（§3.7-2）。

对一组合成用例运行 MemoryFactValidator（真实 siliconflow-light 调用），
统计：判定一致率（显式/推断标签 vs LLM 判定）、平均时延、平均 token 消耗、
估算成本。输出结构化报告，供艾莲评审「写入校验门 PoC 结论（成本/误判率评估）」。

用法（仓库根目录）：
    .\\.venv\\Scripts\\python.exe tools\\memory_validation_poc.py
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except Exception:
    pass

from core.memory_validation import MemoryFactValidator

# (text, expected_status) — expected 为人工标注
CASES: list[tuple[str, str]] = [
    # 用户明确表达 → confirmed
    ("用户说：我住在重庆市渝北区龙山街道XX小区3栋1202，这是我的地址。", "confirmed"),
    ("用户说：我喜欢喝拿铁，少糖。", "confirmed"),
    ("用户说：我们的纪念日是每年6月18日。", "confirmed"),
    ("用户说：我下周一出差去上海。", "confirmed"),
    ("用户说：密码是我生日后六位。", "confirmed"),
    # 推断/模糊/脑补 → low_confidence
    ("用户只发了'嗯'，AI 推断用户今天心情不好。", "low_confidence"),
    ("AI 猜测用户可能喜欢红色，因为用户头像边框是红色。", "low_confidence"),
    ("用户说'最近有点忙'，AI 认为用户是在拒绝见面。", "low_confidence"),
    ("AI 设想：用户应该会喜欢这种风格的礼物。", "low_confidence"),
    ("用户问了一句'那个软件好用吗'，AI 推断用户想换电脑。", "low_confidence"),
    # 边界：事实性但非用户亲口表达 → 应低置信度
    ("从用户发来的定位看，他大概住在渝北区（AI 推断）。", "low_confidence"),
]


async def main() -> None:
    validator = MemoryFactValidator(timeout=10.0, max_retries=1)
    rows: list[dict[str, Any]] = []
    total_tokens = 0
    total_ms = 0.0
    correct = 0
    for text, expected in CASES:
        verdict = await validator.validate(
            text=text,
            channel="poc",
            source="poc",
            importance=8,
        )
        status = verdict.get("status")
        ok = status == expected
        correct += int(ok)
        prompt_tok = int(verdict.get("tokens_prompt") or 0)
        comp_tok = int(verdict.get("tokens_completion") or 0)
        total_tokens += prompt_tok + comp_tok
        total_ms += float(verdict.get("duration_ms") or 0)
        rows.append(
            {
                "text": text[:40],
                "expected": expected,
                "got": status,
                "ok": ok,
                "reason": (verdict.get("reason") or "")[:60],
                "tokens": prompt_tok + comp_tok,
                "ms": round(float(verdict.get("duration_ms") or 0), 1),
            }
        )
    n = len(CASES)
    report = {
        "case_count": n,
        "agreement_rate": round(correct / n, 3),
        "avg_latency_ms": round(total_ms / n, 1),
        "avg_tokens_per_call": round(total_tokens / n, 1),
        "total_tokens": total_tokens,
        # 按 siliconflow 轻量模型估算（参考价：~0.3元/百万token）
        "est_cost_cny_per_1000_calls": round(total_tokens / n * 1000 * 0.3e-6, 3),
        "rows": rows,
    }
    print("=== CONSISTENCYGATE_POC ===")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
