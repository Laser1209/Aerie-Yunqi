"""Aerie · 云栖 v13.9.8 — Self-Evolver (Phase 9 Batch 6).

Detects capability gaps in the live tool registry and proposes
*new* tools for the user to approve. Proposals are surfaced as
cards in the brain center, sandbox-previewed, and only registered
into the live tool registry when the user explicitly approves.

Design contract (per phase9-batch3-6-execution-plan-v1.md §B6):

  - High-sensitivity trigger: 2 conditions both met
      (1) react_trace.thought contains a "cannot / no tool" keyword
      (2) at least one tool call in tool_results failed
  - On trigger:
      * synthesize a tool schema with name/description/parameters
      * run SandboxRunner.preview() to render safety + risk + sim output
      * persist to self_evolve_log (user_decision='pending')
      * emit('self_evolve_proposed', id=..., safety=...) SSE event
  - The user can later:
      * GET    /api/self_evolve/{id}            — fetch proposal
      * POST   /api/self_evolve/{id}/preview    — re-render sandbox
      * POST   /api/self_evolve/{id}/approve    — mark approved +
                                                   register in tool_registry
      * POST   /api/self_evolve/{id}/reject     — mark rejected
  - Idempotency: approve/reject are no-ops if the proposal is already
    in a final state, so the user can spam-click without poisoning the
    tool registry.

Why "提议+沙箱预演" instead of letting the AI auto-register:

  - The user's standing order is to keep humans in the loop for any
    code-level mutation. We surface the gap + a textual preview and
    wait for thumbs-up.
  - Even on approval, we never `exec()` anything — we only register a
    function stub or a schema entry that the LLM can later choose to
    call. The actual implementation is a follow-up engineering task.

All log writes are wrapped in try/except — a self-evolution failure
must NEVER block the main pipeline.
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

from core.chat_events import emit as stderr_emit
from core.sandbox_runner import SandboxRunner

logger = logging.getLogger(__name__)


# ── Trigger keywords (high-sensitivity mode) ─────────
# If the LLM's <think> block contains any of these, we treat the
# thought as a "capability gap" signal. Keep this list SHORT and
# precise — false positives flood the user with proposals.
_GAP_KEYWORDS: tuple[str, ...] = (
    # Chinese
    "无法", "没有工具", "做不到", "不会", "缺少", "没办法",
    "没这个能力", "不能", "还不支持",
    # English (for mixed/EN-system-prompt replies)
    "I cannot", "i can't", "no tool", "lack of", "missing tool",
    "not supported", "not available", "unable to",
)

# Compiled once for speed.
_GAP_RE = re.compile(
    "|".join(re.escape(k) for k in _GAP_KEYWORDS),
    flags=re.IGNORECASE,
)


# ── Tool-name derivation helpers ──────────────────────
_TOOL_NAME_CLEAN = re.compile(r"[^a-z0-9_]+")
_TOOL_NAME_MAX = 32


def _slugify_tool_name(raw: str) -> str:
    """Turn a freeform gap description into a pythonic tool name.

    Strips non-alphanumeric, lowercases, prepends ``ita_`` so users
    can tell at a glance this is an AI-proposed tool, and clips to
    ``_TOOL_NAME_MAX`` chars.
    """
    if not raw:
        return "ita_unnamed_tool"
    cleaned = _TOOL_NAME_CLEAN.sub("_", raw.strip().lower()).strip("_")
    if not cleaned:
        cleaned = "ita_unnamed_tool"
    # Ensure leading underscore isn't allowed (python identifier).
    cleaned = cleaned.lstrip("_")
    if not cleaned:
        cleaned = "ita_unnamed_tool"
    if not cleaned.startswith("ita_"):
        cleaned = "ita_" + cleaned
    return cleaned[:_TOOL_NAME_MAX]


def _derive_tool_spec(
    user_message: str,
    thought: str,
    failed_tool: str | None,
) -> dict:
    """Heuristically derive a proposed tool schema from the gap context.

    The output is a *placeholder* tool spec — its purpose is to give
    the user something concrete to review. Real implementation is
    expected later as a follow-up engineering task.
    """
    # Pick the most informative source for the description.
    src = (thought or "").strip() or (user_message or "").strip()
    short_desc = src[:200]
    # Truncate to a single sentence if possible.
    if "。" in short_desc:
        short_desc = short_desc.split("。", 1)[0] + "。"
    elif "." in short_desc:
        short_desc = short_desc.split(".", 1)[0] + "."

    base = failed_tool or _slugify_tool_name(short_desc)
    name = _slugify_tool_name(base + "_" + short_desc[:12].strip())

    return {
        "name": name,
        "description": short_desc or "auto-proposed tool",
        "parameters": {
            "type": "object",
            "properties": {
                "input": {
                    "type": "string",
                    "description": "freeform input for the tool",
                },
            },
            "required": ["input"],
        },
        "trigger": thought[:200] if thought else "",
        "rationale": (
            "detected a capability gap in react_trace; user asked for something "
            "the current tool registry cannot deliver."
        ),
    }


class SelfEvolver:
    """Detects capability gaps and proposes new tools.

    Lifecycle:
      - ``maybe_propose()`` is called from the pipeline after every
        successful cognition commit. Returns proposal id or None.
      - User reviews via the brain center UI; approve/reject is routed
        through ``approve()`` / ``reject()`` (or via HTTP endpoints
        that wrap these).
    """

    def __init__(
        self,
        db: Any,
        tool_registry: Any,
        brain: Any = None,
        sandbox: SandboxRunner | None = None,
    ) -> None:
        self._db = db
        self._tool_registry = tool_registry
        self._brain = brain
        self._sandbox = sandbox or SandboxRunner()
        # Cache of the last few proposals for quick read in UI.
        self._last_proposal_id: int | None = None

    # ── Trigger detection ────────────────────────────
    @staticmethod
    def _detect_gap(
        react_trace: dict | None,
        tool_results: list[dict] | None,
    ) -> tuple[bool, str | None]:
        """Return (has_gap, first_failed_tool_name)."""
        if not react_trace:
            return False, None
        thought = (react_trace.get("thought") or "").strip()
        if not thought:
            return False, None
        if not _GAP_RE.search(thought):
            return False, None
        # Find first failed tool.
        for tr in (tool_results or []):
            try:
                if tr and tr.get("success") is False:
                    return True, tr.get("name")
            except Exception:
                continue
        return False, None

    # ── Public API ───────────────────────────────────
    def maybe_propose(
        self,
        user_id: int,
        user_message: str,
        react_trace: dict | None,
        tool_results: list[dict] | None = None,
    ) -> int | None:
        """Inspect a react trace + tool results; propose a new tool if a gap
        is detected. Returns the new proposal id, or None on no-op / error.

        All DB writes and emits are wrapped in try/except so this method
        MUST never raise.
        """
        try:
            has_gap, failed_tool = self._detect_gap(react_trace, tool_results)
            if not has_gap:
                return None

            thought = (react_trace or {}).get("thought", "")
            spec = _derive_tool_spec(
                user_message=user_message,
                thought=thought,
                failed_tool=failed_tool,
            )

            # Render the sandbox preview.
            preview = self._sandbox.preview(spec)
            if not preview.get("ok"):
                logger.warning(
                    "self_evolver sandbox rejected spec name=%s reason=%s",
                    spec.get("name"), preview.get("error"),
                )
                # We still record the proposal — the user can read why
                # the sandbox refused and decide.

            # Persist the proposal.
            ts = int(time.time() * 1000)
            row_id = self._db.insert(
                "self_evolve_log",
                {
                    "ts": ts,
                    "user_id": int(user_id) if user_id is not None else None,
                    "trigger_kind": "capability_gap",
                    "description": spec.get("description", "")[:1000],
                    "proposed_tool_schema": json.dumps(
                        spec, ensure_ascii=False
                    ),
                    "safety_check": preview.get("safety_check", "?"),
                    "user_decision": "pending",
                },
            )
            self._last_proposal_id = row_id

            # Real-time push to the brain center.
            try:
                stderr_emit(
                    "self_evolve_proposed",
                    id=row_id,
                    user_id=int(user_id) if user_id is not None else None,
                    name=spec.get("name"),
                    safety=preview.get("safety_check", "?"),
                    description=spec.get("description", ""),
                    requires_approval=bool(preview.get("requires_approval")),
                    ts=ts,
                )
            except Exception:
                logger.exception("self_evolve_proposed emit error")

            logger.info(
                "self_evolve_proposed: id=%s user_id=%s name=%s safety=%s",
                row_id, user_id, spec.get("name"), preview.get("safety_check"),
            )
            return row_id
        except Exception:
            logger.exception("self_evolver.maybe_propose error")
            return None

    # ── Read API (used by HTTP layer) ───────────────
    def list_proposals(
        self,
        user_id: int | None = None,
        status: str = "pending",
        limit: int = 50,
    ) -> list[dict]:
        """Return a list of proposal rows (newest first)."""
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if status and status != "all":
                clauses.append("user_decision = ?")
                params.append(status)
            if user_id is not None:
                clauses.append("user_id = ?")
                params.append(int(user_id))
            sql = (
                "SELECT id, ts, user_id, trigger_kind, description, "
                "proposed_tool_schema, safety_check, user_decision, created_at "
                "FROM self_evolve_log"
            )
            if clauses:
                sql += " WHERE " + " AND ".join(clauses)
            sql += " ORDER BY id DESC LIMIT ?"
            params.append(int(limit))
            return self._db.query(sql, tuple(params))
        except Exception:
            logger.exception("self_evolver.list_proposals error")
            return []

    def get_proposal(self, proposal_id: int) -> dict | None:
        try:
            return self._db.query_one(
                "SELECT * FROM self_evolve_log WHERE id = ?",
                (int(proposal_id),),
            )
        except Exception:
            logger.exception("self_evolver.get_proposal error")
            return None

    def render_preview(self, proposal_id: int) -> dict:
        """Re-run sandbox preview on an existing proposal.

        Returns a dict in the same shape as ``SandboxRunner.preview()``.
        On error, returns ``{"ok": False, "error": "..."}``.
        """
        row = self.get_proposal(proposal_id)
        if not row:
            return {"ok": False, "error": "not_found"}
        raw = row.get("proposed_tool_schema")
        if not raw:
            return {"ok": False, "error": "missing_schema"}
        try:
            spec = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            return {"ok": False, "error": f"schema_parse_failed: {e}"}
        try:
            return self._sandbox.preview(spec)
        except Exception as e:
            logger.exception("render_preview error")
            return {"ok": False, "error": f"sandbox_error: {e}"}

    # ── Decision API ─────────────────────────────────
    def _set_decision(
        self,
        proposal_id: int,
        decision: str,
    ) -> dict:
        """Internal: mark a proposal as approved/rejected (idempotent)."""
        if decision not in ("approved", "rejected"):
            return {"status": "error", "reason": "invalid_decision"}
        row = self.get_proposal(proposal_id)
        if not row:
            return {"status": "error", "reason": "not_found"}
        current = row.get("user_decision") or "pending"
        if current == decision:
            # Idempotent: already in the desired final state.
            return {
                "status": "ok",
                "id": int(proposal_id),
                "decision": decision,
                "already": True,
            }
        if current in ("approved", "rejected"):
            # Already finalized with a *different* decision — refuse.
            return {
                "status": "error",
                "reason": f"already_{current}",
                "id": int(proposal_id),
            }
        try:
            self._db.update(
                "self_evolve_log",
                {"user_decision": decision},
                "id = ?",
                (int(proposal_id),),
            )
        except Exception as e:
            logger.exception("self_evolve decision write error")
            return {"status": "error", "reason": f"db_error: {e}"}
        try:
            stderr_emit(
                "self_evolve_decided",
                id=int(proposal_id),
                decision=decision,
            )
        except Exception:
            pass
        return {
            "status": "ok",
            "id": int(proposal_id),
            "decision": decision,
        }

    def approve(self, proposal_id: int) -> dict:
        """Approve a proposal. Registers the proposed tool in the live
        tool registry (if it accepts a `register` call). Returns a
        status dict.
        """
        result = self._set_decision(proposal_id, "approved")
        if result.get("status") != "ok":
            return result
        # If this is a fresh approval (already=False), try registering.
        if not result.get("already"):
            row = self.get_proposal(proposal_id) or {}
            raw = row.get("proposed_tool_schema")
            spec: dict | None = None
            if raw:
                try:
                    spec = json.loads(raw) if isinstance(raw, str) else raw
                except Exception:
                    spec = None
            if spec and self._tool_registry is not None:
                try:
                    self._register_proposed_tool(spec)
                except Exception:
                    logger.exception(
                        "self_evolver tool register error id=%s",
                        proposal_id,
                    )
        return result

    def reject(self, proposal_id: int) -> dict:
        """Reject a proposal. No tool registration happens."""
        return self._set_decision(proposal_id, "rejected")

    # ── Internal: tool registration (best-effort) ────
    def _register_proposed_tool(self, spec: dict) -> None:
        """Register the proposed tool into the live registry.

        We register a *placeholder* function that just returns a
        confirmation string. The actual implementation is intentionally
        out of scope for the AI-proposal flow — the user is expected
        to write real code later. The point of approval is to make the
        LLM aware of the new tool so it can be called.
        """
        name = (spec or {}).get("name")
        if not name:
            return
        description = (spec or {}).get("description", "")
        parameters = (spec or {}).get("parameters", {"type": "object", "properties": {}})

        # Build a placeholder callable.
        def _placeholder(**kwargs) -> dict:
            return {
                "status": "placeholder",
                "tool": name,
                "received": kwargs,
                "note": (
                    "this tool was proposed by the self-evolution mechanism "
                    "and approved, but its real implementation is pending. "
                    "Override this stub in tools/__init__.py when ready."
                ),
            }

        schema = {
            "description": description,
            "parameters": parameters,
        }
        try:
            self._tool_registry.register(name, _placeholder, schema)
            logger.info("self_evolver registered tool: %s", name)
        except Exception:
            # Register may fail if the registry contract differs; log
            # but don't raise — the proposal is already approved.
            logger.exception(
                "tool_registry.register failed for proposed tool %s", name
            )

    # ── Stats (cheap, used by cognition panel) ───────
    def stats(self) -> dict:
        try:
            total = self._db.query_one(
                "SELECT COUNT(*) AS n FROM self_evolve_log"
            ) or {"n": 0}
            pending = self._db.query_one(
                "SELECT COUNT(*) AS n FROM self_evolve_log "
                "WHERE user_decision = 'pending'"
            ) or {"n": 0}
            approved = self._db.query_one(
                "SELECT COUNT(*) AS n FROM self_evolve_log "
                "WHERE user_decision = 'approved'"
            ) or {"n": 0}
            rejected = self._db.query_one(
                "SELECT COUNT(*) AS n FROM self_evolve_log "
                "WHERE user_decision = 'rejected'"
            ) or {"n": 0}
            return {
                "total": total["n"],
                "pending": pending["n"],
                "approved": approved["n"],
                "rejected": rejected["n"],
            }
        except Exception:
            logger.exception("self_evolver.stats error")
            return {"total": 0, "pending": 0, "approved": 0, "rejected": 0}

    @property
    def last_proposal_id(self) -> int | None:
        return self._last_proposal_id
