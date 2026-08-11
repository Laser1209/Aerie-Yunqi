"""Phase 14 world ImageCandidate consumer.

World emits candidate events only.  Core owns all approval, image workflow,
delivery planning, and ACK decisions.  This module deliberately adds a thin
consumer around the existing Phase 10 ``ImageWorkflow`` rather than changing
the image workflow itself.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import json
import logging
import os
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
_MANUAL_APPROVAL_ACTIONS = {"approve", "reject", "postpone"}

# 视觉场景判重的参考窗口：最近该时段内成功生成的图才作为"参考图"。用于跨路径
# （主动发图 / 聊天要图）同画面判重——两条路径都汇聚到消费者，统一按"画面意思"
# 去重，避免 text 判重因 reason_code 不同而互相看不见。
_VISION_DEDUP_WINDOW_SEC = 14400  # 4h：覆盖开发期跨重启间隔，且 evening 主题一天只一次

_VISION_SCENE_QUESTION = (
    "下面是一段【即将生成的图片提示词】。请把它和上面这张【参考图片】做"
    "'是否会让人感觉重复'的判定。\n\n"
    "判定规则：\n"
    "- 如果按这段提示词生成的图片，整体氛围、场景类型、时间段、主体动作与参考图属于"
    "'同一类生活照'，让人一看就觉得'这跟刚才那张是同一个场景/重复了'，就判：同一场景。\n"
    "- 如果明显是不同场景（不同地点/时间段/氛围/主体活动），就判：不同场景。\n"
    "- 重要：忽略细微差异，不要因为城市名、具体家具摆设、房间细节不同就判不同。"
    "只看整体是不是'同一类居家/生活氛围'。\n\n"
    "【待生成提示词】: {prompt}\n\n"
    "请只回答，不要多余内容，格式如下：\n"
    "判定: 同一场景 或 不同场景\n"
    "理由: 一句话说明依据"
)


def _vision_scene_same(image_path: str | Path, prompt: str) -> bool:
    """用 SiliconFlow Qwen3-VL 判断新提示词与参考图是否同一场景（可重复感）。

    复用项目既有视觉链路（qq_media / siliconflow-vision 同款 SiliconFlow + Qwen3-VL）。
    失败/无 key/异常一律返回 False（视为"不同场景"，不误伤正常生图）——
    视觉判重是增强层，只有高置信的"同一场景"才被采纳为跳过。
    """
    import base64
    import mimetypes

    api_key = os.getenv("SILICONFLOW_API_KEY")
    if not api_key:
        return False
    path = Path(image_path)
    if not path.exists() or not path.is_file():
        return False
    try:
        from openai import OpenAI
    except Exception:
        return False
    base_url = os.getenv("SILICONFLOW_BASE_URL", "https://api.siliconflow.com/v1")
    model = os.getenv("VISION_MODEL", "Qwen/Qwen3-VL-8B-Instruct")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    try:
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    except Exception:
        return False
    data_url = f"data:{mime};base64,{b64}"
    question = _VISION_SCENE_QUESTION.format(prompt=prompt)
    try:
        import httpx

        client = OpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=httpx.Client(trust_env=False, timeout=60),
        )
        resp = client.chat.completions.create(
            model=model,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": data_url}},
                    {"type": "text", "text": question},
                ],
            }],
            max_tokens=256,
            temperature=0,
        )
        answer = str((resp.choices[0].message.content) or "").strip()
    except Exception:
        logger.debug("vision scene dedup provider call failed", exc_info=True)
        return False
    return "同一场景" in answer


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
        image_budget: Any | None = None,
        store: JsonWorldImageCandidateStore | None = None,
        clock: Callable[[], datetime] | None = None,
        delivery_online: Callable[[], bool] | None = None,
        prompt_resolver: Callable[[str, dict[str, Any]], str] | None = None,
        sender: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    ) -> None:
        self.feature_flags = feature_flags
        self.image_workflow = image_workflow
        self.world_port = world_port
        self.push_policy = push_policy
        self.proactive_judge = proactive_judge
        self.image_budget = image_budget
        self.store = store or JsonWorldImageCandidateStore()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.delivery_online = delivery_online
        self.prompt_resolver = prompt_resolver or self._default_prompt_for_candidate
        self.sender = sender

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
            try:
                results.append(await self.process_event(event))
            except Exception:
                logger.warning(
                    "[ImageConsumer] process_event failed for event seq=%s event_id=%s; continuing batch",
                    _event_sequence(event),
                    str(getattr(event, "event_id", "") or ""),
                    exc_info=True,
                )
        return results

    async def approve_candidate(self, approval_payload: dict[str, Any]) -> dict[str, Any]:
        """Process a Dashboard-originated manual candidate decision.

        The Dashboard only sends public identifiers and a decision. Core looks
        up the canonical ImageCandidate event from WorldPort replay, so ACK,
        idempotency, and audit records stay anchored to the world event instead
        of trusting renderer-provided candidate details.
        """

        approval = _manual_approval_from_payload(approval_payload)
        if not self._flag_enabled():
            return _manual_result(
                status="disabled",
                approval=approval,
                reason="feature_flag_off",
                acked=False,
            )

        found = await self._find_candidate_event(approval)
        if found is None:
            return _manual_result(
                status="not_found",
                approval=approval,
                reason="candidate_not_found",
                acked=False,
            )
        event, candidate = found

        if approval["action"] == "postpone":
            return _manual_result(
                status="postponed",
                approval=approval,
                reason=approval["reason_code"] or "manual_postpone",
                acked=False,
                event=event,
                candidate=candidate,
            )

        if approval["action"] == "reject":
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
            record = self._record(
                "rejected",
                candidate,
                event,
                reason=approval["reason_code"] or "manual_reject",
            )
            acked = await self._ack(_event_sequence(event))
            return self._result(
                status="rejected",
                event=event,
                candidate=candidate,
                reason=approval["reason_code"] or "manual_reject",
                acked=acked,
                record=record,
            )

        return await self.process_event(event)

    async def process_event(self, event: Any) -> dict[str, Any]:
        if not self._flag_enabled():
            logger.info(
                "[ImageConsumer] disabled reason=%s key=%s",
                "feature_flag_off",
                self._log_key(event),
            )
            return self._result(
                status="disabled",
                event=event,
                reason="feature_flag_off",
                acked=False,
            )

        candidate = self._candidate_from_event(event)
        if candidate is None:
            logger.info(
                "[ImageConsumer] ignored reason=%s key=%s",
                "not_image_candidate",
                self._log_key(event),
            )
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
                # 用户主动要求的图不因推送暂停/离线而被挡：那是直接命令。
                if not self._is_manual_trigger(candidate):
                    logger.info(
                        "[ImageConsumer] offline pending key=%s",
                        candidate["idempotency_key"],
                    )
                    return self._result(
                        status="offline",
                        event=event,
                        candidate=candidate,
                        reason="delivery_offline",
                        acked=False,
                    )

        allowed, policy_reason = self._can_push(candidate["scene"], candidate)
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

        budget_allowed, budget_reason = self._budget_can_record(candidate)
        if not budget_allowed:
            record = self._record("suppressed", candidate, event, reason=budget_reason)
            acked = await self._ack(_event_sequence(event))
            return self._result(
                status="suppressed",
                event=event,
                candidate=candidate,
                reason=budget_reason,
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

        # 提示词解析可能在异步层选上下文（轻量 LLM 接力）；真正耗时的生图
        # （sync httpx provider call）仍放到 worker 线程，事件循环不冻结。
        try:
            workflow_result = await self._run_workflow(candidate)
        except Exception:
            logger.debug("world image candidate workflow failed", exc_info=True)
            workflow_result = {
                "status": "failed",
                "side_effects": dict(_NO_SIDE_EFFECTS),
                "delivery_plan": None,
            }
        workflow_status = str(workflow_result.get("status") or "failed")
        if workflow_status == "disabled":
            logger.info(
                "[ImageConsumer] workflow_disabled reason=%s key=%s",
                "image_workflow_disabled",
                candidate["idempotency_key"],
            )
            return self._result(
                status="workflow_disabled",
                event=event,
                candidate=candidate,
                reason="image_workflow_disabled",
                acked=False,
                side_effects=_public_side_effects(workflow_result),
                workflow_result=workflow_result,
            )
        if workflow_status == "dedup_skipped":
            record = self._record(
                "dedup_skipped",
                candidate,
                event,
                reason="vision_same_scene",
                workflow_result=workflow_result,
            )
            acked = await self._ack(_event_sequence(event))
            return self._result(
                status="dedup_skipped",
                event=event,
                candidate=candidate,
                reason="vision_same_scene",
                acked=acked,
                side_effects=_public_side_effects(workflow_result),
                record=record,
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
            await self._deliver(workflow_result)
            self._record_push(candidate["scene"])
            self._record_budget("proactive", candidate)
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

    def has_recent_completed(self, reason_code: str, window_sec: float) -> bool:
        """持久化同主题去重：最近窗口内是否已成功处理同一 reason_code。

        主动发图循环在发布前调用它：即使后端重启把进程内 recent_intents 清空，
        也能从审计存储判断"同一视觉主题刚成功发过"，避免每次重启都重新生成
        一张一模一样的图。仅统计 status=completed（生成+派发成功的）记录。
        """
        if not reason_code or window_sec <= 0:
            return False
        now_ts = self.clock().timestamp()
        data = self.store._load() if hasattr(self.store, "_load") else {}
        for record in (data.get("records_by_key") or {}).values():
            if not isinstance(record, dict):
                continue
            if str(record.get("status") or "") != "completed":
                continue
            cand = record.get("candidate")
            if not isinstance(cand, dict):
                continue
            if str(cand.get("reason_code") or "") != reason_code:
                continue
            updated = str(record.get("updated_at") or "")
            if not updated:
                continue
            try:
                done_ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if now_ts - done_ts <= window_sec:
                return True
        return False

    def _recent_completed_asset(self, window_sec: float) -> str:
        """最近窗口内成功生成并落地资产的最晚一条 asset_url，用作画面判重参考图。"""
        if window_sec <= 0:
            return ""
        now_ts = self.clock().timestamp()
        data = self.store._load() if hasattr(self.store, "_load") else {}
        best: tuple[float, str] | None = None
        for record in (data.get("records_by_key") or {}).values():
            if not isinstance(record, dict):
                continue
            if str(record.get("status") or "") != "completed":
                continue
            updated = str(record.get("updated_at") or "")
            if not updated:
                continue
            try:
                done_ts = datetime.fromisoformat(updated.replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if now_ts - done_ts > window_sec:
                continue
            asset = str(((record.get("workflow") or {}).get("asset_url")) or "")
            if asset and (best is None or done_ts > best[0]):
                best = (done_ts, asset)
        return best[1] if best else ""

    @staticmethod
    def _resolve_asset_path(asset_url: str) -> Path | None:
        name = str(asset_url or "").split("/")[-1]
        if not name:
            return None
        return (Path.cwd() / "uploads" / name).resolve()

    def _check_same_scene_sync(self, prompt: str) -> bool:
        if not prompt:
            return False
        asset = self._recent_completed_asset(_VISION_DEDUP_WINDOW_SEC)
        if not asset:
            return False
        path = self._resolve_asset_path(asset)
        if path is None or not path.is_file():
            return False
        try:
            return _vision_scene_same(path, prompt)
        except Exception:
            logger.debug("vision scene dedup judgement failed", exc_info=True)
            return False

    async def _check_same_scene_skip(self, prompt: str) -> bool:
        try:
            return await asyncio.to_thread(self._check_same_scene_sync, prompt)
        except Exception:
            return False

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
            "size": _safe_value(payload.get("size") or ""),
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

    def _can_push(
        self,
        scene: str,
        candidate: dict[str, Any] | None = None,
    ) -> tuple[bool, str]:
        # 用户主动要求的图（scene=local_send）是直接命令，不受任何约束，
        # 否则"拍一张照片"会因最近有推送而被静默掐掉。
        if self._is_manual_trigger(candidate):
            return True, "manual_trigger"
        # 主动发图（Agent 自行决策）不限制调用：PushPolicy 的频控
        # （min_interval / daily_limit / quiet_period / scene_interval）只约束
        # 文字主动推送。图片有自己的节奏约束——proactive.photo_min_interval_sec
        # （最小发图间隔）与 proactive.image_max_per_day（每日上限）——均由
        # 用户在设置界面配置。这里仍尊重全局静音（用户手动 mute 推送时图片
        # 也不应打扰）；全局暂停由 delivery_online（scheduler.is_paused）在
        # 流程更早处拦截，无需在此重复。
        policy = self.push_policy
        if policy is not None:
            try:
                mute_until = getattr(policy, "mute_until", None)
                if mute_until is not None:
                    if isinstance(mute_until, datetime) and mute_until.tzinfo is not None:
                        mute_until = mute_until.replace(tzinfo=None)
                    if datetime.now() < mute_until:
                        return False, "muted"
            except Exception:
                logger.debug("world image candidate push policy mute check failed", exc_info=True)
        return True, "image_agent_decided"

    def _budget_can_record(self, candidate: dict[str, Any] | None = None) -> tuple[bool, str]:
        # 用户主动要求的图片（scene=local_send）不占用主动/自动发图额度。
        if candidate is not None and self._is_manual_trigger(candidate):
            return True, "manual_trigger"
        if self.image_budget is None or not hasattr(self.image_budget, "can_record"):
            return True, "ok"
        try:
            allowed, reason = self.image_budget.can_record("proactive")
            return bool(allowed), str(reason or "ok")
        except Exception:
            logger.debug("world image candidate budget check failed", exc_info=True)
            return False, "daily_image_limit"

    def _record_budget(self, kind: str, candidate: dict[str, Any] | None = None) -> None:
        if candidate is not None and self._is_manual_trigger(candidate):
            return
        if self.image_budget is None or not hasattr(self.image_budget, "record"):
            return
        try:
            self.image_budget.record(kind)
        except Exception:
            logger.debug("world image candidate budget record failed", exc_info=True)

    @staticmethod
    def _log_key(event: Any, candidate: dict[str, Any] | None = None) -> str:
        if candidate:
            return str(candidate.get("idempotency_key") or "")
        payload = getattr(event, "payload", None)
        if isinstance(payload, dict):
            return _safe_value(payload.get("idempotency_key") or "")
        return ""

    @staticmethod
    def _is_manual_trigger(candidate: dict[str, Any] | None) -> bool:
        return bool(candidate) and str(candidate.get("scene") or "") == "local_send"

    def _judge(self, candidate: dict[str, Any]) -> Any:
        if self.proactive_judge is None or not hasattr(self.proactive_judge, "evaluate"):
            return None
        try:
            decision = self.proactive_judge.evaluate(
                candidate["scene"],
                context_override={
                    "desire_score": min(100.0, candidate["score"] * 100.0),
                    "context_score": min(100.0, candidate["score"] * 100.0),
                    "environment_score": 50.0,
                    "user_minutes_since_last": 999.0,
                },
            )
            # 主动发图不限制调用（Agent 决策即执行）：proactive_judge 是文字
            # 主动推送的情绪闸门，对图片候选只保留分数/语气供审计，不再抑制——
            # 抑制会把 Agent 已经决定发布的图片静默吞掉。
            if decision is not None:
                decision.suppress_reason = ""
            return decision
        except Exception:
            logger.debug("world image candidate proactive judge failed", exc_info=True)
            return type("RejectedJudge", (), {"suppress_reason": ""})()

    async def _run_workflow(self, candidate: dict[str, Any]) -> dict[str, Any]:
        try:
            prompt = await self._resolve_prompt(candidate)
        except Exception:
            logger.debug("world image candidate prompt resolve failed", exc_info=True)
            return {
                "status": "failed",
                "side_effects": dict(_NO_SIDE_EFFECTS),
                "delivery_plan": None,
            }
        # 视觉场景判重（跨路径同画面去重）：主动发图与聊天要图都汇聚于此，
        # 在花钱生成前，用最近一张已生成图 + 新提示词让视觉模型判是否同场景。
        if await self._check_same_scene_skip(prompt):
            logger.info(
                "[WorldImage] skip same-scene image reason=%s prompt_key=%s",
                candidate.get("reason_code"), candidate.get("prompt_key"),
            )
            return {
                "status": "dedup_skipped",
                "side_effects": dict(_NO_SIDE_EFFECTS),
                "delivery_plan": None,
            }
        try:
            result = await asyncio.to_thread(
                self._run_workflow_blocking, prompt, candidate
            )
            return result if isinstance(result, dict) else {"status": "failed"}
        except Exception:
            logger.debug("world image candidate workflow failed", exc_info=True)
            return {
                "status": "failed",
                "side_effects": dict(_NO_SIDE_EFFECTS),
                "delivery_plan": None,
            }

    async def _resolve_prompt(self, candidate: dict[str, Any]) -> str:
        """解析生图提示词；resolver 可能是同步或异步（异步可做轻量 LLM 上下文挑选）。

        健壮性：resolver 异常时兜底返回非空占位提示词（_default_prompt_for_candidate），
        绝不返回空串——否则 generate_image 会因 empty_prompt 拒绝，生图直接放弃。
        """
        try:
            result = self.prompt_resolver(candidate["prompt_key"], candidate)
            if inspect.isawaitable(result):
                result = await result
            text = str(result or "")
            if text.strip():
                return text
        except Exception:
            # warning 而非 debug：异常体必须落盘，否则空提示词问题无法复盘定位。
            logger.warning("world image candidate prompt resolve failed", exc_info=True)
        # 兜底：非空占位提示词，保证安全校验通过、provider 能被调用。
        return self._default_prompt_for_candidate(candidate["prompt_key"], candidate)

    def _run_workflow_blocking(self, prompt: str, candidate: dict[str, Any]) -> dict[str, Any]:
        """同步执行生图（放入 worker 线程，避免阻塞事件循环）。"""
        try:
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
                    "size": candidate.get("size") or "",
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

    async def _deliver(self, workflow_result: dict[str, Any]) -> bool:
        """Deliver a completed image to an external channel via the injected sender.

        Best-effort: the workflow already produced the asset and delivery plan;
        a channel the consumer knows how to reach (``qq``) is handed to the
        sender, which resolves the local asset path and pushes it.  Delivery
        failures are logged but never change the workflow's ``completed``
        status or block the ACK, so the pipeline stays decoupled from QQ.
        """
        if self.sender is None or not callable(self.sender):
            return False
        plan = workflow_result.get("delivery_plan")
        if not isinstance(plan, dict):
            return False
        channel = str(plan.get("channel") or "").lower()
        if channel not in {"qq", "local_chat"}:
            return False
        try:
            result = self.sender(plan, workflow_result)
            if hasattr(result, "__await__"):
                result = await result
            return bool(result)
        except Exception:
            logger.debug("world image candidate delivery failed", exc_info=True)
            return False

    def _record_push(self, scene: str) -> None:
        if self.push_policy is None or not hasattr(self.push_policy, "record"):
            return
        try:
            self.push_policy.record(scene)
        except Exception:
            logger.debug("world image candidate push policy record failed", exc_info=True)

    async def _find_candidate_event(
        self,
        approval: dict[str, str],
    ) -> tuple[Any, dict[str, Any]] | None:
        replay = getattr(self.world_port, "replay_events", None)
        if not callable(replay):
            return None
        try:
            events = await _maybe_await(replay(last_seq=0))
        except TypeError:
            try:
                events = await _maybe_await(replay())
            except Exception:
                logger.debug("world image candidate manual replay unavailable", exc_info=True)
                return None
        except Exception:
            logger.debug("world image candidate manual replay unavailable", exc_info=True)
            return None

        wanted_candidate = approval["candidate_id"]
        wanted_idempotency = approval["idempotency_key"]
        for event in events or []:
            candidate = self._candidate_from_event(event)
            if candidate is None:
                continue
            if wanted_candidate and candidate["candidate_id"] == wanted_candidate:
                return event, candidate
            if wanted_idempotency and candidate["idempotency_key"] == wanted_idempotency:
                return event, candidate
        return None

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
                "asset_url": str(delivery.get("asset_url") or ""),
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
        "size",
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


def _manual_approval_from_payload(payload: dict[str, Any]) -> dict[str, str]:
    data = payload if isinstance(payload, dict) else {}
    action = _safe_value(data.get("action") or "approve").lower()
    if action not in _MANUAL_APPROVAL_ACTIONS:
        action = "reject"
    candidate_id = _safe_value(data.get("candidate_id") or data.get("candidateId") or "")
    idempotency_key = _safe_value(
        data.get("idempotency_key")
        or data.get("idempotencyKey")
        or candidate_id
    )
    reason_code = _safe_value(data.get("reason_code") or data.get("reasonCode") or "")
    return {
        "candidate_id": candidate_id,
        "action": action,
        "idempotency_key": idempotency_key,
        "reason_code": reason_code,
    }


def _manual_result(
    *,
    status: str,
    approval: dict[str, str],
    reason: str,
    acked: bool,
    event: Any | None = None,
    candidate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": status,
        "reason": str(reason or ""),
        "feature_flag": WorldImageCandidateConsumer.feature_flag,
        "event_id": str(getattr(event, "event_id", "") or ""),
        "sequence": _event_sequence(event) if event is not None else 0,
        "candidate_id": (candidate or {}).get("candidate_id") or approval["candidate_id"],
        "prompt_key": (candidate or {}).get("prompt_key", ""),
        "acked": bool(acked),
        "idempotent_replay": False,
        "side_effects": dict(_NO_SIDE_EFFECTS),
        "workflow": {
            "status": "",
            "request_id": "",
        },
        "recorded": False,
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
