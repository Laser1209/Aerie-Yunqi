"""Aerie · TopicLifecycle — 话题生命周期状态机（阶段 4）.

在 ``TopicTracker``（active/closed 读取结构）之上旁挂一层**独立**的长期
生命周期状态机，仅维护 ``lifecycle: active | dormant | dead`` 及兴趣评分，
沿 ``data/topic_state.json`` 扩容字段持久化。

职责边界（重要）：
- 状态迁移是**确定性基础设施**，只写状态、只读配置；
- 状态**不得直接触发任何行为**（不发消息、不推送），仅作为阶段 5 的调制输入；
- 唯一例外是「dead 话题的存根归档」（写记忆库），属状态基础设施，非用户可见行为。

迁移规则（阈值全部来自 ``config/topic_lifecycle.yaml``，热加载；代码仅兜底默认）：
- ``active → dormant``：沉寂 ``> dormant_after_hours``；
- ``dormant → dead``：沉寂 ``> dead_after_days`` **且** 满足保守策略
  （``interest_score`` 已随连续沉寂轮次衰减到 0，即 ``demote_after_silent_turns`` 次
  无响应，且沉寂 ``>= demote_after_inactive_days``）；两者冲突时取更保守者（取「与」）；
- **激活**：再次被提及 / 相似话题命中（``similarity_threshold``）→ 迁回 active
  并返回历史摘要，供阶段 5 调制（本模块只返回，不注入、不推送）。

语义相似判定：复用仓库既有的 embedding 入口
（``core/knowledge_indexer.resolve_embedding_fn`` → 远程 > chromadb 本地 ONNX >
确定性哈希兜底），取「词法命中」与「向量 cosine」的较大者：

- 词法负责**字面命中**（子串 / CJK 二元组包含度），便宜且确定；
- 向量负责**换个说法仍是同一件事**（MiniLM 语义空间 cosine）；
- embedding 不可用时自动退化为纯词法，绝不抛错、绝不在判定路径上阻塞。

判定阈值 ``similarity_threshold`` 随判定口径一起重标定（见
``config/topic_lifecycle.yaml`` 注释）。
"""

from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from functools import lru_cache
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import yaml

from core.topic_tracker import CLOSURE_WORDS, Topic, TopicTracker

logger = logging.getLogger(__name__)

# 文本 → 归一化向量的进程内缓存条数（话题指纹稳定、入站文本每轮一条）。
_EMBED_CACHE_SIZE = 512

# 进程内单例 embedding 函数；None 表示尚未解析。
_EMBEDDING_FN: Optional[Callable[[str], Any]] = None
_EMBEDDING_RESOLVED = False

# 配置文件默认路径：config/topic_lifecycle.yaml
_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / "config" / "topic_lifecycle.yaml"
)

# 代码兜底默认（业务数值一律从配置读取，此处仅作缺文件/异常时的兜底）。
_DEFAULT_CONFIG: dict[str, Any] = {
    "dormant_after_hours": 24.0,
    "dead_after_days": 30.0,
    "similarity_threshold": 0.70,
    "demote_after_silent_turns": 3,
    "demote_after_inactive_days": 14.0,
}

# 兴趣衰减的浮点比较容差（1 - 3*(1/3) 可能残留 1e-16）。
_SCORE_EPS = 1e-9

# mtime 比较容差（避免文件系统时间戳精度抖动导致反复重载）。
_MTIME_EPS = 0.1


def _cjk_bigrams(text: str) -> set[str]:
    """归一化后取字符二元组集合（去掉空白）。"""
    normalized = re.sub(r"\s+", "", str(text or ""))
    if len(normalized) < 2:
        return set()
    return {normalized[i : i + 2] for i in range(len(normalized) - 1)}


def similarity(text: str, reference: str) -> float:
    """语义相似度（0..1）：词法命中与向量 cosine 取较大者。

    - 完全包含 → 1.0（字面命中的上界，直接短路，省掉一次 embedding）；
    - 否则取 max(二元组包含度, embedding cosine)，互补「字面」与「换个说法」。
    """
    query = str(text or "").strip()
    ref = str(reference or "")
    if not query or not ref:
        return 0.0
    lexical = _lexical_similarity(query, ref)
    if lexical >= 1.0:
        return 1.0
    vector = _vector_similarity(query, ref)
    if vector is None:
        return lexical
    return max(lexical, vector)


