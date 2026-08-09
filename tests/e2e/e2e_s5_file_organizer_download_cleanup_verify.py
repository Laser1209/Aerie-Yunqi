"""Aerie v13.9 · 下载清理验证（哈希去重 + mtime 过期清理）

验证项：
  D1 find_duplicates 定位重复文件（同大小 + 部分指纹 + 全文哈希）
  D2 preview_dedup 去重计划：每组保留最新，多余移入回收目录
  D3 preview_expired_cleanup 过期计划：按 mtime 清理 N 天未使用文件
  D4 preview_downloads_cleanup 合并计划（去重 + 过期）
  D5 execute_cleanup 执行 + undo 可回滚
  D6 file_dedup / file_cleanup 工具注册并可调用
"""

from __future__ import annotations
import os
import sys
import time
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.file_organizer import FileOrganizer, CleanupPlan  # noqa: E402


def _make_download_dir() -> Path:
    """构造下载目录：含重复图片、过期文件、近期文件。"""
    root = Path(tempfile.mkdtemp(prefix="aerie_clean_"))
    # 两组完全相同的文件（重复）
    for name in ("a.png", "b.png"):
        (root / name).write_bytes(b"IMAGE-BYTES" * 128)
    for name in ("x.zip", "y.zip"):
        (root / name).write_bytes(b"ARCHIVE-DATA" * 256)
    # 一个过期文件（45 天前修改）
    stale = root / "stale.txt"
    stale.write_bytes(b"old")
    os.utime(stale, (time.time() - 45 * 86400,) * 2)
    # 一个近期文件（不应被清理）
    (root / "recent.txt").write_bytes(b"fresh")
    return root


def d1_find_duplicates() -> tuple[bool, str]:
    root = _make_download_dir()
    try:
        org = FileOrganizer(undo_log_dir=str(root / "undo"))
        groups = org.find_duplicates(str(root), recursive=False)
        # 应有两组重复（png 一组、zip 一组）
        ok = len(groups) == 2
        sizes = {g["count"] for g in groups}
        # 每组 2 个文件
        ok = ok and sizes == {2}
        return ok, f"groups={len(groups)}, counts={sorted(sizes)}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def d2_preview_dedup() -> tuple[bool, str]:
    root = _make_download_dir()
    try:
        org = FileOrganizer(undo_log_dir=str(root / "undo"))
        plan = org.preview_dedup(str(root), recursive=False)
        ok = isinstance(plan, CleanupPlan)
        # 每组保留 1 份，多余 2 个（png、zip 各移走 1）
        ok = ok and plan.total_files == 2
        ok = ok and plan.actions and len(plan.actions) == 2
        # 预览后源文件仍在（dry-run）
        ok = ok and (root / "a.png").exists() and (root / "b.png").exists()
        return ok, f"actions={len(plan.actions)}, moved={plan.summary.get('duplicate_files')}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def d3_preview_expired() -> tuple[bool, str]:
    root = _make_download_dir()
    try:
        org = FileOrganizer(undo_log_dir=str(root / "undo"))
        plan = org.preview_expired_cleanup(str(root), older_than_days=30, recursive=False)
        ok = isinstance(plan, CleanupPlan)
        # 仅 stale.txt 过期（1 个）
        ok = ok and plan.total_files == 1
        ok = ok and len(plan.actions) == 1
        ok = ok and "stale.txt" in plan.actions[0].source
        # 近期文件不应被清理
        ok = ok and not any("recent.txt" in a.source for a in plan.actions)
        return ok, f"expired={plan.summary.get('expired_files')}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def d4_preview_downloads() -> tuple[bool, str]:
    root = _make_download_dir()
    try:
        org = FileOrganizer(undo_log_dir=str(root / "undo"))
        plan = org.preview_downloads_cleanup(str(root), older_than_days=30, recursive=False)
        ok = isinstance(plan, CleanupPlan)
        # 去重 2 + 过期 1 = 3 个动作
        ok = ok and len(plan.actions) == 3
        ok = ok and plan.kind == "downloads"
        return ok, f"actions={len(plan.actions)}, dedup={plan.summary['dedup'].get('duplicate_files')}, expired={plan.summary['expired'].get('expired_files')}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def d5_execute_and_undo() -> tuple[bool, str]:
    root = _make_download_dir()
    try:
        org = FileOrganizer(undo_log_dir=str(root / "undo"))
        plan = org.preview_downloads_cleanup(str(root), older_than_days=30, recursive=False)
        ok, msg, undo_id = org.execute_cleanup(plan, description="下载清理测试")
        ok_all = ok and bool(undo_id)
        # 执行后：每组重复移走 1 个，过期文件移走
        dup_moved = ((not (root / "a.png").exists() or not (root / "b.png").exists())
                     and (not (root / "x.zip").exists() or not (root / "y.zip").exists()))
        stale_moved = not (root / "stale.txt").exists()
        ok_all = ok_all and dup_moved and stale_moved

        # 撤销恢复：所有原始文件应回到原位
        ok2, _msg2, count = org.undo(undo_id)
        restored = all((root / n).exists() for n in ("a.png", "b.png", "x.zip", "y.zip", "stale.txt"))
        ok_all = ok_all and ok2 and restored and count >= 3
        return ok_all, f"exec={ok} undo={ok2} restored={count}"
    finally:
        import shutil
        shutil.rmtree(root, ignore_errors=True)


def d6_tools_registered() -> tuple[bool, str]:
    from core.tool_registry import ToolRegistry
    from core.office_tools import register_office_tools
    reg = ToolRegistry()
    register_office_tools(reg)
    names = set(reg.list_names())
    ok = {"file_dedup", "file_cleanup", "file_organize"} <= names
    return ok, f"registered={sorted(names & {'file_dedup', 'file_cleanup', 'file_organize'})}"


def main() -> int:
    tests = [
        d1_find_duplicates,
        d2_preview_dedup,
        d3_preview_expired,
        d4_preview_downloads,
        d5_execute_and_undo,
        d6_tools_registered,
    ]
    print("=" * 60)
    print("Aerie v13.9 · 下载清理验证（去重 + 过期）")
    print("=" * 60)
    passed = 0
    for test in tests:
        ok, detail = test()
        status = "✓" if ok else "✗"
        print(f"  {status} {test.__name__}  {detail}")
        if ok:
            passed += 1
    total = len(tests)
    print("=" * 60)
    print(f"结果: {passed}/{total} 通过")
    print("=" * 60)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
