# Debug Session: Modular Prompt Flattened

Status: [OPEN]
Session: modular-prompt-flattened

## Symptom

The production timeline records a completed `role_selfie` prompt as one flattened paragraph. The expected modular prompt sections are not visible in the final output.

## Hypotheses

- H1: Modular sections are generated but flattened before the final prompt is recorded or sent.
- H2: `role_selfie` still uses the legacy full-persona template.
- H3: The modular parser does not match this request and falls back to the full-persona path.
- H4: The relay or deterministic fallback joins modular sections into natural language.
- H5: The current timeline records only the final string and omits module-level evidence.

## Evidence

- `logs/image_production_timeline.jsonl:132-138` shows `route_mode=FULL`, `prompt.spec={}`, `source=default`, and the fixed full-persona desk scene in `prompt.base`.
- `core/companion.py:3456-3461` only parses modular dimensions when `scene=local_send` and `candidate.user_raw` is non-empty.
- `core/pipeline.py:1831-1834` constructs chat image candidates with `user_raw=msg.content`.
- `core/world_image_candidates.py:608-645` reconstructs candidates from event payloads but does not copy `user_raw` into the returned candidate.
- The consumer therefore receives the original event without the field in its internal candidate, records `prompt.spec` as `default`, and never reaches `_compose_modular_prompt` with user input.

Confirmed: the modular prompt logic is not failing at composition. The raw user instruction is lost at the consumer event-to-candidate boundary.

Instrumentation added at `core/world_image_candidates.py:350` records whether `user_raw` exists in the event payload and in the reconstructed candidate. No business behavior was changed by this instrumentation.

## Fix

- `core/world_image_candidates.py:_candidate_from_event` now preserves `payload.user_raw` as `candidate.user_raw`.
- This is the minimal boundary fix: the existing `_semantic_photo_spec` → `_extract_photo_spec` → `_compose_modular_prompt` chain remains unchanged.
- The temporary instrumentation at `candidate.created` records payload/candidate propagation for the next real request.

## Verification

- Direct event reconstruction assertion passed: `user_raw propagation: PASS`.
- Prompt/image consumer regression tests passed: 70 tests.
- `core/world_image_candidates.py` diagnostics are clean.
- `tests/test_pipeline.py` has 4 unrelated existing fixture failures because the brain mock returns the unavailable-brain fallback; no image-prompt assertions fail.
- A real post-fix production request is still required to compare `prompt.spec.source` and the final prompt against the pre-fix timeline.
