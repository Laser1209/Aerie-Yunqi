from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from communication.message import CancellationToken, CancellationTooLate, IncomingMessage
from core.chat_request_repository import ClaimedRequest, RequestContext


logger = logging.getLogger(__name__)


class ChatRequestWorker:
    def __init__(
        self,
        *,
        repository: Any,
        pipeline: Any,
        emit: Callable[..., None],
        clock: Callable[[], datetime],
        max_concurrency: int = 4,
        lease_seconds: int = 30,
        heartbeat_seconds: float = 10,
        worker_id: str = "chat-request-worker",
        batch_completed_hook: Callable[[IncomingMessage | None], Awaitable] | None = None,
    ) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be positive")
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if not worker_id:
            raise ValueError("worker_id is required")

        self.repository = repository
        self.pipeline = pipeline
        self.emit = emit
        self.clock = clock
        self.max_concurrency = max_concurrency
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds
        self.worker_id = worker_id
        self.batch_completed_hook = batch_completed_hook

        self._running_tasks: dict[str, asyncio.Task[None]] = {}
        self._heartbeat_tasks: dict[str, asyncio.Task[None]] = {}
        self._cancellation_tokens: dict[str, CancellationToken] = {}
        self._cancellation_reasons: dict[str, str] = {}
        self._slot_tasks: list[asyncio.Task[None]] = []
        self._idle_event = asyncio.Event()
        self._work_event = asyncio.Event()
        self._started = False
        self._stopping = False

    async def start(self) -> None:
        if self._started:
            return

        recovered = self.repository.recover_interrupted()
        self._stopping = False
        self._idle_event.clear()
        self._work_event.clear()
        self._started = True
        self._slot_tasks = [
            asyncio.create_task(
                self._slot_loop(slot_index),
                name=f"chat-request-slot-{slot_index}",
            )
            for slot_index in range(self.max_concurrency)
        ]
        logger.info(
            "chat request worker started: worker_id=%s slots=%d recovered=%d",
            self.worker_id,
            self.max_concurrency,
            recovered,
        )

    async def stop(self) -> None:
        if not self._started:
            return

        self._stopping = True
        self._work_event.set()

        running_items = list(self._running_tasks.items())
        running = [task for _request_id, task in running_items]
        for request_id, task in running_items:
            self._cancellation_reasons[request_id] = "worker_stopped"
            self._cancel_token(request_id, "worker_stopped")
            if not task.done():
                task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)

        for task in self._slot_tasks:
            if not task.done():
                task.cancel()
        if self._slot_tasks:
            await asyncio.gather(*self._slot_tasks, return_exceptions=True)

        heartbeats = list(self._heartbeat_tasks.values())
        for task in heartbeats:
            if not task.done():
                task.cancel()
        if heartbeats:
            await asyncio.gather(*heartbeats, return_exceptions=True)

        self._running_tasks.clear()
        self._heartbeat_tasks.clear()
        self._cancellation_tokens.clear()
        self._cancellation_reasons.clear()
        self._slot_tasks.clear()
        self._idle_event.set()
        self._started = False
        logger.info("chat request worker stopped: worker_id=%s", self.worker_id)

    async def cancel_running(self, request_id: str) -> bool:
        task = self._running_tasks.get(request_id)
        if task is None or task.done():
            if self._try_mark_failed(request_id, "cancel_task_missing"):
                self._emit_status(
                    "chat_request_failed",
                    request_id=request_id,
                    status="failed",
                    error_code="cancel_task_missing",
                )
            self._work_event.set()
            return False

        self._cancellation_reasons.setdefault(request_id, "user_cancel")
        self._cancel_token(request_id, "user_cancel")
        task.cancel()
        await asyncio.wait({task}, timeout=0.25)
        return True

    def notify(self) -> None:
        self._work_event.set()

    async def _slot_loop(self, slot_index: int) -> None:
        while not self._stopping:
            try:
                claimed = self.repository.claim_next(
                    lease_owner=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "chat request claim failed: worker_id=%s slot=%d",
                    self.worker_id,
                    slot_index,
                )
                await self._wait_for_work()
                continue

            if claimed is None:
                if not self._running_tasks:
                    self._idle_event.set()
                await self._wait_for_work()
                continue

            self._idle_event.clear()
            request_id = claimed.context.request_id
            execution = asyncio.create_task(
                self._execute_claimed(claimed),
                name=f"chat-request-{request_id}",
            )
            self._running_tasks[request_id] = execution
            self._emit_claimed_status("chat_request_running", claimed, "running")
            try:
                await execution
            except asyncio.CancelledError:
                self._finalize_cancelled(claimed)
            finally:
                if self._running_tasks.get(request_id) is execution:
                    self._running_tasks.pop(request_id, None)
                self._work_event.set()

    async def _wait_for_work(self) -> None:
        try:
            await asyncio.wait_for(self._work_event.wait(), timeout=0.25)
        except TimeoutError:
            pass
        finally:
            self._work_event.clear()

    async def _execute_claimed(self, claimed: ClaimedRequest) -> None:
        context = claimed.context
        request_id = context.request_id
        batch_id = context.batch_id
        is_batch = batch_id is not None

        if is_batch:
            await self._execute_batch(
                primary_claimed=claimed,
                batch_id=batch_id,
            )
            return

        execution = asyncio.current_task()
        if execution is None:
            raise RuntimeError("chat request execution task is unavailable")
        heartbeat = asyncio.create_task(
            self._heartbeat_loop(request_id, execution),
            name=f"chat-request-heartbeat-{request_id}",
        )
        self._heartbeat_tasks[request_id] = heartbeat
        token = CancellationToken()
        self._cancellation_tokens[request_id] = token
        try:
            result = await self.pipeline.handle(
                request_context=context,
                cancellation_token=token,
            )
            result_data = result if isinstance(result, dict) else {}
            if not result_data.get("canonical_completed"):
                self.repository.mark_completed(
                    request_id=request_id,
                    lease_owner=self.worker_id,
                    result=result_data,
                )
            self._emit_claimed_status(
                "chat_request_completed",
                claimed,
                "completed",
                sequence=self._terminal_sequence(result_data),
            )
        except asyncio.CancelledError:
            self._finalize_cancelled(claimed)
        except CancellationTooLate as exc:
            self._fail_claimed(claimed, exc.reason)
        except Exception:
            logger.exception(
                "chat request pipeline failed: request_id=%s worker_id=%s",
                request_id,
                self.worker_id,
            )
            self._fail_claimed(claimed, "pipeline_failed")
        finally:
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
            if self._heartbeat_tasks.get(request_id) is heartbeat:
                self._heartbeat_tasks.pop(request_id, None)
            self._cancellation_tokens.pop(request_id, None)
            self._cancellation_reasons.pop(request_id, None)

    async def _execute_batch(
        self,
        *,
        primary_claimed: ClaimedRequest,
        batch_id: str,
    ) -> None:
        primary_context = primary_claimed.context
        primary_request_id = primary_context.request_id

        remaining_claimed = self.repository.claim_remaining_batch(
            batch_id=batch_id,
            lease_owner=self.worker_id,
            lease_seconds=self.lease_seconds,
            exclude_request_id=primary_request_id,
        )

        all_claimed: list[ClaimedRequest] = [primary_claimed] + remaining_claimed
        all_contexts: list[RequestContext] = [c.context for c in all_claimed]
        all_request_ids: list[str] = [ctx.request_id for ctx in all_contexts]

        logger.info(
            "Processing batch %s: %d requests (primary=%s)",
            batch_id,
            len(all_claimed),
            primary_request_id,
        )

        execution = asyncio.current_task()
        if execution is None:
            raise RuntimeError("chat request batch execution task is unavailable")

        for req_id in all_request_ids:
            self._running_tasks[req_id] = execution

        heartbeats: list[asyncio.Task[None]] = []
        for req_id in all_request_ids:
            hb = asyncio.create_task(
                self._heartbeat_loop(req_id, execution),
                name=f"chat-request-heartbeat-{req_id}",
            )
            self._heartbeat_tasks[req_id] = hb
            heartbeats.append(hb)

        token = CancellationToken()
        for req_id in all_request_ids:
            self._cancellation_tokens[req_id] = token

        messages = [self._context_to_message(ctx) for ctx in all_contexts]

        try:
            results = await self.pipeline.handle(
                messages=messages,
                batch_id=batch_id,
                cancellation_token=token,
            )
            results_list = results if isinstance(results, list) else []
            self.repository.mark_batch_completed(
                batch_id=batch_id,
                lease_owner=self.worker_id,
                results={},
            )
            if self.batch_completed_hook is not None:
                try:
                    await self.batch_completed_hook(messages[0] if messages else None)
                except Exception:
                    logger.exception("batch_completed_hook failed for batch %s", batch_id)
            for claimed, result_data in zip(all_claimed, results_list):
                if not isinstance(result_data, dict):
                    result_data = {}
                self._emit_claimed_status(
                    "chat_request_completed",
                    claimed,
                    "completed",
                    sequence=self._terminal_sequence(result_data),
                )
            logger.info(
                "Batch %s completed: %d requests processed",
                batch_id,
                len(all_claimed),
            )
        except asyncio.CancelledError:
            self._finalize_batch_cancelled(all_claimed)
        except CancellationTooLate as exc:
            self._fail_batch(all_claimed, exc.reason)
        except Exception:
            logger.exception(
                "chat request batch pipeline failed: batch_id=%s worker_id=%s",
                batch_id,
                self.worker_id,
            )
            self._fail_batch(all_claimed, "pipeline_failed")
        finally:
            for hb in heartbeats:
                hb.cancel()
            await asyncio.gather(*heartbeats, return_exceptions=True)
            for req_id in all_request_ids:
                self._running_tasks.pop(req_id, None)
                self._heartbeat_tasks.pop(req_id, None)
                self._cancellation_tokens.pop(req_id, None)
                self._cancellation_reasons.pop(req_id, None)
            self._work_event.set()

    @staticmethod
    def _context_to_message(context: RequestContext) -> IncomingMessage:
        identity = context.identity
        source = "local" if identity.channel == "desktop" else identity.channel
        return IncomingMessage(
            user_id=identity.user_id,
            content=context.input_content,
            msg_type="private",
            source=source or "local",
            raw_event={},
            reply_to_id=context.reply_to_id,
            attachments=list(context.attachments),
            actor_id=identity.actor_id,
            channel=identity.channel,
            channel_account_id=identity.channel_account_id,
        )

    def _fail_batch(self, claimed_list: list[ClaimedRequest], error_code: str) -> None:
        if not claimed_list:
            return
        batch_id = claimed_list[0].context.batch_id
        try:
            self.repository.mark_batch_failed(
                batch_id=batch_id,
                lease_owner=self.worker_id,
                error_code=error_code,
            )
        except Exception:
            logger.exception(
                "chat request batch failure finalization failed: batch_id=%s",
                batch_id,
            )
        for claimed in claimed_list:
            self._emit_claimed_status(
                "chat_request_failed",
                claimed,
                "failed",
                error_code=error_code,
                sequence=0,
            )

    def _finalize_batch_cancelled(self, claimed_list: list[ClaimedRequest]) -> None:
        if not claimed_list:
            return
        batch_id = claimed_list[0].context.batch_id
        reasons = set()
        for claimed in claimed_list:
            req_id = claimed.context.request_id
            reason = self._cancellation_reasons.pop(req_id, None)
            if reason:
                reasons.add(reason)
        if reasons & {"worker_stopped", "lease_lost"}:
            self._fail_batch(claimed_list, "worker_stopped" if "worker_stopped" in reasons else "lease_lost")
            return
        try:
            self.repository.mark_batch_failed(
                batch_id=batch_id,
                lease_owner=self.worker_id,
                error_code="pipeline_cancelled",
            )
        except Exception:
            logger.exception(
                "chat request batch cancellation finalization failed: batch_id=%s",
                batch_id,
            )
        for claimed in claimed_list:
            self._emit_claimed_status(
                "chat_request_cancelled",
                claimed,
                "cancelled",
                sequence=1,
            )

    async def _heartbeat_loop(
        self,
        request_id: str,
        execution: asyncio.Task[None],
    ) -> None:
        while True:
            try:
                lease_active = self.repository.heartbeat(
                    request_id=request_id,
                    lease_owner=self.worker_id,
                    lease_seconds=self.lease_seconds,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "chat request heartbeat failed: request_id=%s worker_id=%s",
                    request_id,
                    self.worker_id,
                )
                self._cancel_for_lost_lease(request_id, execution)
                return
            if not lease_active:
                logger.warning(
                    "chat request heartbeat lost lease: request_id=%s "
                    "worker_id=%s",
                    request_id,
                    self.worker_id,
                )
                self._cancel_for_lost_lease(request_id, execution)
                return
            await asyncio.sleep(self.heartbeat_seconds)

    def _cancel_for_lost_lease(
        self,
        request_id: str,
        execution: asyncio.Task[None],
    ) -> None:
        if execution.done():
            return
        self._cancellation_reasons.setdefault(request_id, "lease_lost")
        self._cancel_token(request_id, "lease_lost")
        execution.cancel()

    def _cancel_token(self, request_id: str, reason: str) -> None:
        token = self._cancellation_tokens.get(request_id)
        if token is not None:
            token.cancel(reason)

    def _finalize_cancelled(self, claimed: ClaimedRequest) -> None:
        request_id = claimed.context.request_id
        reason = self._cancellation_reasons.pop(request_id, None)
        if reason == "worker_stopped":
            self._fail_claimed(claimed, "worker_stopped")
            return
        if reason == "lease_lost":
            self._fail_claimed(claimed, "lease_lost")
            return

        cancelled = self._try_mark_cancelled(request_id)
        if cancelled is True:
            self._emit_claimed_status(
                "chat_request_cancelled",
                claimed,
                "cancelled",
                sequence=1,
            )
        elif cancelled is False:
            self._fail_claimed(claimed, "pipeline_cancelled")

    def _try_mark_cancelled(self, request_id: str) -> bool | None:
        try:
            self.repository.mark_cancelled(
                request_id=request_id,
                lease_owner=self.worker_id,
            )
            return True
        except ValueError:
            return False
        except Exception:
            logger.exception(
                "chat request cancellation finalization failed: "
                "request_id=%s worker_id=%s",
                request_id,
                self.worker_id,
            )
            return None

    def _try_mark_failed(self, request_id: str, error_code: str) -> bool:
        try:
            self.repository.mark_failed(
                request_id=request_id,
                lease_owner=self.worker_id,
                error_code=error_code,
            )
            return True
        except ValueError:
            return False
        except Exception:
            logger.exception(
                "chat request failure finalization failed: request_id=%s "
                "worker_id=%s error_code=%s",
                request_id,
                self.worker_id,
                error_code,
            )
            return False

    def _fail_claimed(self, claimed: ClaimedRequest, error_code: str) -> None:
        if not self._try_mark_failed(claimed.context.request_id, error_code):
            return
        self._emit_claimed_status(
            "chat_request_failed",
            claimed,
            "failed",
            error_code=error_code,
            sequence=1,
        )

    def _emit_claimed_status(
        self,
        event_type: str,
        claimed: ClaimedRequest,
        status: str,
        *,
        error_code: str | None = None,
        sequence: int | None = None,
    ) -> None:
        context = claimed.context
        self._emit_status(
            event_type,
            request_id=context.request_id,
            conversation_id=context.conversation_id,
            turn_id=context.turn_id,
            channel=context.identity.channel,
            status=status,
            error_code=error_code,
            sequence=sequence,
        )

    def _emit_status(self, event_type: str, **payload: Any) -> None:
        if payload.get("error_code") is None:
            payload.pop("error_code", None)
        if payload.get("sequence") is None:
            payload.pop("sequence", None)
        try:
            self.emit(event_type, **payload)
        except Exception:
            logger.exception(
                "chat request event emit failed: event_type=%s request_id=%s",
                event_type,
                payload.get("request_id"),
            )

    @staticmethod
    def _terminal_sequence(result_data: dict[str, Any]) -> int:
        try:
            return int(result_data.get("event_sequence") or 0) + 1
        except (TypeError, ValueError):
            return 1
