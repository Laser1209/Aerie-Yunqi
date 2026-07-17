"""
Aerie v12.0 · S5 收口验证脚本
  M5.1 自进化 L4 + M5.2 电脑操控 + M5.3 文件整理
+ M5.4 文档写作 + M5.5 自主 Skill 创建 + M5.6 QQ 深耕
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def run_module(name: str, filename: str) -> tuple[int, int, float]:
    """运行单个模块验证脚本，返回 (通过数, 总数, 耗时)"""
    import subprocess
    start = time.time()
    result = subprocess.run(
        [sys.executable, str(Path(__file__).parent / filename)],
        capture_output=True, text=True, timeout=120,
    )
    elapsed = time.time() - start

    passed = 0
    total = 0
    for line in result.stdout.splitlines():
        if "结果:" in line and "通过" in line:
            # 格式: 结果: 25/25 通过
            parts = line.replace("结果:", "").strip().split("/")
            if len(parts) == 2:
                total = int(parts[0]) if total == 0 else total
                right = parts[1].split("通过")[0].strip()
                passed = total
                total = int(right) if right.isdigit() else total
            # 更准确的提取
            import re
            m = re.search(r"(\d+)/(\d+) 通过", line)
            if m:
                passed = int(m.group(1))
                total = int(m.group(2))

    status = "✅" if passed == total and total > 0 else "❌"
    print(f"  {status} {name:<20s} {passed}/{total}  ({elapsed:.1f}s)")

    if passed < total:
        # 打印最后几行错误
        lines = result.stdout.strip().splitlines()
        for line in lines[-5:]:
            if "✗" in line or "未通过" in line or "Error" in line or "error" in line:
                print(f"       └─ {line.strip()}")

    return passed, total, elapsed


def main():
    print("=" * 64)
    print("   Aerie v12.0 · S5 收口验证")
    print("   外部单 Agent + 内部准多 Agent · 能力大爆发")
    print("=" * 64)
    print()
    print("  模块                     通过/总数      耗时")
    print("  " + "-" * 56)

    modules = [
        ("M5.1 自进化 L4",        "e2e_s5_self_evolve_l4_verify.py"),
        ("M5.2 电脑操控",         "e2e_s5_computer_control_verify.py"),
        ("M5.3 文件整理",         "e2e_s5_file_organizer_verify.py"),
        ("M5.4 文档写作",         "e2e_s5_doc_writer_verify.py"),
        ("M5.5 自主 Skill 创建",  "e2e_s5_skill_creator_verify.py"),
        ("M5.6 QQ 深耕",          "e2e_s5_qq_deepening_verify.py"),
    ]

    total_passed = 0
    total_items = 0
    total_time = 0.0
    failed_modules = []

    for name, filename in modules:
        # 检查文件是否存在
        if not Path(filename).exists():
            print(f"  ⚠️  {name:<20s} 脚本不存在: {filename}")
            failed_modules.append(name)
            continue

        p, t, e = run_module(name, filename)
        total_passed += p
        total_items += t
        total_time += e
        if p < t or t == 0:
            failed_modules.append(name)

    print("  " + "-" * 56)
    print(f"  {'合计':<22s} {total_passed}/{total_items}  ({total_time:.1f}s)")
    print()

    # S5 核心能力清单
    print("=" * 64)
    print("  S5 阶段新增核心能力：")
    print("=" * 64)
    s5_features = [
        ("🧬 自进化 L4", "代码自修改 · 4 道生存闸门 · 24h 回滚窗口"),
        ("🖱️ 电脑操控",   "3 级权限 · 键鼠/截图/UIA · 危险命令拦截"),
        ("📁 文件整理",   "AI 智能分类 · 预览执行 · 7 天撤销"),
        ("📝 文档写作",   "5 类模板 · 4 种导出格式 · 3 种 HTML 样式"),
        ("🔧 自主 Skill", "5 类模板 · 安全沙箱 · 命名空间隔离"),
        ("💬 QQ 深耕",    "语音优化 · 视频管理 · 主动消息 v2"),
    ]
    for feat, desc in s5_features:
        print(f"  {feat:<16s}  {desc}")

    print()
    print("=" * 64)
    if not failed_modules:
        print("  🎉 S5 收口验证全部通过！Aerie v12.0.0 就绪")
        print("     版本跃升: v10.1.1 → v12.0.0")
        print("     核心架构: 外部单 Agent + 内部准多 Agent")
    else:
        print(f"  ⚠️  {len(failed_modules)} 个模块未通过: {failed_modules}")
    print("=" * 64)

    return len(failed_modules) == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
