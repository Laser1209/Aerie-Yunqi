"""指令型 skill 的**上下文注入**（而非可调用工具）。

**为什么需要它**

`skills/` 下有相当一批 skill 本质是**提示词 / 工作流文档**（brainstorming、
writing-plans、test-driven-development、frontend-design …），不是能调用的函数。
把它们注册成工具在语义上是错的 —— 模型会去"调用一篇文档"，返回一段说明文字，
既没有副作用也没有价值。这正是它们此前只能生成 scaffold 桩的原因。

正确做法与它们本来的性质一致：**命中相关对话时，把指令内容注入 system prompt**，
让模型照着这份方法论做事。

**机制**

1. `discover()` 扫描三个 skill 根，只收 frontmatter 声明了 ``kind: instruction``
   的 skill，读出它的 ``triggers``（触发关键词）与 SKILL.md 正文（= 指令本身）；
2. ``build_block(text)`` 按当前用户消息匹配 triggers，命中的指令拼成一段
   以 ``[技能指令]`` 开头的提示词片段；没命中返回空串。

**为什么不常驻注入**：指令正文动辄上千字，每条消息都塞进去会挤掉对话上下文与
记忆。只在命中时注入，与"按需加载"的通用做法一致。

**与工具型 skill 的关系**：同一份 SKILL.md 只走一条路 —— 声明
``kind: instruction`` 就不注册为工具（见 `core/skill_loader.py`），反之亦然。
两条路互斥，避免同一能力既是工具又是指令、模型两头都试。
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from core.skill_loader import SkillLoader, _SKILL_ROOTS

logger = logging.getLogger(__name__)

# 单次注入的正文上限：超了只截断到该长度，宁可少放一点，也不挤掉对话上下文。
MAX_INSTRUCTION_CHARS = 3000
# 一条消息最多命中几个技能：多了会互相干扰，也让 system prompt 失控。
MAX_MATCHES = 2


@dataclass(frozen=True)
class SkillInstruction:
    """一份指令型 skill：谁触发（triggers）+ 指令正文（body）。"""

    name: str
    triggers: tuple[str, ...]
    body: str

    def matches(self, text: str) -> bool:
        lowered = str(text or "").lower()
        if not lowered:
            return False
        return any(t and t.lower() in lowered for t in self.triggers)


def _split_frontmatter(skill_md: Path) -> tuple[dict, str]:
    """返回 (frontmatter, 正文)。frontmatter 解析复用 SkillLoader 的既有实现。"""
    meta = SkillLoader._parse_frontmatter(skill_md) or {}
    try:
        raw = skill_md.read_text(encoding="utf-8")
    except OSError:
        return meta, ""
    if not raw.startswith("---"):
        return meta, raw.strip()
    end = raw.find("\n---", 3)
    if end < 0:
        return meta, raw.strip()
    body = raw[end + 4:]
    return meta, body.strip()


class SkillInstructionIndex:
    """指令型 skill 的发现与匹配（进程内缓存，`discover()` 幂等）。"""

    def __init__(self, roots: tuple[tuple[Path, str], ...] | None = None) -> None:
        self._roots = roots or _SKILL_ROOTS
        self._instructions: dict[str, SkillInstruction] = {}

    @property
    def names(self) -> list[str]:
        return sorted(self._instructions)

    def discover(self) -> int:
        """扫描并重置索引；返回发现的指令型 skill 数量。"""
        self._instructions.clear()
        for base, _kind in self._roots:
            if not base.is_dir():
                continue
            try:
                entries = sorted(base.iterdir())
            except OSError:
                continue
            for entry in entries:
                if not entry.is_dir():
                    continue
                skill_md = entry / "SKILL.md"
                if not skill_md.exists():
                    continue
                meta, body = _split_frontmatter(skill_md)
                if str(meta.get("kind") or "").strip().lower() != "instruction":
                    continue
                name = str(meta.get("name") or entry.name).strip()
                triggers = meta.get("triggers") or []
                if not isinstance(triggers, list):
                    triggers = []
                trigger_tuple = tuple(str(t).strip() for t in triggers if str(t).strip())
                if not trigger_tuple:
                    # 没有触发词 = 永远不会被注入，属于配置漏写，明确记一条。
                    logger.warning("指令型 skill %s 未声明 triggers，永远不会注入", name)
                if not body:
                    logger.warning("指令型 skill %s 的正文为空，跳过", name)
                    continue
                self._instructions[name] = SkillInstruction(
                    name=name, triggers=trigger_tuple, body=body,
                )
        return len(self._instructions)

    def match(self, text: str, *, limit: int = MAX_MATCHES) -> list[SkillInstruction]:
        """按当前消息匹配指令（顺序稳定：按名字排序，便于测试与复现）。"""
        hits = [inst for _, inst in sorted(self._instructions.items()) if inst.matches(text)]
        return hits[:limit]

    def build_block(self, text: str) -> str:
        """把命中的指令拼成可注入的提示词片段；没命中返回空串。"""
        hits = self.match(text)
        if not hits:
            return ""
        chunks: list[str] = []
        used = 0
        for inst in hits:
            body = inst.body
            remaining = MAX_INSTRUCTION_CHARS - used
            if remaining <= 0:
                break
            if len(body) > remaining:
                body = body[:remaining].rstrip() + "\n…（指令过长，已截断）"
            chunks.append(f"### {inst.name}\n{body}")
            used += len(body)
        if not chunks:
            return ""
        header = (
            "[技能指令] 用户这句话落在下列专业流程里，"
            "请**按这些步骤执行**（它们是对方法论的要求，不是要你复述的内容）："
        )
        return header + "\n\n" + "\n\n".join(chunks)
