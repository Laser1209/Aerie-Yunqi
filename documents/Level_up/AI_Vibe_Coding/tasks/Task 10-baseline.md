---
title: Task 10-baseline
tags: [aerie, task, phase10, image]
kind: task
task_id: TASK-10-001
phase: Phase 10
subsystem: image
status: done
progress_note: "2026-07-21: implemented auditable ImageWorkflow with safety review, injectable generation/vision providers, JSON idempotency audit, asset persistence, delivery planning, API endpoints, flag-off no-side-effect rollback, and optional explicit OpenAI-compatible image/vision provider wiring."
priority: P1
dependencies: ["TASK-09-001"]
risk: medium
decision_required: false
feature_flag: image_assets_v1
migration: false
files: ["core/image_service.py", "core/api_server.py", "core/brain.py", "tests/test_phase10_image_workflow.py", "tests/test_brain_provider_routing.py"]
acceptance_ids: ["A-10-01", "A-10-02", "A-10-03"]
rollback_ready: true
owner: image-team
evidence: ["file:///E:/Agent_reply/core/image_service.py", "file:///E:/Agent_reply/core/api_server.py", "file:///E:/Agent_reply/core/brain.py", "file:///E:/Agent_reply/tests/test_phase10_image_workflow.py", "file:///E:/Agent_reply/tests/test_brain_provider_routing.py"]
---
# Task 10-baseline
> [!todo] Phase 10
> Vision/Generation Provider、审核、资产与 Delivery 分离；验收目标：超时、失败、拒绝不产生重复外部副作用。

- [x] 先提交失败测试证据
- [x] 完成最小实现与兼容路径
- [x] 验证 `image_assets_v1` 关闭后的旧路径
- [x] 显式配置图片/视觉 Provider 时接入真实 OpenAI-compatible 调用，未配置时保持无外部调用的 stub 降级
- [x] 记录脱敏 Evidence、指标与守恒结果
- [x] 完成回滚演练并更新 `rollback_ready`

## 链接
[[Phase 10]] · [[90_全局验收清单]] · [[92_回滚演练]]

## Evidence
- 2026-07-21 Red: `python -m pytest tests/test_phase10_image_workflow.py -q` -> expected collection error `ModuleNotFoundError: No module named 'core.image_service'`.
- 2026-07-21 Green: `python -m pytest tests/test_phase10_image_workflow.py -q` -> `8 passed, 4 warnings`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `106 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile core/api_server.py core/attachment_handler.py core/chat_request_service.py core/image_service.py` passed; `node --check electron/src/renderer/js/chat.js` passed; `node --check electron/src/renderer/js/chat-uploader.js` passed.
- Rollback: keep `image_assets_v1: false` or set `AERIE_FEATURE_IMAGE_ASSETS_V1=false`; `/api/images/generate` returns `status=disabled`, no provider call, no asset write, no delivery plan, and no `uploads/.image_assets/image_workflows.json` audit file is created on the disabled path.
- 2026-07-21 Provider hardening Red: explicit image/vision provider tests returned `2 failed, 1 passed` because Brain still returned stub.
- 2026-07-21 Provider hardening Green: `python -m pytest tests/test_brain_provider_routing.py::test_generate_image_uses_explicit_openai_compatible_provider tests/test_brain_provider_routing.py::test_generate_image_without_explicit_provider_keeps_stub tests/test_brain_provider_routing.py::test_see_image_uses_explicit_openai_compatible_vision_provider -q` -> `3 passed`; `python -m pytest tests/test_phase10_image_workflow.py -q` -> `9 passed, 4 warnings`.
- 2026-07-21 Provider hardening Regression: `python -m py_compile core/brain.py core/image_service.py` passed；`python -m pytest tests/test_brain_provider_routing.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_phase14_world_image_candidates.py -q` -> `36 passed, 4 warnings`；`python -m pytest tests -q` -> `536 passed, 6 warnings`；`node --test electron/tests/*.test.js` -> `23 passed`；`npm run check:all` in `electron` passed；workspace provider-key scan OK。
