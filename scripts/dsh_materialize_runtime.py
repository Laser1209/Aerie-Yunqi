#!/usr/bin/env python3
"""物化 DSH node 运行时闭包(固化 V19-V22 的 deploy+restore+materialize 流程)。

背景:Windows 无 DSH 生产 exe,只能走 node 模式。官方 build-exe-for-python-sdk.ts
在 Node24/Windows 下 spawn pnpm.cmd 报 EINVAL(V20),故本脚本手动复刻其
deployStaging + restoreLegacyHoists 两步,把 node 闭包物化到:
  python/sdk-runtime/src/deepseek_harness_runtime/runtime/node/

用法:
  python scripts/dsh_materialize_runtime.py               # 完整流程(首次,约 4-6 分钟)
  python scripts/dsh_materialize_runtime.py --skip-deploy # 仅 restore+verify(闭包已 deploy 时快速修复)
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

DSH_ROOT = Path(r"E:\DeepSeek Hermes")
STAGING = DSH_ROOT / "python" / "sdk-runtime" / "src" / "deepseek_harness_runtime" / "runtime" / "node"
SOURCE_NODE_MODULES = DSH_ROOT / "python" / "sdk-runtime" / "node_modules"

# cordis.yml 必需的 8 个插件(缺一个 dsh_cli 就无法握手)
_REQUIRED = [
    "dsh-sdk-jsonrpc-server",
    "dsh-agent-spine-demo",
    "dsh-llm-deepseek",
    "dsh-session-persistence-jsonl",
    "dsh-session-checkpoint-policy",
    "dsh-subprocess-local",
    "dsh-bash-local",
    "dsh-fs-local",
]


def run_pnpm_deploy() -> None:
    """deployStaging:rm -rf staging → pnpm deploy 物化闭包(等价 build 脚本的 deploy 命令)。"""
    print(f"[1/3] pnpm deploy → {STAGING}")
    shutil.rmtree(STAGING, ignore_errors=True)
    cmd = [
        "pnpm", "--filter", "dsh-jsonrpc-agent-pkg", "deploy",
        "--legacy", "--prod",
        "--config.node-linker=hoisted",
        "--config.auto-install-peers=false",
        "--config.link-workspace-packages=true",
        str(STAGING),
    ]
    subprocess.run(cmd, cwd=str(DSH_ROOT), check=True)


def restore_deepseek_ai() -> None:
    """restoreLegacyHoists:legacy deploy 会把部分 @deepseek-ai 直接依赖 hoist 到 source 侧,
    需从 python/sdk-runtime/node_modules 复制补齐(dereference,排除嵌套 node_modules)。"""
    print("[2/3] restore @deepseek-ai packages")
    source_ai = SOURCE_NODE_MODULES / "@deepseek-ai"
    if not source_ai.is_dir():
        raise FileNotFoundError(f"source @deepseek-ai missing: {source_ai}")

    target_ai = STAGING / "node_modules" / "@deepseek-ai"
    shutil.rmtree(target_ai, ignore_errors=True)
    target_ai.mkdir(parents=True, exist_ok=True)

    count = 0
    for entry in sorted(source_ai.iterdir()):
        shutil.copytree(
            entry,
            target_ai / entry.name,
            symlinks=False,  # dereference:workspace 包 symlink 物化为实体
            ignore=shutil.ignore_patterns("node_modules"),  # 嵌套 node_modules symlink 会 dereference 失败
        )
        count += 1
    print(f"      restored {count} packages")


def verify() -> None:
    """校验 cordis.yml 必需的 8 个插件就位。"""
    print("[3/3] verify required plugins")
    node_modules = STAGING / "node_modules"
    ok = True
    for pkg in _REQUIRED:
        present = (node_modules / "@deepseek-ai" / pkg / "package.json").is_file()
        print(f"      {'ok  ' if present else 'MISS'} {pkg}")
        ok = ok and present
    if not ok:
        sys.exit(1)
    print("      ALL PRESENT")


def main() -> None:
    parser = argparse.ArgumentParser(description="物化 DSH node 运行时闭包")
    parser.add_argument("--skip-deploy", action="store_true", help="跳过 pnpm deploy(闭包已物化时)")
    args = parser.parse_args()

    if not DSH_ROOT.is_dir():
        sys.exit(f"[fatal] DSH 仓库不存在: {DSH_ROOT}")
    if not args.skip_deploy:
        run_pnpm_deploy()
    else:
        if not STAGING.is_dir():
            sys.exit(f"[fatal] staging 不存在,不能 --skip-deploy: {STAGING}")
    restore_deepseek_ai()
    verify()
    print("== 完成 ==")


if __name__ == "__main__":
    main()