def _lexical_similarity(query: str, ref: str) -> float:
    """字面相似度：子串命中记 1.0，否则按二元组包含度。"""
    if query in ref or ref in query:
        return 1.0
    bigrams_a, bigrams_b = _cjk_bigrams(query), _cjk_bigrams(ref)
    if not bigrams_a or not bigrams_b:
        return 0.0
    overlap = len(bigrams_a & bigrams_b)
    if not overlap:
        return 0.0
    return overlap / min(len(bigrams_a), len(bigrams_b))


def _embedding_fn() -> Optional[Callable[[str], Any]]:
    """惰性解析进程内 embedding 函数（只解析一次）。

    ``resolve_embedding_fn()`` 自带兜底链（远程 → chromadb 本地 ONNX → 确定性
    哈希），因此正常不会返回 None；导入失败才返回 None（调用方退回纯词法）。
    """
    global _EMBEDDING_FN, _EMBEDDING_RESOLVED
    if not _EMBEDDING_RESOLVED:
        _EMBEDDING_RESOLVED = True
        try:
            from core.knowledge_indexer import resolve_embedding_fn

            _EMBEDDING_FN = resolve_embedding_fn()
        except Exception:
            logger.warning("话题相似度：embedding 不可用，退化为纯词法", exc_info=True)
            _EMBEDDING_FN = None
    return _EMBEDDING_FN


@lru_cache(maxsize=_EMBED_CACHE_SIZE)
def _embed_normalized(text: str) -> Optional[tuple[float, ...]]:
    """文本 → L2 归一化向量；不可用时返回 None。"""
    fn = _embedding_fn()
    if fn is None:
        return None
    try:
        vec = [float(x) for x in fn(text)]
    except Exception:
        logger.debug("话题相似度：embedding 调用失败", exc_info=True)
        return None
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0.0:
        return None
    return tuple(v / norm for v in vec)


def _vector_similarity(query: str, reference: str) -> Optional[float]:
    """归一化向量的 cosine（∈[0,1]）；任一侧取不到向量则返回 None。"""
    a = _embed_normalized(query)
    b = _embed_normalized(reference)
    if a is None or b is None or len(a) != len(b):
        return None
    dot = 0.0
    for x, y in zip(a, b):
        dot += x * y
    return max(0.0, min(1.0, dot))


