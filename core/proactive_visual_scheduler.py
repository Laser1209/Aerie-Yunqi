"""P1-C.4 主动消息 + 主动图片联合调度.

ProactiveVisualScheduler 在主动候选之上做统一调度:
  - 从 ProactiveCandidate + WorldSnapshot 生成主动消息文本
  - 通过 VisualIntentRouter 判断是否需要附带 visual_request
  - 同一 world_snapshot_id 幂等(不重复生成)
  - 用户忽略后进入退避, 不再重复调度同一快照
  - 不调用任何真实 provider / model / API
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.image_service import VisualIntentRouter
from core.proactive_candidates import ProactiveCandidate
from core.world_simulation import WorldSnapshot


@dataclass
class ProactiveVisualDecision:
    """一次主动调度结果: 主动消息 + 可选视觉请求."""

    message: str
    snapshot_id: str
    visual_request: dict[str, Any] | None = None
    intent: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class ProactiveVisualScheduler:
    def __init__(
        self,
        *,
        visual_intent_router: VisualIntentRouter | None = None,
        min_confidence: float = 0.5,
    ) -> None:
        self.visual_intent_router = visual_intent_router or VisualIntentRouter(
            min_confidence=min_confidence
        )
        self._planned_snapshot_ids: set[str] = set()
        self._ignored_snapshot_ids: set[str] = set()

    def plan(
        self,
        *,
        snapshot: WorldSnapshot,
        candidates: list[ProactiveCandidate],
        metadata: dict[str, Any] | None = None,
    ) -> ProactiveVisualDecision | None:
        snapshot_id = str(getattr(snapshot, "world_snapshot_id", "") or "")
        if not snapshot_id:
            snapshot_id = str(getattr(snapshot, "instance_id", ""))

        if not candidates:
            return None
        if snapshot_id and snapshot_id in self._planned_snapshot_ids:
            return None
        if snapshot_id and snapshot_id in self._ignored_snapshot_ids:
            return None

        candidate = candidates[0]
        message = self._build_message(candidate, snapshot)

        visual_request: dict[str, Any] | None = None
        if self._candidate_wants_visual(candidate):
            prompt = self._visual_prompt(candidate, snapshot)
            routed = self.visual_intent_router.route(
                prompt=prompt,
                metadata=dict(metadata or {}),
            )
            if routed.get("status") == "ok":
                visual_request = routed

        if snapshot_id:
            self._planned_snapshot_ids.add(snapshot_id)

        return ProactiveVisualDecision(
            message=message,
            snapshot_id=snapshot_id,
            visual_request=visual_request,
            intent=candidate.intent.value,
        )

    def record_user_ignored(self, *, snapshot_id: str) -> None:
        """用户忽略后, 该快照进入退避集合, 不再重复调度."""
        if snapshot_id:
            self._ignored_snapshot_ids.add(snapshot_id)

    def _candidate_wants_visual(self, candidate: ProactiveCandidate) -> bool:
        return candidate.intent.value in (
            "life_share",
            "attention_ack",
            "unfinished_topic",
        )

    def _build_message(self, candidate: ProactiveCandidate, snapshot: WorldSnapshot) -> str:
        location = getattr(snapshot, "location", "") or ""
        activity = getattr(snapshot, "activity", "") or ""
        if candidate.topic:
            return f"和你聊聊{candidate.topic} (此刻: {location}·{activity})"
        return f"悄悄看了下此刻的你 ({location}·{activity})"

    def _visual_prompt(self, candidate: ProactiveCandidate, snapshot: WorldSnapshot) -> str:
        # 从候选话题派生视觉 prompt; 环境对象类话题天然不含角色参考
        topic = candidate.topic or ""
        if topic:
            return f"拍一下{topic}"
        return "拍一下窗边的风景"
