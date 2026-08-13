"""Aerie · TopicTracker — 对话话题生命周期追踪引擎.

话题 = 围绕主体（核心主旨）的语义单元。TopicTracker 维护话题的
active/closed 生命周期，为主动消息的"续接 / 再造 / 新话题"决策
与对话上下文注入提供依据，消除主动消息与上文对话之间的割裂。

生命周期（v3.2 收敛）：
- 只显式维护 active | closed 两态；
- paused 为派生状态 —— last_active_at 距今 >= PAUSE_AFTER_HOURS
  即视为暂停（供续接判定），无需显式状态转移路径；
- closed 话题保留 stub（浓缩记忆），可被"话题再造"唤醒为 active。

判定（触发式，确定性为主）：
- 收尾信号词表（CLOSURE_WORDS）命中当前话题 → closed；
- active 话题沉默超过 CLOSE_AFTER_HOURS → closed（重启恢复时也按
  当前 idle 时长重新评估，避免"几天没登录重启还续接旧话题"）；
- subject 命名默认回退 detect_topics 类目名（LLM 命名可注入 override）。

持久化：data/topic_state.json（原子写 tmp+replace，参照 PushPolicy）。
存根入记忆库：显式 LONG_TERM + EXPERIENCE + metadata{kind:"topic_stub"}，
不伪造 importance=7.0；由调用方注入 store 回调，本模块不依赖具体实现。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from core.paths import data_dir

logger = logging.getLogger(__name__)

# 沉寂阈值：last_active_at 距今 >= 该值视为 paused 语义（续接判定用）
PAUSE_AFTER_HOURS = 4.0
# 沉默超时：paused 超过该时长自动 closed
CLOSE_AFTER_HOURS = 24.0
# 话题再造窗口：closed 话题在此窗口内可被重新提起
REVIVE_WINDOW_HOURS = 72.0
# 收尾信号词表（确定性话题终止判定；可扩展）
CLOSURE_WORDS: tuple[str, ...] = (
    "好了",
    "那先这样",
    "先这样",
    "就这样",
    "明天再说",
    "再说吧",
    "不聊了",
    "去睡了",
    "先忙",
    "回见",
    "拜拜",
)
# 存根上限：记忆库只保留最近 MAX_STUB_STORE 条话题存根
MAX_STUB_STORE = 50


@dataclass
class Topic:
    """单个话题。paused 为派生状态，不显式存储。"""

    id: str
    subject: str
    state: str  # active | closed
    started_at: float
    last_active_at: float
    turn_count: int = 0
    summary: str = ""
    stub: str = ""
    closed_at: Optional[float] = None

    def is_paused(self, now: float) -> bool:
        """paused 语义：active 且沉寂超过阈值。"""
        return self.state == "active" and (now - self.last_active_at) >= PAUSE_AFTER_HOURS * 3600


class TopicTracker:
    """话题生命周期追踪引擎（纯同步核心；存根落库为注入的异步回调）。"""

    def __init__(
        self,
        *,
        state_path: Optional[Path] = None,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        self._state_path = state_path or data_dir() / "topic_state.json"
        self._clock = clock or time.time
        self.topics: list[Topic] = []
        self._load()

    # ── 状态查询 ───────────────────────────────────────

    def active_topic(self, now: Optional[float] = None) -> Optional[Topic]:
        """最近的 active 话题（未超 CLOSE_AFTER_HOURS 沉默）。"""
        now = now if now is not None else self._clock()
        for t in self.topics:
            if t.state == "active" and (now - t.last_active_at) < CLOSE_AFTER_HOURS * 3600:
                return t
        return None

    def latest_closed(self, now: Optional[float] = None) -> Optional[Topic]:
        """最近 closed 且仍在再造窗口内的话题。"""
        now = now if now is not None else self._clock()
        closed = [t for t in self.topics if t.state == "closed" and t.closed_at]
        if not closed:
            return None
        closed.sort(key=lambda t: float(t.closed_at or 0), reverse=True)
        newest = closed[0]
        if (now - float(newest.closed_at or now)) < REVIVE_WINDOW_HOURS * 3600:
            return newest
        return None

    def continuation_plan(self, now: Optional[float] = None) -> dict[str, Any]:
        """主动消息触发前判定：续接 / 再造 / 新话题。

        返回 {"mode": "continue"|"revive"|"new", "topic": Topic|None,
              "dialogue_context": str}
        """
        now = now if now is not None else self._clock()
        active = self.active_topic(now)
        if active is not None:
            return {
                "mode": "continue",
                "topic": active,
                "dialogue_context": self._context_for(active),
            }
        stub = self.latest_closed(now)
        if stub is not None:
            return {
                "mode": "revive",
                "topic": stub,
                "dialogue_context": self._context_for(stub),
            }
        return {"mode": "new", "topic": None, "dialogue_context": ""}

    def _context_for(self, topic: Topic) -> str:
        """话题摘要注入文本（续接/再造依据，预算已由调用方裁剪）。"""
        if topic.stub:
            return f"[话题：{topic.subject}] {topic.stub}"
        if topic.summary:
            return f"[话题：{topic.subject}] {topic.summary}"
        return f"[话题：{topic.subject}]"

    # ── 对话驱动更新 ───────────────────────────────────

    def record_dialogue(
        self,
        text: str,
        *,
        subject_override: Optional[str] = None,
        now: Optional[float] = None,
    ) -> Optional[Topic]:
        """对话发生时更新话题状态。

        - 收尾词命中 → 当前 active 话题 closed（生成 stub）；
        - 否则无 active → 新建话题；有 active → 更新活跃时间/轮数/摘要。

        subject_override 为可选的 LLM 命名（默认回退 detect_topics）。
        """
        now = now if now is not None else self._clock()
        text = str(text or "").strip()

        # ① 收尾信号判定（确定性）
        if self._hit_closure(text):
            return self._close_active(now)

        # ② 主题判定
        subject = subject_override or self._infer_subject(text)

        active = self.active_topic(now)
        if active is None:
            topic = Topic(
                id=uuid.uuid4().hex[:12],
                subject=subject,
                state="active",
                started_at=now,
                last_active_at=now,
                turn_count=1,
                summary=text[:200],
            )
            self.topics.insert(0, topic)
            self._save()
            return topic

        # ③ 活跃话题延续
        active.last_active_at = now
        active.turn_count += 1
        active.summary = (text[:200] if not active.summary else active.summary)
        self._save()
        return active

    def mark_inactive_closure(self, now: Optional[float] = None) -> Optional[Topic]:
        """把沉默超时的 active 话题 closed（重启恢复时也调用）。"""
        now = now if now is not None else self._clock()
        return self._close_active(now, force_idle=True)

    # ── 内部：判定与收尾 ───────────────────────────────

    def _hit_closure(self, text: str) -> bool:
        for word in CLOSURE_WORDS:
            if word in text:
                return True
        return False

    def _infer_subject(self, text: str) -> str:
        try:
            from core.evolution_manager import detect_topics

            topics = detect_topics(text)
            if topics:
                return topics[0]
        except Exception:
            logger.debug("topic subject inference failed", exc_info=True)
        return "日常"

    def _close_active(self, now: float, *, force_idle: bool = False) -> Optional[Topic]:
        """关闭最新的 active 话题（收尾信号直接关；force_idle 需沉默超时）。"""
        active_list = [t for t in self.topics if t.state == "active"]
        if not active_list:
            return None
        active_list.sort(key=lambda t: t.last_active_at, reverse=True)
        newest = active_list[0]
        if force_idle:
            if (now - newest.last_active_at) < CLOSE_AFTER_HOURS * 3600:
                return None
        newest.state = "closed"
        newest.closed_at = now
        newest.stub = self._build_stub(newest)
        self._save()
        return newest

    def _build_stub(self, topic: Topic) -> str:
        """closed 时生成浓缩存根（subject + 摘要浓缩）。"""
        base = topic.summary or ""
        # 浓缩：取主题词 + 开头一段
        head = base[:120].replace("\n", " ")
        return head if head else f"你们聊过：{topic.subject}"

    # ── 存根落记忆库（异步，调用方注入 store 回调）───────

    async def persist_stub(
        self,
        topic: Topic,
        *,
        user_id: int,
        store: Callable[[str, dict], Any],
    ) -> str:
        """把话题存根写入长期记忆（LONG_TERM + EXPERIENCE + kind=topic_stub）。

        store 为调用方注入的异步回调：store(content, metadata) -> memory_id。
        """
        content = f"话题存根：{topic.subject}——{topic.stub or topic.summary or ''}"
        content = content[:200]
        metadata = {
            "kind": "topic_stub",
            "subject": topic.subject,
            "closed_at": datetime.now().isoformat(timespec="seconds"),
        }
        try:
            return await store(content, metadata)
        except Exception:
            logger.debug("topic stub persist failed", exc_info=True)
            return ""

    # ── 持久化 ─────────────────────────────────────────

    def _load(self) -> None:
        if not self._state_path:
            return
        if not self._state_path.exists():
            # 首次启动即落盘空状态，供管理台状态查看，避免出现"文件不存在"
            self._save()
            return
        try:
            raw = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("topic state could not be loaded", exc_info=True)
            return
        items = raw.get("topics") if isinstance(raw, dict) else None
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            try:
                topic = Topic(**{k: item[k] for k in ("id", "subject", "state", "started_at", "last_active_at") if k in item})
                topic.turn_count = int(item.get("turn_count", 0))
                topic.summary = str(item.get("summary", ""))
                topic.stub = str(item.get("stub", ""))
                topic.closed_at = item.get("closed_at")
                self.topics.append(topic)
            except (TypeError, ValueError):
                continue
        # 重启恢复：按当前 idle 时长重新评估状态
        now = self._clock()
        for t in self.topics:
            if t.state == "active" and (now - t.last_active_at) >= CLOSE_AFTER_HOURS * 3600:
                t.state = "closed"
                t.closed_at = t.closed_at or now
                t.stub = t.stub or self._build_stub(t)
        if self.topics:
            self._save()

    def _save(self) -> None:
        if not self._state_path:
            return
        try:
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"topics": [asdict(t) for t in self.topics]}
            tmp = self._state_path.with_name(self._state_path.name + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self._state_path)
        except Exception:
            logger.warning("topic state could not be saved", exc_info=True)

    def snapshot(self) -> dict[str, Any]:
        return {"topics": [asdict(t) for t in self.topics]}

    def reset(self) -> None:
        self.topics = []
        self._save()
