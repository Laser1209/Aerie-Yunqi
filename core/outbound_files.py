"""把本地文件发布到 uploads 目录，供桌面端下载/打开。

**为什么需要它**

本机三端里，QQ 与微信都有原生"发文件"能力（`QQClient.send_file` /
`iLinkGateway.send_file`），但**桌面端没有**：`SendQueue` 只注册了 qq / ilink
两个通道发送器，桌面端（`local_chat`）只有文本与图片通道。于是"在桌面端让
Agent 发个文件给你"这条需求长期只能静默丢件（§十四 #72）。

桌面端展示文件的机制已经存在且成熟：**生成图就是走 `/uploads/<rel>`** ——
后端 `GET /uploads/{filename:path}` 负责安全地送出文件，前端把结构化附件
渲染成卡片。这里复用同一条路：把要发的文件复制进 uploads，得到一个相对路径，
再交给聊天记录当附件。

**为什么不走附件中心（`core.desktop_attachments`）**

那一套是给**用户上传**设计的：要过 Defender 扫描、再起子进程做内容抽取，
状态是 queued → processing → ready。把它用在外发文件上，会拿杀毒软件去扫
我们自己刚生成的文件（可能被误隔离），还要等一轮解析，语义与成本都不对。

**信任方向**：这里的文件来源是 Agent 自己生成或用户已授权目录内的文件
（`send_file_to_user` 已先过 `_resolve_write_target` 白名单），不对外来输入做二次检疫。
"""
from __future__ import annotations

import logging
import mimetypes
import shutil
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _uploads_dir() -> Path:
    """uploads 目录的单一真源：优先取 api_server 的常量，取不到才回落。

    懒导入的原因：`core.api_server` 体量很大（FastAPI app + 大量端点），
    在模块顶层导入会让本模块的调用方被它拖住，也平添循环导入风险。
    """
    try:
        from core.api_server import UPLOAD_DIR

        return Path(UPLOAD_DIR).resolve()
    except Exception:  # noqa: BLE001
        logger.debug("api_server.UPLOAD_DIR 不可用，回落到 cwd/uploads", exc_info=True)
        return (Path.cwd() / "uploads").resolve()


def publish_to_uploads(source: str | Path) -> str | None:
    """把 ``source`` 复制进 uploads，返回其相对路径（如 ``"a1b2c3.txt"``）。

    文件名用 uuid 重写（与图片上传同口径）：避免同名覆盖，也避免把用户目录结构
    泄漏到对外 URL 里。复制失败返回 None —— 调用方应如实报"没发出去"，
    绝不静默当成功。
    """
    src = Path(source)
    if not src.is_file():
        return None
    try:
        root = _uploads_dir()
        root.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}{src.suffix.lower()}"
        shutil.copyfile(src, root / name)
        return name
    except OSError:
        logger.warning("发布文件到 uploads 失败: %s", source, exc_info=True)
        return None


def build_file_attachment(
    rel_path: str,
    *,
    display_name: str = "",
    size_bytes: int | None = None,
) -> dict[str, Any] | None:
    """构造桌面端可渲染的**文件**附件描述（与图片附件同族，字段按前端约定）。

    前端 `chat.js::_buildAttachmentCard` 的非图片分支消费的字段是
    ``category / name / size / extension / state``；桌面端打开走 ``url``
    （生成图那条路的同款直链，见该函数的 image 分支）。
    ``display_name`` 保留原始文件名 —— uploads 里存的是 uuid 名，
    用户看到的必须是原名。
    """
    rel = str(rel_path or "").strip().lstrip("/")
    if not rel:
        return None
    stored_name = rel.rsplit("/", 1)[-1]
    name = str(display_name or stored_name).strip() or stored_name
    extension = Path(name).suffix.lower().lstrip(".")
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    attachment: dict[str, Any] = {
        "category": "file",
        "name": name,
        "url": "/uploads/" + rel,
        "content_type": content_type,
        "extension": extension,
        # "ready" 才会渲染出「打开」按钮（见前端 _buildAttachmentCard）。
        "state": "ready",
    }
    if size_bytes is not None:
        attachment["size"] = int(size_bytes)
    return attachment
