"""历史图片消息修复脚本。

修复三类历史坏数据（见根因分析）：
  1. LLM 在正文里编造的 ``![图片](http://127.0.0.1:7890/uploads/<假哈希>.png)``
     —— URL 指向的文件不存在，前端渲染成裂图。修复时直接剥离图片语法/
     ``[图片内容]`` 描述，保留剩余正文。
  2. 真实图片但以 markdown 内嵌在正文、attachments 为空（旧本地投递格式）
     —— URL 指向的文件真实存在，重写为结构化附件（与 QQ 通道一致），
     正文改为 ``[图片] 描述``；双表（chat_log / messages）同步更新。
  3. chat_log 有记录但 messages 缺 normalized 行的旧消息
     —— 重启后从历史接口随机消失。复用 core.conversation_backfill 的既有
     逻辑补齐，不重写轮次/会话推断。

用法:
  python scripts/repair_image_messages.py             # 默认 dry-run，只打印
  python scripts/repair_image_messages.py --apply     # 真正写库

注意：--apply 前请先停掉后端，避免 SQLite 写锁冲突。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.conversation_backfill import backfill_chat_log  # noqa: E402
from core.image_output_guard import rewrite_image_content  # noqa: E402

# 正文里出现图片语法或图片占位的行才扫描，避免全表逐条做文件 IO
_SUSPECT_WHERE = "content LIKE '%![%' OR content LIKE '%[图片%'"


def _merge_attachments(
    existing_raw: str | None,
    new_attachments: list[dict[str, Any]],
    uploads_root: Path,
) -> str | None:
    """合并旧附件与新解析出的真实图片附件，顺手剔除指向死文件的图片附件。

    历史上 attachments 列可能存着真实文件（QQ 通道）或与正文同源的假 URL，
    这里以"文件真实存在"为唯一采信标准，按 url 去重保序。
    """
    merged: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def _take(record: dict[str, Any]) -> None:
        url = str(record.get("url") or record.get("thumbnail_url") or "").strip()
        category = str(record.get("category") or record.get("type") or "").lower()
        if url in seen_urls:
            return
        # 只对 uploads 下的图片做存活性校验；其他类型/外链附件原样保留
        if category == "image" and url.startswith("/uploads/"):
            rel = url[len("/uploads/"):]
            if not (uploads_root / rel).is_file():
                return
        seen_urls.add(url)
        merged.append(record)

    if existing_raw:
        try:
            existing = json.loads(existing_raw)
        except (ValueError, TypeError):
            existing = None
        if isinstance(existing, list):
            for record in existing:
                if isinstance(record, dict):
                    _take(record)
    for record in new_attachments:
        _take(record)

    return json.dumps(merged, ensure_ascii=False) if merged else None


def _repair_table(
    conn: sqlite3.Connection,
    table: str,
    id_column: str,
    uploads_root: Path,
    apply: bool,
) -> dict[str, int]:
    """修复单表（chat_log 或 messages），返回计数。"""
    stats = {"scanned": 0, "fixed": 0, "fake_stripped": 0, "real_attachments": 0}
    rows = conn.execute(
        f"SELECT {id_column} AS row_id, content, attachments FROM {table} "
        f"WHERE {_SUSPECT_WHERE} ORDER BY {id_column} ASC",
    ).fetchall()
    stats["scanned"] = len(rows)
    for row in rows:
        old_content = row["content"] or ""
        rewritten_content, parsed_real_images, content_changed = rewrite_image_content(
            old_content, uploads_root,
        )
        new_attachments_json = _merge_attachments(
            row["attachments"], parsed_real_images, uploads_root,
        )
        changed = content_changed or (row["attachments"] or None) != new_attachments_json
        if not changed:
            continue
        if content_changed:
            if parsed_real_images:
                stats["real_attachments"] += 1
            else:
                stats["fake_stripped"] += 1
        stats["fixed"] += 1
        new_content = rewritten_content
        if apply:
            conn.execute(
                f"UPDATE {table} SET content = ?, attachments = ? "
                f"WHERE {id_column} = ?",
                (new_content, new_attachments_json, row["row_id"]),
            )
    return stats


def main() -> int:
    parser = argparse.ArgumentParser(description="修复历史图片消息（假URL/结构化附件/缺normalized行）")
    parser.add_argument("--db", default=os.path.join(_REPO_ROOT, "data", "aerie.db"))
    parser.add_argument("--uploads", default=os.path.join(_REPO_ROOT, "uploads"))
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写库；缺省为 dry-run 只打印修复计划",
    )
    args = parser.parse_args()

    db_path = Path(args.db)
    uploads_root = Path(args.uploads).resolve()
    if not db_path.is_file():
        print(f"[ERROR] 数据库不存在: {db_path}")
        return 1
    if not uploads_root.is_dir():
        print(f"[ERROR] uploads 目录不存在: {uploads_root}")
        return 1

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"[{mode}] db={db_path}")
    print(f"[{mode}] uploads={uploads_root}")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 1) 先修 chat_log（backfill 会读取修好后的内容生成 messages 行）
        log_stats = _repair_table(conn, "chat_log", "id", uploads_root, args.apply)
        # 2) 再修 messages（QQ/请求路径写入的 normalized 行不在 chat_log 修复范围内）
        msg_stats = _repair_table(conn, "messages", "message_id", uploads_root, args.apply)

        # 3) 补齐缺失的 normalized 行
        if args.apply:
            backfill_result = backfill_chat_log(conn)
            backfilled = int(backfill_result.get("inserted", 0))
        else:
            # dry-run 必须零写入（后端可能在跑，避免抢 SQLite 写锁），
            # 直接统计 chat_log 有、messages 缺的行数
            backfilled = conn.execute(
                "SELECT COUNT(*) FROM chat_log c "
                "WHERE NOT EXISTS (SELECT 1 FROM messages m "
                "                  WHERE m.legacy_chat_log_id = c.id)",
            ).fetchone()[0]

        print(
            f"[{mode}] chat_log: 扫描 {log_stats['scanned']}，修复 {log_stats['fixed']}"
            f"（假URL剥离 {log_stats['fake_stripped']}，真实图片转附件 "
            f"{log_stats['real_attachments']}）"
        )
        print(
            f"[{mode}] messages: 扫描 {msg_stats['scanned']}，修复 {msg_stats['fixed']}"
            f"（假URL剥离 {msg_stats['fake_stripped']}，真实图片转附件 "
            f"{msg_stats['real_attachments']}）"
        )
        print(f"[{mode}] normalized 缺失行补齐: {backfilled}")

        if args.apply:
            conn.commit()
            print("[APPLY] 已提交")
        else:
            conn.rollback()
            print("[DRY-RUN] 未写入，确认无误后加 --apply 执行")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
