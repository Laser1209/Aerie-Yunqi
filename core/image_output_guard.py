"""Image artifact guard for assistant text output.

真实图片永远由后台生图链路作为**独立消息 + 结构化附件**送达
(``_deliver_local_chat_image`` / QQ ``send_image``), 文本回复里不允许出现
任何图片语法。但对话历史中真实图片消息长这样::

    [图片] 她的一张自拍

历史消息进入 LLM 上下文后, 模型会模仿"发图"的样子, 在自己的回复正文里编造
``![图片](http://127.0.0.1:7890/uploads/<瞎编哈希>.png)`` 与 ``[图片内容] ...``,
而这些 URL 指向的文件根本不存在, 前端只渲染出裂图图标。仅靠 system prompt
禁止(context_builder)无法稳定拦住, 因此在输出层做确定性剥离。

本模块同时提供历史数据修复用的内容重写函数(rewrite_image_content),
供 scripts/repair_image_messages.py 复用, 不做任何文件 IO 以外的副作用。
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# 任意 markdown 图片: ![任意alt](任意url)
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
# [图片内容] 描述(吃到行尾)
_IMAGE_CONTENT_RE = re.compile(r"[ \t]*\[图片内容\][^\n]*")
# 裸 [图片] / [图片:xxx] 占位符
_BARE_IMAGE_RE = re.compile(r"\[图片(?::[^\]]*)?\]")
# uploads URL 中相对文件路径的提取(绝对 http URL 与相对路径都覆盖)
_UPLOADS_PATH_RE = re.compile(r"^(?:https?://[^/]+)?/uploads/(.+)$", re.IGNORECASE)


def strip_llm_image_artifacts(text: str) -> str:
    """剥离 LLM 回复正文中编造的图片语法与画面描述。

    - ``![图片](...)`` / 任意 markdown 图片 → 删除
    - ``[图片内容] ...`` → 整段删除
    - 裸 ``[图片]`` / ``[图片:...]`` → 删除
    - 表情包标记(``[表情包]``)不动, 那是另一套交付机制
    最后折叠多余空白, 保持正文可读。
    """
    cleaned = str(text or "")
    cleaned = _MARKDOWN_IMAGE_RE.sub("", cleaned)
    cleaned = _IMAGE_CONTENT_RE.sub("", cleaned)
    cleaned = _BARE_IMAGE_RE.sub("", cleaned)
    # 清掉剥离后残留的行首行尾空白与连续空行
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r" *\n *", "\n", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def uploads_relative_path(url: str) -> str:
    """把图片 URL 归一化为 uploads 相对路径; 非 uploads URL 返回空串。"""
    raw = str(url or "").strip()
    if not raw or raw.startswith("data:"):
        return ""
    match = _UPLOADS_PATH_RE.match(raw)
    if not match:
        return ""
    rel = match.group(1).strip("/")
    # 防御路径穿越: 合法资产名不含 .. 和反斜杠
    if "\\" in rel or ".." in rel.split("/"):
        return ""
    return rel


def build_image_attachment(rel_path: str) -> dict[str, Any] | None:
    """根据 uploads 相对路径构造结构化图片附件(与 QQ 通道字段约定一致)。"""
    rel_path = str(rel_path or "").strip().lstrip("/")
    if not rel_path:
        return None
    name = rel_path.rsplit("/", 1)[-1]
    content_type = mimetypes.guess_type(name)[0] or "image/png"
    url = "/uploads/" + rel_path
    return {
        "category": "image",
        "name": name,
        "url": url,
        # 生成图没有独立缩略图, 直接用原图; 前端按 thumbnail→url 顺序回退
        "thumbnail_url": url,
        "content_type": content_type,
    }


def _extract_descriptions(text: str) -> list[str]:
    """收集正文里的 [图片内容] 描述(去重保序), 修复时用于生成 [图片] 行。"""
    descriptions: list[str] = []
    for match in _IMAGE_CONTENT_RE.finditer(str(text or "")):
        desc = re.sub(r"^\s*\[图片内容\]\s*", "", match.group(0)).strip()
        if desc and desc not in descriptions:
            descriptions.append(desc)
    return descriptions


def rewrite_image_content(
    content: str,
    uploads_dir: str | Path,
) -> tuple[str, list[dict[str, Any]], bool]:
    """把一条历史消息里的 markdown 图片重写为结构化附件。

    Returns:
        (new_content, attachments, changed)
        - URL 指向的文件真实存在 → 收进 attachments(相对 URL), 正文剥离图片语法;
          若正文没有剩余有效文字, 用 ``[图片] 描述`` 兜底(与 QQ 通道一致,
          同时给 LLM 上下文保留"这是张什么图")。
        - URL 指向的文件不存在(LLM 编造) → 直接丢弃, 不留裂图。
        - 没有任何 markdown 图片 → 原样返回, changed=False。
    """
    original = str(content or "")
    images = _MARKDOWN_IMAGE_RE.findall(original)
    if not images:
        return original, [], False

    uploads_root = Path(uploads_dir).resolve()
    attachments: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for url in images:
        rel = uploads_relative_path(url)
        if not rel or rel in seen_paths:
            continue
        seen_paths.add(rel)
        asset_path = (uploads_root / rel).resolve()
        try:
            asset_path.relative_to(uploads_root)
        except ValueError:
            continue
        if not asset_path.is_file():
            continue
        attachment = build_image_attachment(rel)
        if attachment:
            attachments.append(attachment)

    descriptions = _extract_descriptions(original)
    # 剥离全部图片语法/画面描述/裸占位
    new_text = strip_llm_image_artifacts(original)

    if attachments and not new_text:
        desc = descriptions[0] if descriptions else "图片"
        new_text = f"[图片] {desc}"

    return new_text, attachments, True
