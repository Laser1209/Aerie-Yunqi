"""防回归：`plugins/` 与 `models/` 绝不能进安装包。

用户明确要求功能包走自己的网站分发（下载 `.aeriepack` 后在模块中心安装），
所以这两个目录**只能在开发态存在**，一旦被 electron-builder 打进安装包：

- 安装包会平白胖 1~2 GB；
- "核心精简、能力按需下载"这条架构前提当场失效；
- 用户卸载重装时会得到一份自己没下载过的模型。

这条约束以前只是口头约定，没有任何守卫 —— 这里把它钉死。
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parent.parent
_BUILDER_YML = _ROOT / "electron" / "electron-builder.yml"

# 不允许出现在打包白名单里的目录名（按路径段匹配，避免误伤 models_xxx 之类）
_FORBIDDEN_SEGMENTS = ("plugins", "models")


def _config() -> dict:
    return yaml.safe_load(_BUILDER_YML.read_text(encoding="utf-8")) or {}


def _segments(pattern: str) -> set[str]:
    """把 glob 模式拆成路径段集合，忽略 `../`、`**`、`!` 等噪声。"""
    text = str(pattern or "").replace("\\", "/")
    if text.startswith("!"):
        text = text[1:]
    parts = [p for p in text.split("/") if p and p not in ("..", ".", "**")]
    return {p.replace("**", "").strip("*") for p in parts if p.strip("*")}


def test_extra_resources_do_not_point_at_plugins_or_models():
    for entry in _config().get("extraResources") or []:
        if not isinstance(entry, dict):
            continue
        for key in ("from", "to"):
            segs = _segments(entry.get(key, ""))
            bad = segs & set(_FORBIDDEN_SEGMENTS)
            assert not bad, (
                f"extraResources[{key}={entry.get(key)!r}] 命中禁用目录 {sorted(bad)}；"
                "plugins/ 与 models/ 必须走外载分发"
            )


def test_source_filter_allowlist_excludes_plugins_and_models():
    """`../` → python 的 filter 是**白名单**：逐条断言没有 plugins/models 段。"""
    filtered: list[dict] = [
        entry
        for entry in (_config().get("extraResources") or [])
        if isinstance(entry, dict) and entry.get("filter")
    ]
    assert filtered, "打包配置里应存在带 filter 的源码 extraResource"

    for entry in filtered:
        for pattern in entry["filter"]:
            segs = _segments(pattern)
            assert not (segs & set(_FORBIDDEN_SEGMENTS)), (
                f"源码白名单 {pattern!r} 命中禁用目录；"
                "把 plugins/ 或 models/ 加回安装包会破坏外载分发模型"
            )


def test_forbidden_segment_matching_is_not_overzealous():
    """守卫本身不能误伤：`core/`、`tools/`、`config/` 等必须判定为放行。"""
    for ok in ("main.py", "core/**", "tools/**", "config/**", "skills/**"):
        assert not (_segments(ok) & set(_FORBIDDEN_SEGMENTS)), ok

    # 单复数/前后缀不误伤（models_legacy 不是 models）
    assert not (_segments("core/models_legacy/**") & set(_FORBIDDEN_SEGMENTS))
    assert _segments("plugins/**") & set(_FORBIDDEN_SEGMENTS)
    assert _segments("models/**") & set(_FORBIDDEN_SEGMENTS)
