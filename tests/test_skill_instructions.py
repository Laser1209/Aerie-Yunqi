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


# ── 全量体检：仓库里所有指令型 skill 的格式与触发词卫生 ─────────────────


def _all_instruction_skills() -> dict[str, dict]:
    """扫描仓库，取出所有 kind: instruction 的 skill 元信息。"""
    import yaml
    from core.skill_loader import _SKILL_ROOTS

    found: dict[str, dict] = {}
    for base, _kind in _SKILL_ROOTS:
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            md = entry / "SKILL.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8")
            parts = text.split("---", 2)
            if len(parts) < 3:
                continue
            meta = yaml.safe_load(parts[1]) or {}
            if str(meta.get("kind") or "").lower() != "instruction":
                continue
            found[str(meta.get("name") or entry.name)] = {
                "dir": entry,
                "triggers": [str(t) for t in (meta.get("triggers") or [])],
                "body": parts[2].strip(),
                "text": text,
            }
    return found


def test_every_instruction_skill_is_well_formed():
    """每份指令型 skill：有触发词、正文够长、不是 scaffold、不留 run.py。"""
    skills = _all_instruction_skills()
    assert len(skills) >= 30, f"指令型 skill 数量异常：{len(skills)}"

    problems: list[str] = []
    for name, info in skills.items():
        if not info["triggers"]:
            problems.append(f"{name}: 无 triggers（永不触发）")
        if len(info["body"]) <= 300:
            problems.append(f"{name}: 正文只有 {len(info['body'])} 字，像占位")
        if "cloud_call_not_implemented" in info["text"]:
            problems.append(f"{name}: 仍是 scaffold 占位")
        if (info["dir"] / "run.py").exists():
            problems.append(f"{name}: 指令型不该保留 run.py")
    assert not problems, "指令型 skill 体检未通过：\n" + "\n".join(problems)


def test_no_trigger_is_shared_across_instruction_skills():
    """同一触发词不得被两个技能共用 —— 否则一句话同时注入两份指令、互相干扰。

    这是实打实踩过的坑：`装个组件` 曾同时属于 shadcn 与 hyperframes-registry。
    """
    seen: dict[str, list[str]] = {}
    for name, info in _all_instruction_skills().items():
        for trigger in info["triggers"]:
            seen.setdefault(trigger, []).append(name)

    collisions = {t: names for t, names in seen.items() if len(names) > 1}
    assert not collisions, f"触发词冲突：{collisions}"


def test_index_loads_every_instruction_skill():
    """索引必须把仓库里所有指令型 skill 都装进来（不能静默漏掉）。"""
    index = SkillInstructionIndex()
    loaded = index.discover()
    expected = len(_all_instruction_skills())
    assert loaded == expected, f"索引装了 {loaded} 个，仓库里有 {expected} 个"


# ── 触发词覆盖：真实说法必须命中（2026-09-30 验收暴露的问题） ────────────
#
# 触发词是这套机制的**唯一切入口**：命不中 = 这个技能等于不存在。
# 而 SKILL.md 里的词很容易写成"动词 + 名词"的固定搭配，用户的动词却是随机的：
#   * frontend-skill 写"做个落地页"，用户说"设计个落地页" → 落空
#   * dashboard-page 写"搭个数据看板"，用户说"做个数据看板" → 落空
#   * writing-plans 只有"实施方案"，用户说"实施计划" → 落空
# 匹配是子串包含，所以这些用例只断言**日常说法能命中**，不断言具体命中哪一个
# 之外的细节 —— 过度精确的断言会把正常调整变成红灯。

# (用户这句话, 至少应命中的一个技能)
REAL_PHRASE_CASES = [
    ("帮我设计个落地页，要有质感", "frontend-skill"),
    ("公司官网帮我搭一个", "frontend-skill"),
    ("这个页面配色和排版帮我看看", "frontend-design"),
    ("帮我做个数据看板", "dashboard-page"),
    ("搭一个监控面板", "dashboard-page"),
    ("写个实施计划，分几个阶段", "writing-plans"),
    ("这个需求帮我出个方案", "writing-plans"),
    ("帮我做个简历", "doc-page"),
    ("把这个排成 A4 打印版", "doc-page"),
    ("这段代码先写测试再实现", "test-driven-development"),
]


@pytest.mark.parametrize("phrase,expected", REAL_PHRASE_CASES)
def test_real_user_phrasing_actually_triggers(phrase, expected):
    index = SkillInstructionIndex()
    index.discover()
    hits = [inst.name for inst in index.match(phrase, limit=5)]
    assert expected in hits, f"{phrase!r} 没能触发 {expected}（实际命中：{hits or '无'}）"


# 普通对话不该被注入方法论：注入有成本（挤占上下文预算），乱命中比不命中更糟
@pytest.mark.parametrize("phrase", [
    "今天天气怎么样",
    "帮我看看这个报错日志",
    "晚饭吃什么好",
    "",
])
def test_ordinary_chatter_does_not_trigger_anything(phrase):
    index = SkillInstructionIndex()
    index.discover()
    assert index.match(phrase, limit=5) == []


def test_no_instruction_skill_relies_only_on_a_verb_phrase():
    """触发词不能只有"动词+名词"这一类 —— 换个动词就落空。

    每个技能至少要有一个**不以动词开头**的核心词，这样"做个/搭个/设计个…"
    任意动词搭配都能被子串匹配命中。已知例外：确无更短核心词的（如
    "排个 A4" 这类本身就有名词的）。
    """
    leading_verbs = (
        "做个", "搭个", "写个", "出个", "搞个", "弄个", "设计个", "生成个",
        "帮我做", "帮我写", "帮我出", "帮我设计", "把内容做成", "把大纲做成",
    )
    offenders: list[str] = []
    for name, info in _all_instruction_skills().items():
        triggers = info["triggers"]
        if not triggers:
            continue
        has_core = any(not t.startswith(leading_verbs) for t in triggers)
        if not has_core:
            offenders.append(f"{name}: {triggers}")
    assert not offenders, (
        "这些技能的触发词全是「动词+名词」，换个动词就落空，需要补一个核心名词：\n"
        + "\n".join(offenders)
    )
