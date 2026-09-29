"""指令型 skill 的上下文注入（§十六 / 用户 2026-09-29 拍板）。

指令型 skill（brainstorming / writing-plans / test-driven-development …）本质是
**提示词 / 工作流文档**，不是可调用的函数。做成本事有两件：
  1. 它们**不注册为工具**（否则模型会去"调用一篇文档"）；
  2. 命中相关请求时把方法论**注入 system prompt**。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core.skill_instructions import (
    MAX_INSTRUCTION_CHARS,
    SkillInstructionIndex,
)
from core.skill_loader import SkillLoader
from core.skill_router import SkillRouter
from core.tool_registry import ToolRegistry

INSTRUCTION_BATCH_1 = ("brainstorming", "writing-plans", "test-driven-development")


def _write_instruction_skill(root: Path, dir_name: str, name: str, **front) -> Path:
    skill_dir = root / dir_name
    skill_dir.mkdir(parents=True)
    lines = ["---", f"name: {name}", "description: demo", "kind: instruction"]
    triggers = front.get("triggers")
    if triggers is not None:
        lines.append("triggers:")
        lines.extend(f"- {t}" for t in triggers)
    lines.append("---")
    lines.append("")
    lines.append(front.get("body", f"{name} 的指令正文"))
    (skill_dir / "SKILL.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return skill_dir


# ── 发现 ──────────────────────────────────────────────────────────────


def test_real_instruction_skills_are_discovered():
    """仓库里第一批指令型 skill 必须能被索引到（否则注入永不发生）。"""
    index = SkillInstructionIndex()
    index.discover()

    names = set(index.names)
    missing = [n for n in INSTRUCTION_BATCH_1 if n not in names]
    assert not missing, f"这些指令型 skill 没被索引到：{missing}"


def test_only_kind_instruction_is_indexed(tmp_path):
    """工具型 skill 不进指令索引（两条路互斥）。"""
    root = tmp_path / "cloud"
    _write_instruction_skill(root, "a", "ins-a", triggers=["甲"])
    tool_dir = root / "b"
    tool_dir.mkdir()
    (tool_dir / "SKILL.md").write_text(
        "---\nname: tool-b\ndescription: d\n---\n\n正文\n", encoding="utf-8",
    )

    index = SkillInstructionIndex(roots=((root, "cloud"),))
    assert index.discover() == 1
    assert index.names == ["ins-a"]


def test_skill_without_triggers_is_indexed_but_never_matches(tmp_path):
    """漏写 triggers 属于配置疏漏：仍可被发现（便于排查），但永不命中。"""
    root = tmp_path / "cloud"
    _write_instruction_skill(root, "a", "no-trigger", body="正文")

    index = SkillInstructionIndex(roots=((root, "cloud"),))
    assert index.discover() == 1
    assert index.match("随便说点什么") == []


def test_skill_with_empty_body_is_skipped(tmp_path):
    root = tmp_path / "cloud"
    _write_instruction_skill(root, "a", "empty", triggers=["甲"], body="")

    index = SkillInstructionIndex(roots=((root, "cloud"),))
    assert index.discover() == 0


# ── 匹配与注入 ────────────────────────────────────────────────────────


def test_match_is_case_insensitive_and_keyword_based(tmp_path):
    root = tmp_path / "cloud"
    _write_instruction_skill(root, "a", "ins-a", triggers=["TDD", "红绿重构"])

    index = SkillInstructionIndex(roots=((root, "cloud"),))
    index.discover()

    assert [i.name for i in index.match("我们按 tdd 来吧")] == ["ins-a"]
    assert [i.name for i in index.match("讲讲红绿重构")] == ["ins-a"]
    assert index.match("今天天气不错") == []


def test_build_block_returns_empty_without_match(tmp_path):
    root = tmp_path / "cloud"
    _write_instruction_skill(root, "a", "ins-a", triggers=["甲"])
    index = SkillInstructionIndex(roots=((root, "cloud"),))
    index.discover()

    assert index.build_block("完全不相关的话") == ""


def test_build_block_wraps_body_with_purpose_header(tmp_path):
    root = tmp_path / "cloud"
    _write_instruction_skill(root, "a", "ins-a", triggers=["甲"], body="第一步：复述需求")
    index = SkillInstructionIndex(roots=((root, "cloud"),))
    index.discover()

    block = index.build_block("帮我做甲这件事")

    assert block.startswith("[技能指令]")
    assert "### ins-a" in block
    assert "第一步：复述需求" in block


def test_build_block_truncates_long_instructions(tmp_path):
    root = tmp_path / "cloud"
    _write_instruction_skill(
        root, "a", "ins-a", triggers=["甲"], body="很长" * MAX_INSTRUCTION_CHARS,
    )
    index = SkillInstructionIndex(roots=((root, "cloud"),))
    index.discover()

    block = index.build_block("甲")

    assert len(block) < MAX_INSTRUCTION_CHARS + 200      # 头部/标记之外的正文被截断
    assert "已截断" in block


def test_match_limits_number_of_hits(tmp_path):
    """命中过多会互相干扰，也让 system prompt 失控 —— 必须有上限。"""
    root = tmp_path / "cloud"
    for i in range(5):
        _write_instruction_skill(root, f"s{i}", f"ins-{i}", triggers=["共同词"])

    index = SkillInstructionIndex(roots=((root, "cloud"),))
    index.discover()

    assert len(index.match("共同词")) == 2


def test_discover_is_idempotent(tmp_path):
    root = tmp_path / "cloud"
    _write_instruction_skill(root, "a", "ins-a", triggers=["甲"])
    index = SkillInstructionIndex(roots=((root, "cloud"),))

    assert index.discover() == 1
    assert index.discover() == 1     # 重复扫描不累加、不丢


# ── 与工具注册互斥 ─────────────────────────────────────────────────────


def test_instruction_skill_is_not_registered_as_tool():
    """端到端口径：指令型 skill 发现了、可用，但**不进工具注册表**。"""
    registry = ToolRegistry()
    loader = SkillLoader(registry, SkillRouter({}))
    loader.discover()
    loader.register_all()

    for name in INSTRUCTION_BATCH_1:
        meta = loader.discovered.get(name)
        assert meta is not None, f"{name} 应当被发现"
        assert meta["form"] == "instruction"
        assert registry.get(name) is None, f"{name} 不该作为工具注册"


@pytest.mark.parametrize("name", INSTRUCTION_BATCH_1)
def test_instruction_skill_has_real_content_not_scaffold(name):
    """内容必须是真写的指令，不是 scaffold 占位（否则注入了也没用）。"""
    meta_path = None
    from core.skill_loader import _SKILL_ROOTS

    for base, _kind in _SKILL_ROOTS:
        candidate = base / name / "SKILL.md"
        if candidate.exists():
            meta_path = candidate
            break
    assert meta_path is not None, f"找不到 {name}/SKILL.md"

    text = meta_path.read_text(encoding="utf-8")
    assert "cloud_call_not_implemented" not in text
    assert "implemented: false" not in text
    body = text.split("---", 2)[-1]
    assert len(body.strip()) > 300, f"{name} 的指令正文过短，像是占位"


# ── 与 context_builder 的接线（注入真的会发生） ─────────────────────────


def test_context_builder_injects_instructions_for_matching_message(monkeypatch):
    """端到端口径：命中触发词的消息，必须真的拿到注入片段。"""
    import core.context_builder as cb

    monkeypatch.setattr(cb, "_SKILL_INSTRUCTIONS", None)   # 重置单例，强制重扫

    block = cb._skill_instructions_for("我们按 TDD 来吧，先写测试再实现")

    assert block.startswith("[技能指令]")
    assert "test-driven-development" in block


def test_context_builder_returns_empty_for_unrelated_message(monkeypatch):
    """不命中就不注入 —— 否则每轮都塞几千字，挤掉对话上下文。"""
    import core.context_builder as cb

    monkeypatch.setattr(cb, "_SKILL_INSTRUCTIONS", None)

    assert cb._skill_instructions_for("今晚吃什么") == ""


def test_context_builder_degrades_gracefully_when_index_fails(monkeypatch):
    """索引构建异常不得拦住对话：降级为"本轮不注入"。"""
    import core.context_builder as cb

    monkeypatch.setattr(cb, "_SKILL_INSTRUCTIONS", None)

    class _Boom:
        def discover(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        "core.skill_instructions.SkillInstructionIndex", lambda *a, **k: _Boom(),
    )

    assert cb._skill_instructions_for("我们按 TDD 来吧") == ""
