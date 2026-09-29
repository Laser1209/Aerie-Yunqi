"""功能包装配与校验 —— 把 `plugins/<id>/` 打成可分发的 `.aeriepack`。

用法（从仓库根运行）：

    python scripts/build_plugin_pack.py --pack knowledge          # 装配单个包
    python scripts/build_plugin_pack.py --all                     # 装配全部已就绪的包
    python scripts/build_plugin_pack.py --verify dist/x.aeriepack # 校验（篡改必被发现）
    python scripts/build_plugin_pack.py --pack knowledge --emit-catalog-entry

产物形态（zip 结构，pack.json 在根）：

    pack.json
    py/...
    vendor/...            # 可选
    models/...            # 可选
    bin/...               # 可选
    SHA256SUMS            # 每个文件的 sha256（相对路径 + 两空格 + 摘要）

为什么单独写一个脚本：`plugins/` 与 `models/` 都不进安装包（见 `plugins/README.md`），
发布物是"装配出来的"而不是"提交进仓库的"。装配过程必须可复现、可校验 ——
下载器只认 SHA256，装错一个字节就等于装了个来源不明的东西。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
PLUGINS_ROOT = ROOT / "plugins"
DIST_ROOT = ROOT / "dist"

# 打进包的内容目录（pack.json 单独处理，必须在根）。
_CONTENT_DIRS = ("py", "vendor", "models", "bin")
# 装配时忽略的噪声。
_IGNORED = {"__pycache__", ".pytest_cache", ".git"}
_IGNORED_SUFFIX = (".pyc", ".pyo")

SUMS_NAME = "SHA256SUMS"


class PackError(RuntimeError):
    """装配/校验失败（消息面向使用者，不带堆栈）。"""


# ── 基础工具 ─────────────────────────────────────────────

def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _iter_files(base: Path) -> Iterable[Path]:
    """枚举要打包的文件（相对 base，已过滤噪声），按路径排序保证可复现。"""
    out: list[Path] = []
    for sub in _CONTENT_DIRS:
        root = base / sub
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if any(part in _IGNORED for part in path.parts):
                continue
            if path.suffix in _IGNORED_SUFFIX:
                continue
            out.append(path)
    return sorted(out, key=lambda p: p.as_posix())


def load_manifest(pack_dir: Path) -> dict[str, Any]:
    manifest_path = pack_dir / "pack.json"
    if not manifest_path.is_file():
        raise PackError(f"{pack_dir.name}: 缺少 pack.json")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PackError(f"{pack_dir.name}: pack.json 解析失败：{exc}") from exc
    if not str(manifest.get("id") or "").strip():
        raise PackError(f"{pack_dir.name}: pack.json 缺少 id")
    return manifest


def pack_name(manifest: dict[str, Any]) -> str:
    return f"{manifest['id']}-{manifest.get('version') or '0.0.0'}.aeriepack"


# ── 装配 ────────────────────────────────────────────────

def build_pack(pack_id: str, *, dist: Path = DIST_ROOT) -> Path:
    """装配单个包，返回产物路径。"""
    pack_dir = PLUGINS_ROOT / pack_id
    if not pack_dir.is_dir():
        raise PackError(f"包目录不存在：{pack_dir}")

    manifest = load_manifest(pack_dir)
    if str(manifest["id"]) != pack_id:
        raise PackError(
            f"{pack_id}: pack.json 的 id 是 {manifest['id']!r}，必须与目录名一致"
        )

    files = list(_iter_files(pack_dir))
    if not files:
        raise PackError(f"{pack_id}: 没有任何内容可打包（缺少 py/ 等目录）")
    if not (pack_dir / "py").is_dir():
        raise PackError(f"{pack_id}: 缺少 py/ 目录（宿主靠它注入 sys.path）")

    sums_lines = [
        f"{_sha256(path)}  {path.relative_to(pack_dir).as_posix()}" for path in files
    ]

    dist.mkdir(parents=True, exist_ok=True)
    target = dist / pack_name(manifest)

    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(pack_dir / "pack.json", "pack.json")
        for path in files:
            zf.write(path, path.relative_to(pack_dir).as_posix())
        zf.writestr(SUMS_NAME, "\n".join(sums_lines) + "\n")

    return target


# ── 校验（篡改检测）────────────────────────────────────

def verify_pack(archive: Path) -> dict[str, Any]:
    """校验 .aeriepack：清单、逐文件 SHA256、且不得有未登记文件。"""
    if not archive.is_file():
        raise PackError(f"产物不存在：{archive}")

    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        if "pack.json" not in names:
            raise PackError("包内缺少 pack.json")
        if SUMS_NAME not in names:
            raise PackError(f"包内缺少 {SUMS_NAME}（无法证明完整性）")

        manifest = json.loads(zf.read("pack.json").decode("utf-8"))
        sums = _parse_sums(zf.read(SUMS_NAME).decode("utf-8"))

        listed = set(sums)
        present = {n for n in names if n not in ("pack.json", SUMS_NAME)}
        unlisted = sorted(present - listed)
        missing = sorted(listed - present)
        if unlisted:
            raise PackError(f"包内有未登记文件（疑似被塞入）：{unlisted[:5]}")
        if missing:
            raise PackError(f"清单里列了但包里没有：{missing[:5]}")

        for rel, expected in sums.items():
            actual = hashlib.sha256(zf.read(rel)).hexdigest()
            if actual != expected:
                raise PackError(
                    f"文件被篡改：{rel}\n  期望 {expected}\n  实际 {actual}"
                )

    return {
        "id": manifest.get("id"),
        "version": manifest.get("version"),
        "files": len(sums),
        "size_bytes": archive.stat().st_size,
    }


def _parse_sums(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        digest, _, rel = line.partition("  ")
        if not rel:
            raise PackError(f"{SUMS_NAME} 行格式不对：{line!r}")
        out[rel] = digest
    return out


# ── catalog 条目 ────────────────────────────────────────

def emit_catalog_entry(pack_id: str, archive: Path) -> dict[str, Any]:
    manifest = load_manifest(PLUGINS_ROOT / pack_id)
    info = verify_pack(archive)
    return {
        "id": manifest["id"],
        "available": True,
        "sizeMb": round(info["size_bytes"] / (1024 * 1024), 1),
        "api_level": manifest.get("api_level"),
        "min_core": manifest.get("min_core"),
        "restart_required": bool(manifest.get("restart_required", True)),
        "urls": [],                 # 上传到对象存储后回填
        "sha256": _sha256(archive),
    }


# ── CLI ─────────────────────────────────────────────────

def _ready_packs() -> list[str]:
    """只装配"有 py/ 入口"的包；空壳（只有 requirements.txt）跳过并说明。"""
    ready: list[str] = []
    for entry in sorted(PLUGINS_ROOT.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        if (entry / "pack.json").is_file() and (entry / "py").is_dir():
            ready.append(entry.name)
    return ready


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pack", help="要装配的包 id")
    parser.add_argument("--all", action="store_true", help="装配全部就绪的包")
    parser.add_argument("--verify", help="校验一个 .aeriepack")
    parser.add_argument("--emit-catalog-entry", action="store_true",
                        help="输出可直接粘进 plugin-catalog.json 的条目")
    parser.add_argument("--dist", default=str(DIST_ROOT), help="产物输出目录")
    ns = parser.parse_args(argv)

    try:
        if ns.verify:
            info = verify_pack(Path(ns.verify))
            print(f"OK — {info['id']}@{info['version']}，{info['files']} 个文件，"
                  f"{info['size_bytes']} 字节")
            return 0

        targets = _ready_packs() if ns.all else ([ns.pack] if ns.pack else [])
        if not targets:
            print("没指定要装配的包（用 --pack <id> 或 --all）")
            skipped = [p.name for p in sorted(PLUGINS_ROOT.iterdir())
                       if p.is_dir() and p.name not in _ready_packs()
                       and not p.name.startswith(".")]
            if skipped:
                print(f"跳过（缺 pack.json 或 py/）：{', '.join(skipped)}")
            return 2

        for pack_id in targets:
            archive = build_pack(pack_id, dist=Path(ns.dist))
            info = verify_pack(archive)
            print(f"built {archive.relative_to(ROOT)} "
                  f"({info['files']} files, {info['size_bytes']} bytes)")
            if ns.emit_catalog_entry:
                print(json.dumps(emit_catalog_entry(pack_id, archive), ensure_ascii=False, indent=2))
        return 0
    except PackError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
