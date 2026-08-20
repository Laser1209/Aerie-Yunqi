"""OneBot11 消息段（segment）构造工具（自研实现）。

OneBot11 消息数组的每个元素形如 ``{"type": ..., "data": {...}}``。
本模块提供类型安全的段构造器，业务层组装富文本消息时统一从这里取，
避免手写字典时 key 拼写错误。

典型用法::

    segments = [
        reply(msg_id),
        text("我在呢"),
        image("file:///C:/tmp/photo.png"),
    ]
"""

from __future__ import annotations


def text(content: str) -> dict:
    """纯文本段。"""
    return {"type": "text", "data": {"text": str(content or "")}}


def image(file: str) -> dict:
    """图片段。``file`` 支持本地绝对路径 / ``file://`` / http(s) URL / base64。"""
    return {"type": "image", "data": {"file": str(file)}}


def record(file: str, magic: bool = False) -> dict:
    """语音段。``file`` 为本地路径或 URL；``magic`` 为变声（若引擎支持）。"""
    data: dict = {"file": str(file)}
    if magic:
        data["magic"] = 1
    return {"type": "record", "data": data}


def video(file: str) -> dict:
    """视频段。"""
    return {"type": "video", "data": {"file": str(file)}}


def reply(message_id: int) -> dict:
    """回复段，指向要引用的平台消息 id。"""
    return {"type": "reply", "data": {"id": int(message_id)}}


def face(face_id: int) -> dict:
    """QQ 内置表情段。"""
    return {"type": "face", "data": {"id": int(face_id)}}


def mface(url: str = "", summary: str = "", emoji_id: str = "") -> dict:
    """商城表情段。``summary`` 是引擎返回的简短描述，用于转写。"""
    data: dict = {}
    if url:
        data["url"] = str(url)
    if summary:
        data["summary"] = str(summary)
    if emoji_id:
        data["emoji_id"] = str(emoji_id)
    return {"type": "mface", "data": data}


def at(qq: int | str) -> dict:
    """@某人。``qq`` 为 0/``"all"`` 时 @全体成员（需管理员权限）。"""
    return {"type": "at", "data": {"qq": str(qq)}}


def forward(message_id: int) -> dict:
    """合并转发段（引用已生成的转发消息 id）。"""
    return {"type": "forward", "data": {"id": int(message_id)}}


def json_custom(data: dict | str) -> dict:
    """JSON 卡片段（小程序/富卡片）。"""
    payload = data if isinstance(data, str) else _compact_json(data)
    return {"type": "json", "data": {"data": payload}}


def _compact_json(data: dict) -> str:
    import json

    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def to_cq(segments: list[dict]) -> str:
    """把段数组转成 CQ 码字符串（兼容纯文本通道的兜底）。

    仅用于需要字符串渲染的场景（如日志、文本兜底）；真实发送一律用段数组。
    """
    parts: list[str] = []
    for seg in segments:
        seg_type = seg.get("type")
        data = seg.get("data") or {}
        if seg_type == "text":
            parts.append(str(data.get("text", "")))
        else:
            kv = ",".join(f"{k}={v}" for k, v in data.items())
            parts.append(f"[CQ:{seg_type},{kv}]" if kv else f"[CQ:{seg_type}]")
    return "".join(parts)
