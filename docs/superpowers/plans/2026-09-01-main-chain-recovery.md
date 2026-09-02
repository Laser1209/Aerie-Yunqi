# Main Chain Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore a verifiable desktop chat loop from backend cold start through persisted response without changing production data or credentials.

**Architecture:** Keep the existing Electron -> preload -> FastAPI -> request worker -> Pipeline -> SSE flow. Fix deterministic startup scope, make model-disabled mode a process-wide outbound gate, preserve request metadata through retries and worker reconstruction, and repair the renderer endpoint contract. Validate in an isolated data directory with process-level and database evidence.

**Tech Stack:** Python 3.14, FastAPI/Uvicorn, SQLite, asyncio, Electron renderer JavaScript, pytest.

## Global Constraints

- Use an isolated `AERIE_DATA_DIR` for runtime tests; do not alter `data/aerie.db`.
- Do not print, copy, rotate, or add any API token, key, cookie, or password.
- Preserve existing untracked `main.js` and root `package.json`.
- Keep World sidecar/in-process selection unchanged in this phase; record it as a follow-up.
- Every change must have a focused regression test or a reproducible smoke check.

### Task 1: Fix Companion cold-start scope error

**Files:**
- Modify: `core/companion.py` around the `Companion.__init__` proactive planner import
- Test: `tests/` existing Companion startup tests, plus a focused startup regression test in the nearest existing test module

**Interfaces:**
- Consumes: module-level `data_dir` imported from `core.paths`
- Produces: `Companion(...)` can evaluate the earlier Chroma path before binding optional proactive components

- [ ] **Step 1: Add a regression test that constructs the initialization path with optional planner imports mocked and asserts no `UnboundLocalError` is raised.**
- [ ] **Step 2: Run the focused test and capture the current failure.**
- [ ] **Step 3: Remove the inner `from core.paths import data_dir` binding and retain the module-level import; use a private alias only if a local import is unavoidable.**
- [ ] **Step 4: Run the focused test and `python -m compileall core main.py`.**

### Task 2: Make model-disabled mode cover implicit provider calls

**Files:**
- Modify: `core/emotion_engine.py`, `core/companion.py`, and the shared model/provider configuration path identified by existing tests
- Test: focused emotion/provider gate tests and existing LLM caller tests

**Interfaces:**
- Consumes: `AERIE_DISABLE_MODEL_CALLS` semantics already implemented by `core/llm_caller.py`
- Produces: no PAD provider HTTP request or provider health/credit probe when the disable flag is truthy; deterministic local fallback remains available

- [ ] **Step 1: Add tests patching provider HTTP and health-probe clients, set `AERIE_DISABLE_MODEL_CALLS=1`, and assert zero outbound calls plus a valid fallback result.**
- [ ] **Step 2: Run those tests to expose the uncovered calls.**
- [ ] **Step 3: Add one shared predicate or existing-config hook and check it before emotion PAD inference and health/credit probing; avoid duplicating environment parsing.**
- [ ] **Step 4: Run provider/emotion tests and the isolated Phase 4 integration subset.**

### Task 3: Preserve request context and correct worker terminal handling

**Files:**
- Modify: `core/chat_request_repository.py`, `core/chat_request_worker.py`
- Test: existing chat request repository/worker tests

**Interfaces:**
- Consumes: persisted request row fields including `persona_id`, raw event and message metadata
- Produces: retry/reloaded `RequestContext` retains persona and worker-created `IncomingMessage` retains source metadata; incomplete Pipeline results do not become completed batches

- [ ] **Step 1: Add repository round-trip tests for `persona_id` on normal load and retry creation.**
- [ ] **Step 2: Add worker tests asserting raw event, platform message id, timestamp and original message type survive reconstruction.**
- [ ] **Step 3: Run focused tests and document the current failing assertions.**
- [ ] **Step 4: Restore the missing fields in `_row_to_context()` and `create_retry()`, then pass stored metadata through worker reconstruction.**
- [ ] **Step 5: Gate `mark_batch_completed()` on a complete successful worker result; route empty/partial/error outcomes to the existing failure/retry method.**
- [ ] **Step 6: Run all chat-request tests and a SQLite isolated smoke check.**

### Task 4: Repair renderer API contract and dynamic backend origin

**Files:**
- Modify: `electron/src/renderer/js/app.js`, `electron/src/renderer/js/chat.js`, `electron/src/renderer/js/proactive-manager.js`, and the existing renderer API helper/preload contract
- Test: existing Electron unit tests plus focused endpoint/URL tests

**Interfaces:**
- Consumes: `window.aerie.api.request`, `AERIE_BACKEND_PORT`, backend `/api/persona/avatar` and `/api/proactive/status`
- Produces: no call to undefined `_setApiConnectivity`, avatar requests hit the published persona endpoint, file-origin proactive requests use the preload bridge, and status rendering reads fields actually returned by the API

- [ ] **Step 1: Add focused tests or static assertions for each broken endpoint and undefined method.**
- [ ] **Step 2: Run the focused Electron tests to capture baseline failures.**
- [ ] **Step 3: Replace the undefined connectivity calls with the existing connectivity state/helper, update avatar endpoint, route proactive calls through the bridge, and derive API origin from the configured backend port.**
- [ ] **Step 4: Run the complete Electron unit suite and record any unrelated known failures separately.**

### Task 5: Isolated end-to-end verification

**Files:**
- Create: `docs/diagnostics/main-chain-recovery-2026-09-01.md`
- Modify: none unless a test harness requires it

**Interfaces:**
- Consumes: fixes from Tasks 1-4
- Produces: evidence-backed runtime report with process, HTTP, SSE/worker and SQLite checks

- [ ] **Step 1: Start `main.py` with a fresh temporary `AERIE_DATA_DIR`, `AERIE_DISABLE_MODEL_CALLS=1`, and an alternate backend port.**
- [ ] **Step 2: Poll `/api/health` and startup progress until ready or terminal failure.**
- [ ] **Step 3: Submit one chat request through the public API, collect the request id and event stream/poll result, and assert a terminal success or explicit local fallback.**
- [ ] **Step 4: Query the isolated SQLite database and assert request, turn and message terminal records are consistent.**
- [ ] **Step 5: Stop only the isolated process, preserve logs, and write the report with exact commands, outcomes, and residual blockers.**

