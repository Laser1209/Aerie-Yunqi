"""Phase 14 world ImageCandidate consumer.

World emits candidate events only.  Core owns all approval, image workflow,
delivery planning, and ACK decisions.  This module deliberately adds a thin
consumer around the existing Phase 10 ``ImageWorkflow`` rather than changing
the image workflow itself.
"""

from __future__ import annotations

import copy
import inspect
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from core.paths import data_dir

logger = logging.getLogger(__name__)


_NO_SIDE_EFFECTS = {
    "provider_called": False,
    "asset_created": False,
    "delivery_created": False,
}

_IMAGE_CANDIDATE_TYPES = {
    "world.image_candidate.published",
    "image_candidate.published",
}
_IMAGE_CANDIDATE_TOPICS = {
    "image_candidates",
    "message.candidates",
    "world.image_candidates",
}


class JsonWorldImageCandidateStore:
    """Small durable idempotency/audit store for Phase 14.

    It stores only public candidate keys and workflow identifiers.  Raw prompt
    text, message text, credentials, and provider payloads are not accepted by
    the public candidate sanitizer before a record reaches this store.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else data_dir() / "world_image_candidates.json"

    def get(self, idempotency_key: str) -> dict[str, Any] | None:
        data = self._load()
        record = (data.get("records_by_key") or {}).get(str(idempotency_key))
        return copy.deepcopy(record) if isinstance(record, dict) else None

    def put(self, record: dict[str, Any]) -> None:
        key = str(record.get("idempotency_key") or "").strip()
        if not key:
            return
        data = self._load()
        records = data.setdefault("records_by_key", {})
        records[key] = copy.deepcopy(record)
        self._save(data)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "records_by_key": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.warning("world image candidate store corrupt: %s", self.path, exc_info=True)
            return {"version": 1, "records_by_key": {}}
        if not isinstance(data, dict):
            return {"version": 1, "records_by_key": {}}
        data.setdefault("version", 1)
        data.setdefault("records_by_key", {})
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(
            json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        tmp.replace(self.path)


class WorldImageCandidateConsumer:
    """Approve world image candidates and ACK terminal outcomes.

    Non-terminal outcomes such as ``disabled`` and ``offline`` deliberately do
    not ACK, so closing the feature flag or losing the delivery channel does
    not lose pending sidecar data.
    """

    feature_flag = "world_image_candidates_v1"

    def __init__(
        self,
        *,
        feature_flags: Any,
        image_workflow: Any,
        world_port: Any | None = None,
        push_policy: Any | None = None,
        proactive_judge: Any | None = None,
        store: JsonWorldImageCandidateStore | None = None,
        clock: Callable[[], datetime] | None = None,
        delivery_online: Callable[[], bool] | None = None,
        prompt_resolver: Callable[[str, dict[str, Any]], str] | None = None,
    ) -> None:
        self.feature_flags = feature_flags
        self.image_workflow = image_workflow
        self.world_port = world_port
        self.push_policy = push_policy
        self.proactive_judge = proactive_judge
        self.store = store or JsonWorldImageCandidateStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.delivery_online = delivery_online
        self.prompt_resolver = prompt_resolver or self._default_prompt_for_candidate

    async def consume_replay(self, *, last_seq: int | None = None) -> list[dict[str, Any]]:
        replay = getattr(self.world_port, "replay_events", None)
        if not callable(replay):
            return []
        try:
            events = await _maybe_await(replay(last_seq=last_seq))
        except Exception:
            logger.debug("world image candidate replay unavailable", exc_info=True)
            return []
        results: list[dict[str, Any]] = []
        for event in events or []:
            results.append(await self.process_event(event))
        return results

    async def process_event(self, event: Any) -> dict[str, Any]:
        if not self._flag_enabled():
            return self._result(
                status="disabled",
                event=event,
                reason="feature_flag_off",
                acked=False,
            )

        candidate = self._candidate_from_event(event)
        if candidate is None:
            return self._result(
                status="ignored",
                event=event,
                reason="not_image_candidate",
                acked=False,
            )

        existing = self.store.get(candidate["idempotency_key"])
        if existing:
            acked = await self._ack(_event_sequence(event))
            return self._result(
                status="duplicate",
                event=event,
                candidate=candidate,
                reason=str(existing.get("status") or "already_processed"),
                acked=acked,
                idempotent_replay=True,
            )

        if self._is_expired(candidate):
            record = self._record("expired", candidate, event, reason="expired")
            acked = await self._ack(_event_sequence(event))
            return self._result(
                status="expired",
                event=event,
                candidate=candidate,
                reason="expired",
                acked=acked,
                record=record,
            )

        if self.delivery_online is not None:
            try:
                online = bool(self.delivery_online())
            except Exception:
                logger.debug("delivery_online callback failed", exc_info=True)
                online = False
            if not online:
                return self._result(
                    status="offline",
                    event=event,
                    candidate=candidate,
                    reason="delivery_offline",
                    acked=False,
                )

        allowed, policy_reason = self._can_push(candidate["scene"])
        if not allowed:
            record = self._record("suppressed", candidate, event, reason=policy_reason)
            acked = await self._ack(_event_sequence(event))
            return self._result(
                status="suppressed",
                event=event,
                candidate=candidate,
                reason=policy_reason,
                acked=acked,
                record=record,
            )

        judge_decision = self._judge(candidate)
        suppress_reason = str(getattr(judge_decision, "suppress_reason", "") or "")
        if suppress_reason:
            record = self._record(
                "rejected",
                candidate,
                event,
                reason=suppress_reason,
                judge_decision=judge_decision,
            )
            acked = await self._ack(_event_sequence(event))
            return self._result(
                status="rejected",
                event=event,
                candidate=candidate,
                reason=suppress_reason,
                acked=acked,
                record=record,
            )

        workflow_result = self._run_workflow(candidate)
        workflow_status = str(workflow_result.get("status") or "failed")
        if workflow_status == "disabled":
            return self._result(
                status="workflow_disabled",
                event=event,
                candidate=candidate,
                reason="image_workflow_disabled",
                acked=False,
                side_effects=_public_side_effects(workflow_result),
                workflow_result=workflow_result,
            )
        completed = workflow_status == "completed" and bool(workflow_result.get("delivery_plan"))
        status = "completed" if completed else "failed"
        record = self._record(
            status,
            candidate,
            event,
            reason=workflow_status,
            judge_decision=judge_decision,
            workflow_result=workflow_result,
        )
        if completed:
            self._record_push(candidate["scene"])
        acked = await self._ack(_event_sequence(event))
        return self._result(
            status=status,
            event=event,
            candidate=candidate,
            reason=workflow_status,
            acked=acked,
            side_effects=_public_side_effects(workflow_result),
            record=record,
            workflow_result=workflow_result,
        )

    def _flag_enabled(self) -> bool:
        try:
            is_enabled = getattr(self.feature_flags, "is_enabled")
        except Exception:
            return False
        if not callable(is_enabled):
            return False
        try:
            return bool(is_enabled(self.feature_flag))
        except Exception:
            logger.debug("world image candidate flag check failed", exc_info=True)
            return False

    def _candidate_from_event(self, event: Any) -> dict[str, Any] | None:
        event_type = str(getattr(event, "event_type", "") or "")
        topic = str(getattr(event, "topic", "") or "")
        if event_type not in _IMAGE_CANDIDATE_TYPES and topic not in _IMAGE_CANDIDATE_TOPICS:
            return None
        payload = getattr(event, "payload", None)
        if not isinstance(payload, dict):
            return None
        candidate_id = _safe_value(
            payload.get("candidate_id")
            or payload.get("id")
            or getattr(event, "event_id", "")
            or f"candidate-{_event_sequence(event)}"
        )
        idempotency_key = _safe_value(payload.get("idempotency_key") or candidate_id)
        prompt_key = _safe_value(payload.get("prompt_key") or "default")
        scene = _safe_value(payload.get("scene") or "idle_care")
        return {
            "candidate_id": candidate_id,
            "idempotency_key": idempotency_key,
            "scene": scene,
            "owner_id": _safe_value(payload.get("owner_id") or "master"),
            "channel": _safe_value(payload.get("channel") or "local_chat"),
            "target": _safe_value(payload.get("target") or ""),
            "prompt_key": prompt_key,
            "reason_code": _safe_value(payload.get("reason_code") or ""),
            "source": _safe_value(payload.get("source") or "generated"),
            "score": _safe_float(payload.get("score"), 0.0),
            "expires_at": _safe_value(payload.get("expires_at") or ""),
            "created_at": _safe_value(payload.get("created_at") or getattr(event, "occurred_at", "") or ""),
            "event_id": _safe_value(getattr(event, "event_id", "") or ""),
            "sequence": _event_sequence(event),
            "payload_keys": sorted(str(key) for key in payload.keys()),
        }

    def _is_expired(self, candidate: dict[str, Any]) -> bool:
        expires_at = _parse_datetime(candidate.get("expires_at"))
        if expires_at is None:
            return False
        return _ensure_aware(self.clock()) > expires_at

    def _can_push(self, scene: str) -> tuple[bool, str]:
        if self.push_policy is None or not hasattr(self.push_policy, "can_push"):
            return True, "ok"
        try:
            allowed, reason = self.push_policy.can_push(scene)
            return bool(allowed), str(reason or "ok")
        except Exception:
            logger.debug("world image candidate push policy failed", exc_info=True)
            return False, "policy_error"

    def _judge(self, candidate: dict[str, Any]) -> Any:
        if self.proactive_judge is None or not hasattr(self.proactive_judge, "evaluate"):
            return None
        try:
            return self.proactive_judge.evaluate(
                candidate["scene"],
                context_override={
                    "desire_score": min(100.0, candidate["score"] * 100.0),
                    "context_score": min(100.0, candidate["score"] * 100.0),
                    "environment_score": 50.0,
                    "user_minutes_since_last": 999.0,
                },
            )
        except Exception:
            logger.debug("world image candidate proactive judge failed", exc_info=True)
            return type("RejectedJudge", (), {"suppress_reason": "judge_error"})()

    def _run_workflow(self, candidate: dict[str, Any]) -> dict[str, Any]:
        try:
            prompt = self.prompt_resolver(candidate["prompt_key"], candidate)
            result = self.image_workflow.generate_image(
                prompt=prompt,
                idempotency_key=f"world-image:{candidate['idempotency_key']}",
                owner_id=candidate["owner_id"],
                delivery={
                    "channel": candidate["channel"],
                    "target": candidate["target"],
                },
                metadata={
                    "candidate_id": candidate["candidate_id"],
                    "world_event_id": candidate["event_id"],
                    "prompt_key": candidate["prompt_key"],
                    "reason_code": candidate["reason_code"],
                },
            )
            return result if isinstance(result, dict) else {"status": "failed"}
        except Exception:
            logger.debug("world image candidate workflow failed", exc_info=True)
            return {
                "status": "failed",
                "side_effects": dict(_NO_SIDE_EFFECTS),
                "delivery_plan": None,
            }

    def _record_push(self, scene: str) -> None:
        if self.push_policy is None or not hasattr(self.push_policy, "record"):
            return
        try:
            self.push_policy.record(scene)
        except Exception:
            logger.debug("world image candidate push policy record failed", exc_info=True)

    async def _ack(self, seq: int) -> bool:
        if seq <= 0 or self.world_port is None or not hasattr(self.world_port, "ack"):
            return False
        try:
            await _maybe_await(self.world_port.ack(seq))
            return True
        except Exception:
            logger.debug("world image candidate ack failed", exc_info=True)
            return False

    def _record(
        self,
        status: str,
        candidate: dict[str, Any],
        event: Any,
        *,
        reason: str,
        judge_decision: Any | None = None,
        workflow_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workflow = workflow_result if isinstance(workflow_result, dict) else {}
        delivery = workflow.get("delivery_plan") if isinstance(workflow.get("delivery_plan"), dict) else {}
        record = {
            "status": status,
            "reason": str(reason or ""),
            "idempotency_key": candidate["idempotency_key"],
            "candidate": _public_candidate(candidate),
            "event": {
                "event_id": str(getattr(event, "event_id", "") or ""),
                "sequence": _event_sequence(event),
                "event_type": str(getattr(event, "event_type", "") or ""),
                "topic": str(getattr(event, "topic", "") or ""),
            },
            "judge": _public_judge(judge_decision),
            "workflow": {
                "status": str(workflow.get("status") or ""),
                "request_id": str(workflow.get("request_id") or ""),
                "delivery_plan_id": str(delivery.get("delivery_plan_id") or ""),
            },
            "side_effects": _public_side_effects(workflow),
            "updated_at": self.clock().isoformat(),
        }
        self.store.put(record)
        return record

    def _result(
        self,
        *,
        status: str,
        event: Any,
        reason: str,
        acked: bool,
        candidate: dict[str, Any] | None = None,
        side_effects: dict[str, bool] | None = None,
        record: dict[str, Any] | None = None,
        workflow_result: dict[str, Any] | None = None,
        idempotent_replay: bool = False,
    ) -> dict[str, Any]:
        workflow = workflow_result if isinstance(workflow_result, dict) else {}
        return {
            "status": status,
            "reason": str(reason or ""),
            "feature_flag": self.feature_flag,
            "event_id": str(getattr(event, "event_id", "") or ""),
            "sequence": _event_sequence(event),
            "candidate_id": (candidate or {}).get("candidate_id", ""),
            "prompt_key": (candidate or {}).get("prompt_key", ""),
            "acked": bool(acked),
            "idempotent_replay": bool(idempotent_replay),
            "side_effects": side_effects or dict(_NO_SIDE_EFFECTS),
            "workflow": {
                "status": str(workflow.get("status") or ""),
                "request_id": str(workflow.get("request_id") or ""),
            },
            "recorded": bool(record),
        }

    @staticmethod
    def _default_prompt_for_candidate(prompt_key: str, candidate: dict[str, Any]) -> str:
        return f"world_prompt:{_safe_value(prompt_key or candidate.get('prompt_key') or 'default')}"


def _public_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "candidate_id",
        "scene",
        "owner_id",
        "channel",
        "target",
        "prompt_key",
        "reason_code",
        "source",
        "score",
        "expires_at",
        "created_at",
        "event_id",
        "sequence",
        "payload_keys",
    )
    return {key: copy.deepcopy(candidate.get(key)) for key in allowed if key in candidate}


def _public_side_effects(workflow_result: dict[str, Any]) -> dict[str, bool]:
    raw = workflow_result.get("side_effects") if isinstance(workflow_result, dict) else {}
    if not isinstance(raw, dict):
        raw = {}
    return {
        "provider_called": bool(raw.get("provider_called", False)),
        "asset_created": bool(raw.get("asset_created", False)),
        "delivery_created": bool(raw.get("delivery_created", False)),
    }


def _public_judge(judge_decision: Any | None) -> dict[str, Any]:
    if judge_decision is None:
        return {}
    to_dict = getattr(judge_decision, "to_dict", None)
    if callable(to_dict):
        try:
            data = to_dict()
            if isinstance(data, dict):
                return {
                    "scene": str(data.get("scene") or ""),
                    "score": int(data.get("score") or 0),
                    "tone": str(data.get("tone") or ""),
                    "suppress_reason": str(data.get("suppress_reason") or ""),
                }
        except Exception:
            return {}
    return {
        "scene": str(getattr(judge_decision, "scene", "") or ""),
        "score": int(getattr(judge_decision, "score", 0) or 0),
        "tone": str(getattr(judge_decision, "tone", "") or ""),
        "suppress_reason": str(getattr(judge_decision, "suppress_reason", "") or ""),
    }


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _event_sequence(event: Any) -> int:
    try:
        return int(getattr(event, "sequence", 0) or 0)
    except (TypeError, ValueError):
        return 0


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _ensure_aware(value)
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return _ensure_aware(datetime.fromisoformat(raw))
    except ValueError:
        return None


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _safe_value(value: Any, limit: int = 200) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:limit]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default