class _LifecycleConfigLoader:
    """``topic_lifecycle.yaml`` 热加载读取（mtime 检测，参照 persona_loader 模式）。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._mtime: Optional[float] = None
        self._data: dict[str, Any] = dict(_DEFAULT_CONFIG)

    def get(self) -> dict[str, Any]:
        try:
            mtime = self._path.stat().st_mtime
        except OSError:
            # 文件缺失：沿用兜底默认，且不缓存 mtime（出现后立即加载）。
            return dict(self._data)
        if self._mtime is not None and mtime <= self._mtime + _MTIME_EPS:
            return dict(self._data)
        try:
            raw = yaml.safe_load(self._path.read_text(encoding="utf-8")) or {}
        except Exception:
            logger.warning("topic_lifecycle.yaml 解析失败，沿用兜底默认", exc_info=True)
            self._mtime = mtime
            return dict(self._data)
        merged = dict(_DEFAULT_CONFIG)
        if isinstance(raw, dict):
            for key in _DEFAULT_CONFIG:
                if key in raw:
                    merged[key] = raw[key]
        self._data = self._coerce(merged)
        self._mtime = mtime
        return dict(self._data)

    @staticmethod
    def _coerce(data: dict[str, Any]) -> dict[str, Any]:
        def _float(key: str, minimum: float = 0.0) -> float:
            try:
                return max(minimum, float(data.get(key)))
            except (TypeError, ValueError):
                return float(_DEFAULT_CONFIG[key])

        def _int(key: str) -> int:
            try:
                return max(1, int(data.get(key)))
            except (TypeError, ValueError):
                return int(_DEFAULT_CONFIG[key])

        return {
            "dormant_after_hours": _float("dormant_after_hours"),
            "dead_after_days": _float("dead_after_days"),
            "similarity_threshold": min(1.0, _float("similarity_threshold")),
            "demote_after_silent_turns": _int("demote_after_silent_turns"),
            "demote_after_inactive_days": _float("demote_after_inactive_days"),
        }


class TopicLifecycle:
    """话题生命周期状态机（独立模块；只写状态，不触发行为）。"""

    def __init__(
        self,
        *,
        tracker: Optional[TopicTracker] = None,
        config_path: Optional[Path] = None,
        clock: Optional[Callable[[], float]] = None,
        enabled_check: Optional[Callable[[], bool]] = None,
        store_stub: Optional[Callable[[str, dict], Awaitable[str]]] = None,
    ) -> None:
        self._tracker = tracker if tracker is not None else TopicTracker()
        self._clock = clock or time.time
        self._loader = _LifecycleConfigLoader(config_path or _DEFAULT_CONFIG_PATH)
        self._enabled_check = enabled_check
        self._store_stub = store_stub

    # ── 基础访问 ───────────────────────────────────────

    @property
    def tracker(self) -> TopicTracker:
        return self._tracker

    def config(self) -> dict[str, Any]:
        """当前生效阈值（热加载后的快照）。"""
        return self._loader.get()

    def is_enabled(self) -> bool:
        """开关门控：未注入开关时默认启用（供独立测试/无 companion 场景）。"""
        if self._enabled_check is None:
            return True
        try:
            return bool(self._enabled_check())
        except Exception:
            logger.debug("topic lifecycle enabled_check failed", exc_info=True)
            return False

    # ── 每轮观察入口 ───────────────────────────────────

    def observe(self, turn: dict[str, Any]) -> Optional[dict[str, Any]]:
        """每轮对话后的旁挂观察（确定性；只写状态，不触发任何行为）。

        ``turn``: ``{"text": str, "user_id": int | None, "now": float | None}``
        （``text`` 为空表示仅做时间推进 / 迁移评估，不产生对话写入）。

        返回：激活命中历史摘要时的
        ``{"activated": True, "topic_id", "subject", "summary", "similarity"}``，
        否则 ``None``。调用方仅可将其作为阶段 5 的调制输入。
        """
        if not self.is_enabled():
            return None
        config = self.config()
        now = turn.get("now")
        now = float(now) if now is not None else self._clock()
        text = str(turn.get("text") or "").strip()
        user_id = turn.get("user_id")

        activation: Optional[dict[str, Any]] = None
        if text and not self._is_closure(text):
            # ① 优先尝试激活非 active 的历史话题（命中则注入摘要，不开新话题）。
            activation = self._activate_if_matched(text, now, config)
        if text and activation is None:
            # ② 正常写路径：record_dialogue 负责新建/延续/收尾。
            self._tracker.record_dialogue(text, now=now)
            self._mark_active_context(text, now)

        # ③ 沉默话题自动收尾（接线 mark_inactive_closure；与 lifecycle 互不干扰）。
        self._tracker.mark_inactive_closure(now)
        # ④ 长期状态迁移评估（active → dormant → dead）。
        died = self._evaluate_transitions(now, config)
        if died and self._store_stub is not None:
            self._schedule_archive(died, user_id)
        return activation

    # ── 内部：激活 ─────────────────────────────────────

    def _is_closure(self, text: str) -> bool:
        return any(word in text for word in CLOSURE_WORDS)

    def _activate_if_matched(
        self, text: str, now: float, config: dict[str, Any]
    ) -> Optional[dict[str, Any]]:
        """非 active 话题被相似命中 → 迁回 active 并返回历史摘要。"""
        threshold = float(config["similarity_threshold"])
        matched: Optional[Topic] = None
        best_score = 0.0
        for topic in self._tracker.topics:
            if topic.lifecycle == "active":
                continue
            score = similarity(text, self._fingerprint(topic))
            if score >= threshold and score > best_score:
                matched, best_score = topic, score
        if matched is None:
            return None

        historical = self._context_for(matched)
        matched.state = "active"
        matched.lifecycle = "active"
        matched.last_active_at = now
        matched.turn_count += 1
        matched.interest_score = 1.0
        matched.dormancy_since = None
        matched.last_context = text[:200]
        self._tracker.save()
        return {
            "activated": True,
            "topic_id": matched.id,
            "subject": matched.subject,
            "summary": historical,
            "similarity": round(best_score, 3),
        }

    def reactivate(self, topic_id: str, now: Optional[float] = None) -> bool:
        """把指定话题迁回 active（话题复现命中后由阶段 5 调用）。

        只写状态、不触发行为：复现成功后重置生命周期与兴趣评分，
        避免同一话题在沉寂池里被反复选中。返回是否命中并写盘。
        """
        if not self.is_enabled():
            return False
        moment = float(now) if now is not None else self._clock()
        for topic in self._tracker.topics:
            if topic.id != topic_id:
                continue
            topic.state = "active"
            topic.lifecycle = "active"
            topic.interest_score = 1.0
            topic.dormancy_since = None
            topic.last_active_at = moment
            self._tracker.save()
            return True
        return False

    def _mark_active_context(self, text: str, now: float) -> None:
        """把当前 active 话题标记为活跃：重置生命周期与兴趣评分。"""
        active = self._tracker.active_topic(now)
        if active is None:
            return
        active.lifecycle = "active"
        active.interest_score = 1.0
        active.dormancy_since = None
        active.last_context = text[:200]
        self._tracker.save()

    @staticmethod
    def _fingerprint(topic: Topic) -> str:
        """话题指纹：主体 + 上下文/摘要/存根拼接，供简化相似度比对。"""
        return " ".join(
            part
            for part in (
                topic.subject,
                topic.last_context,
                topic.summary,
                topic.stub,
            )
            if part
        )

    @staticmethod
    def _context_for(topic: Topic) -> str:
        """历史摘要文本（非空；与 TopicTracker._context_for 语义一致）。"""
        base = topic.stub or topic.summary or topic.last_context or ""
        head = str(base).strip()
        if head:
            return f"[话题：{topic.subject}] {head}"
        return f"[话题：{topic.subject}]"

    # ── 内部：迁移 ─────────────────────────────────────

    def _evaluate_transitions(
        self, now: float, config: dict[str, Any]
    ) -> list[Topic]:
        """评估并落盘生命周期迁移；返回本轮新变为 dead 的话题。"""
        dormant_after = float(config["dormant_after_hours"]) * 3600.0
        dead_after = float(config["dead_after_days"]) * 86400.0
        demote_after_days = float(config["demote_after_inactive_days"]) * 86400.0
        decay = 1.0 / max(1, int(config["demote_after_silent_turns"]))

        died: list[Topic] = []
        changed = False
        for topic in self._tracker.topics:
            idle = now - topic.last_active_at
            if topic.lifecycle == "active":
                # 纯时间判定：lifecycle 与 state(active/closed) 正交，沉寂超阈值即降级。
                if idle >= dormant_after:
                    topic.lifecycle = "dormant"
                    # 记录跨越阈值的确切时刻（确定性，不随观察时机漂移）。
                    topic.dormancy_since = topic.last_active_at + dormant_after
                    topic.interest_score = max(0.0, topic.interest_score - decay)
                    changed = True
                continue
            if topic.lifecycle != "dormant":
                continue
            # 保守策略：连续无响应 → 兴趣评分递减（激活时已重置为 1.0）。
            if topic.interest_score > _SCORE_EPS:
                topic.interest_score = max(0.0, topic.interest_score - decay)
                changed = True
            # 更保守者生效：同时满足「沉寂 > dead_after_days」与
            # 「连续 demote_after_silent_turns 次无响应 且 沉寂 >= demote_after_inactive_days」。
            if (
                idle >= dead_after
                and idle >= demote_after_days
                and topic.interest_score <= _SCORE_EPS
            ):
                topic.lifecycle = "dead"
                died.append(topic)
                changed = True
        if changed:
            self._tracker.save()
        return died

    # ── 内部：dead 存根归档（写路径接线 persist_stub）──────

    def _schedule_archive(self, topics: list[Topic], user_id: Any) -> None:
        """把新 dead 话题的存根归档到记忆库（fire-and-forget，不阻断主链路）。"""
        store = self._store_stub
        if store is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # 无事件循环（同步调用）→ 跳过归档，不影响状态迁移。
            return
        for topic in topics:
            try:
                loop.create_task(
                    self._tracker.persist_stub(
                        topic,
                        user_id=int(user_id or 0),
                        store=store,
                    )
                )
            except Exception:
                logger.debug("topic stub archive schedule failed", exc_info=True)


_LIFECYCLE: Optional[TopicLifecycle] = None


def get_topic_lifecycle() -> TopicLifecycle:
    """进程级单例（供无 companion 注入的只读/调试场景复用）。"""
    global _LIFECYCLE
    if _LIFECYCLE is None:
        _LIFECYCLE = TopicLifecycle()
    return _LIFECYCLE
