"""启动前依赖自检：以 requirements.txt 为准，报告缺失的发行包。

为什么需要它
------------
start-dev.bat 原先只硬编码检查 8 个模块（fastapi/uvicorn/yaml/...），
导致其余已声明的依赖缺失时"检查通过、应用照常启动"——表现为能力静默降级：
  · qrcode 缺失    -> 微信扫码登录直接报错
  · trafilatura 缺失 -> 新闻简报抓正文整层静默跳过（被 try/except 兜住，无报错）
两者都是"不崩但坏"，最难排查。改成读 requirements.txt，新增依赖自动纳入检查。

用法
----
    python tools/check_venv_deps.py                        # 报告缺失，缺则退出码 1
    python tools/check_venv_deps.py --quiet                # 全部就绪时不输出
    python tools/check_venv_deps.py --log logs/startup-env.log

输出约定
--------
控制台一律 ASCII——Windows 控制台默认 GBK，输出中文会乱码。
需要中文可读记录时用 --log 写 UTF-8 文件（供人事后排查）。

这也正是 start-dev.bat 里不能写中文注释的原因：cmd.exe 按系统 ANSI
代码页（此处 GBK）读取 .bat，UTF-8 中文注释会字节错位，cmd 会把注释的
碎片当成命令去执行。凡是给人看的中文记录，都在本脚本里写日志解决。

按发行包（distribution）校验，而非 import 名——pip 名与 import 名不一致时
（例如 pillow -> PIL）用 importlib.metadata 才不会误报。
"""
from __future__ import annotations

import importlib.metadata as md
import re
import sys
from datetime import datetime
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_REQ = _ROOT / "requirements.txt"

# 解析 requirements.txt 的一行，取发行包名。
# 覆盖：pip 名、extras（qrcode[pil]）、版本限定（foo==1.0 / foo>=2）、
# 环境标记（; python_version < "3.9"）、注释与 -r/-e 指令行。
_NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")


def parse_requirements(path: Path) -> list[str]:
    """从 requirements.txt 提取发行包名（保持原顺序，去重）。"""
    if not path.exists():
        return []
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = _NAME_RE.match(line)
        if m:
            name = m.group(1)
            if name not in names:
                names.append(name)
    return names


def find_missing(names: list[str]) -> list[str]:
    """返回未安装的发行包名（按 requirements 原顺序）。"""
    missing: list[str] = []
    for name in names:
        try:
            md.version(name)
        except md.PackageNotFoundError:
            missing.append(name)
        except Exception:
            # 元数据损坏等异常按"不可用"处理：宁可提示，也不要漏报
            missing.append(name)
    return missing


def _arg_value(flag: str) -> str | None:
    """取 `--flag value` 形式的参数值。"""
    if flag in sys.argv:
        idx = sys.argv.index(flag)
        if idx + 1 < len(sys.argv):
            return sys.argv[idx + 1]
    return None


def append_log(path: Path, venv: str, total: int, missing: list[str]) -> None:
    """追加一条 UTF-8 记录，供事后排查（控制台不留中文，日志留）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status = "OK" if not missing else f"缺失 {len(missing)} 项"
        line = (
            f"[{ts}] 依赖自检 {status}"
            f"（{total - len(missing)}/{total}）venv={venv}"
        )
        if missing:
            line += " 缺失=" + ",".join(missing)
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(line + "\n")
    except Exception as exc:  # noqa: BLE001
        print(f"[check_venv_deps] WARN: cannot write log: {type(exc).__name__}")


def main() -> int:
    quiet = "--quiet" in sys.argv
    log_path = _arg_value("--log")
    venv_hint = _arg_value("--venv") or ""

    if not _REQ.exists():
        print(f"[check_venv_deps] FAIL: requirements.txt not found: {_REQ}")
        return 1

    names = parse_requirements(_REQ)
    if not names:
        print("[check_venv_deps] FAIL: no dependency parsed from requirements.txt")
        return 1

    missing = find_missing(names)

    if log_path:
        append_log(Path(log_path), venv_hint, len(names), missing)

    if not missing:
        if not quiet:
            print(f"[check_venv_deps] OK: {len(names)}/{len(names)} deps ready")
        return 0

    print(
        f"[check_venv_deps] MISSING {len(missing)}/{len(names)}: "
        + ",".join(missing)
    )
    print("[check_venv_deps] these cause SILENT capability loss, run:")
    print(f'    "{sys.executable}" -m pip install -r "{_REQ}"')
    return 1


if __name__ == "__main__":
    sys.exit(main())
