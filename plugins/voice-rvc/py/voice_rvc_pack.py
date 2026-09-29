"""voice-rvc 功能包 —— RVC 音色转换（CPU torch）。

**当前状态：包契约就绪，权重与移植实现待装配。**

本模块做到的三件事：

1. 顶层**不 import torch**（重库推迟到 `start()`，冷加载约 14s）；
2. 模型缺失 / 移植实现缺失时，工具返回 `{"status": "unavailable", ...}` 并说清
   缺哪一步 —— 不假装成功，也不把一个假的"变声结果"塞回链路；
3. `pack.json` / `assets` 已经把发布产物该长什么样写清楚，装配脚本据此校验。

**还缺什么（发布前必须补）**：

- `models/rvc/<voice>.pth` + `models/rvc/<voice>.index`：音色权重；
- `py/rvc_converter.py`：RVC 推理实现（从 `F:\\yvyin\\desktop-agent` 移植；
  该目录不在本仓库，因此这里不复制一份来路不明的实现）。

补上这两样后，`start()` 会自动接管 `companion.voice_service.tts_provider`
（或由核心侧按配置选用），无需改核心代码。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

_CTX: Any = None
_CONVERTER: Optional[Any] = None
_ERROR: str = ""

_MODEL_SUBDIR = "models/rvc"


def _state() -> dict[str, Any]:
    return {"ready": _CONVERTER is not None, "error": _ERROR}


def _unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "error": reason or "变声未就绪",
        "hint": "需要 models/rvc 下的 .pth + .index 音色权重，以及 py/rvc_converter.py 推理实现",
    }


def _model_dir() -> Optional[Path]:
    try:
        if _CTX is None:
            return None
        return Path(_CTX.pack_path(*_MODEL_SUBDIR.split("/")))
    except Exception:
        logger.debug("voice-rvc: 解析模型目录失败", exc_info=True)
        return None


def _load_converter() -> Optional[Any]:
    """移植实现放在包自己的 py/ 下（宿主已注入 sys.path）。"""
    try:
        import rvc_converter  # type: ignore

        return rvc_converter
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice-rvc: rvc_converter 不可用（%s）", exc)
        return None


def start(companion: Any) -> None:
    """惰性加载 torch + 权重；缺权重或缺实现都只记录原因，核心继续跑。"""
    global _CONVERTER, _ERROR

    del companion  # 变声暂不改写语音链路，等权重/实现到位后再挂接

    model_dir = _model_dir()
    if model_dir is None or not model_dir.is_dir():
        _CONVERTER = None
        _ERROR = f"音色权重目录不存在：{_MODEL_SUBDIR}"
        logger.warning("voice-rvc: %s", _ERROR)
        return

    weights = sorted(model_dir.glob("*.pth"))
    if not weights:
        _CONVERTER = None
        _ERROR = f"没有找到 .pth 音色权重：{model_dir}"
        logger.warning("voice-rvc: %s", _ERROR)
        return

    try:
        import torch  # noqa: F401  （冷加载 10s+，只在这一步发生）

        converter = _load_converter()
        if converter is None:
            _CONVERTER = None
            _ERROR = "缺少 py/rvc_converter.py 推理实现（需从移植源装配）"
            logger.warning("voice-rvc: %s", _ERROR)
            return

        _CONVERTER = converter
        _ERROR = ""
        logger.info("voice-rvc: 变声就绪 (torch %s, %d 个权重)", torch.__version__, len(weights))
    except Exception as exc:  # noqa: BLE001
        _CONVERTER = None
        _ERROR = f"{type(exc).__name__}: {exc}"
        logger.warning("voice-rvc: 加载失败（%s）", _ERROR)


def stop() -> None:
    global _CONVERTER
    _CONVERTER = None


def convert_voice(audio_path: str, voice: str = "") -> dict[str, Any]:
    """把一段音频转成目标音色。"""
    if _CONVERTER is None:
        return _unavailable(_ERROR)
    target = Path(str(audio_path or "")).expanduser()
    if not target.is_file():
        return {"error": f"音频文件不存在：{target}"}
    try:
        out = _CONVERTER.convert(str(target), voice=voice)
    except Exception as exc:  # noqa: BLE001
        logger.warning("voice-rvc: 转换失败", exc_info=True)
        return {"status": "error", "error": str(exc)[:300]}
    return {"status": "ok", "output_path": str(out)}


def register(ctx: Any) -> None:
    global _CTX
    _CTX = ctx

    ctx.tool_registry.register(
        "voice_rvc_convert",
        convert_voice,
        {
            "type": "function",
            "function": {
                "name": "voice_rvc_convert",
                "description": "把本机音频文件转成指定音色（RVC 变声，CPU 推理）。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "audio_path": {"type": "string", "description": "输入音频绝对路径"},
                        "voice": {"type": "string", "description": "可选，音色名（对应 models/rvc 下的权重）"},
                    },
                    "required": ["audio_path"],
                },
            },
        },
        provider_hint="text",
        category="utility",
    )
