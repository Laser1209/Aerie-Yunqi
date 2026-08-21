# Debug Session: Selfie POV Forced

Status: [OPEN]
Session: selfie-pov-forced

## Symptom

The user expects a requested subject photo such as shoes, but the generated prompt and image still use a self-held-phone selfie composition.

## Hypotheses

- H1: `role_selfie` intent routing forces a selfie template regardless of the requested subject.
- H2: `user_raw` reaches the prompt resolver but the modular spec is empty or does not override the default selfie scene.
- H3: `_ensure_selfie_pov` rewrites every character-image prompt back into selfie POV at the final output boundary.
- H4: The inspected production log belongs to an older request or an old backend process.

## Evidence

- `logs/image_production_timeline.jsonl:169-175` is the latest `看看腿` request. It still records `prompt.spec={}`, `source=default`, and the fixed `role_selfie` base scene `坐在工作室书桌前，左手托腮`.
- `core/companion.py:3636-3648` confirms that the fixed托腮自拍 scene is emitted by the `role_selfie` base template before final POV handling.
- `core/companion.py:628-648` only appends selfie POV when missing; it does not create the托腮 scene. H3 is rejected as the primary cause.
- `core/pipeline.py:1831-1834` includes `user_raw` in the chat candidate.
- `world_service/storage/sqlite_store.py:312-354` previously rebuilt the persisted image candidate from a whitelist that omitted `user_raw`. The field was lost before the consumer and prompt resolver.
- The latest production logs do not contain the new consumer propagation fields, confirming the running request was from before the sidecar fix was loaded.

Confirmed root cause: the world sidecar serializer dropped `user_raw`, so the modular parser received no instruction and the `role_selfie` fallback remained active.

## Fix

- `world_service/storage/sqlite_store.py:_image_candidate_payload` now preserves `user_raw` in the public image candidate payload.
- The previously applied consumer fix preserves the same field when reconstructing the internal candidate.
- The existing modular parser and POV logic remain unchanged.

## Verification

- Sidecar propagation assertion passed: `sidecar user_raw propagation: PASS`.
- Consumer and modular prompt regression tests passed: 60 tests.
- Full test command exited successfully, with one truncated failure marker in the terminal output; the targeted image suites are the authoritative passing regression set for this change.
- A fresh backend restart and a new `看看腿` request are required for post-fix production-log proof.
