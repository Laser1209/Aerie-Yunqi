"""生图画幅决断：场景（prompt_key）→ 像素尺寸档 → 构图方向短语。

三处调用方共用同一份映射，避免"发布方漏填 size 就一路掉到上游默认 1:1"
的隐性降级：

* ``core.companion``：候选发布（主动发图）与提示词组装；
* ``core.pipeline``：聊天要图路径的候选尺寸；
* ``core.llm_caller``：provider 调用前的最后一层兜底（按 ``metadata.prompt_key``）。

独立成模块而不是放在 companion 里，是因为 ``llm_caller`` 被 companion 反向
依赖，直接互引会形成循环导入。
"""

from __future__ import annotations

# 手机拍摄比例。1344x768 ≈ 16:9 横拍、768x1344 ≈ 9:16 竖拍，
# 均满足中转站"边长 512~4096 且为 64 的倍数"的约束；1024x1024 为方图兜底。
IMAGE_SIZE_LANDSCAPE = "1344x768"
IMAGE_SIZE_PORTRAIT = "768x1344"
IMAGE_SIZE_SQUARE = "1024x1024"

# 自拍/人像/合影 → 竖屏；环境/物件/风景 → 横屏。
IMAGE_SIZE_BY_PROMPT_KEY: dict[str, str] = {
    "role_selfie": IMAGE_SIZE_PORTRAIT,
    "role_in_scene": IMAGE_SIZE_PORTRAIT,
    "couple_photo": IMAGE_SIZE_PORTRAIT,
    "environment_object": IMAGE_SIZE_LANDSCAPE,
}


def size_for_prompt_key(prompt_key: str) -> str:
    """按发图场景决断手机拍摄的横竖比例（16:9 / 9:16），即伊塔的构图自决。"""
    return IMAGE_SIZE_BY_PROMPT_KEY.get(str(prompt_key or ""), IMAGE_SIZE_PORTRAIT)


def orientation_phrase(image_size: str) -> str:
    """把尺寸转成写进生图 prompt 的构图方向提示（让生成模型配合构图）。

    方图必须单独成一档：原先 ``width >= height`` 把 1024x1024 也判成
    "横构图（手机横拍 16:9 比例）"—— 提示词说的比例与真正传下去的 size 打架，
    生成模型收到的是一份自相矛盾的指令。
    """
    try:
        width, height = (int(part.strip()) for part in str(image_size).lower().split("x"))
    except (ValueError, AttributeError):
        return "竖构图（手机竖拍 9:16 比例）"
    if width == height:
        return "方构图（手机方图 1:1 比例）"
    if width > height:
        return "横构图（手机横拍 16:9 比例）"
    return "竖构图（手机竖拍 9:16 比例）"
