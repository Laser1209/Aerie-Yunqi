---
title: Task 07-baseline
tags: [aerie, task, phase07, core]
kind: task
task_id: TASK-07-001
phase: Phase 07
subsystem: core
status: done
priority: P1
dependencies: ["TASK-06-001"]
risk: medium
decision_required: false
feature_flag: chat_stream_v1
migration: false
files: ["electron/src/renderer/js/chat.js", "electron/src/renderer/styles/main.css", "electron/tests/chat-request-queue.test.js", "core/brain.py", "tests/test_brain_provider_routing.py"]
acceptance_ids: ["A-07-01", "A-07-02"]
rollback_ready: true
owner: core-team
evidence: ["file:///E:/Agent_reply/electron/src/renderer/js/chat.js", "file:///E:/Agent_reply/electron/src/renderer/styles/main.css", "file:///E:/Agent_reply/electron/tests/chat-request-queue.test.js", "file:///E:/Agent_reply/core/brain.py", "file:///E:/Agent_reply/tests/test_brain_provider_routing.py"]
progress_note: "2026-07-21: renderer typing bubble, request rebinding, reduced-motion fallback, chat_stream_v1-off path, optional explicit TTS provider wiring, and rollback matrix checks are green."
---
# Task 07-baseline
> [!todo] Phase 07
> delta 临时气泡、最终语义拆分、Typing 与 Persona Pacing；验收目标：Typing/首 delta/取消/多气泡顺序达标。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `chat_stream_v1` 关闭后的旧路径
- [x] 显式配置 TTS Provider 时接入 OpenAI-compatible `/audio/speech`，未配置时保持无外部调用的 stub 降级
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## Evidence
- 2026-07-21：`node --test electron/tests/chat-request-queue.test.js` → `15 passed`；`node --test electron/tests/sse-bridge.test.js` → `5 passed`。
- 2026-07-21：`pytest -q tests/test_phase5_event_stream.py` → `5 passed`；`pytest -q tests/test_phase4_integration.py -k flag_rollback_matrix` → `1 passed`。
- 2026-07-21 TTS provider hardening Red: explicit TTS provider tests returned `1 failed, 1 passed` because Brain still returned stub.
- 2026-07-21 TTS provider hardening Green: `python -m pytest tests/test_brain_provider_routing.py::test_speak_text_uses_explicit_openai_compatible_tts_provider tests/test_brain_provider_routing.py::test_speak_text_without_explicit_provider_keeps_stub -q` -> `2 passed`；`python -m pytest tests/test_brain_provider_routing.py tests/test_phase10_image_workflow.py -q` -> `18 passed, 4 warnings`。
- 2026-07-21 TTS provider hardening Regression: `python -m py_compile core/brain.py` passed；`python -m pytest tests -q` -> `538 passed, 6 warnings`；`node --test electron/tests/*.test.js` -> `23 passed`；`npm run check:all` in `electron` passed；workspace provider-key scan OK。

## 链接
[[Phase 07]] · [[90_全局验收清单]] · [[92_回滚演练]]
