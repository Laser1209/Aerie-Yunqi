---
title: Phase 10 - 图片理解、生成、审核与投递
kind: phase
phase: Phase 10
status: done
progress_note: "2026-07-21: Phase 10 image workflow is green for safety rejection, provider timeout/failure, idempotent retry, feature-flag rollback, vision reference validation, asset persistence, delivery planning, optional OpenAI-compatible image/vision provider wiring, and redacted audit evidence."
tags: [aerie, phase, phase10]
---
# Phase 10：图片理解、生成、审核与投递
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
Vision/Generation Provider、审核、资产与 Delivery 分离；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 09
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [image_service.py](file:///E:/Agent_reply/core/image_service.py)
- [brain.py](file:///E:/Agent_reply/core/brain.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [attachment_handler.py](file:///E:/Agent_reply/core/attachment_handler.py)
- [test_phase10_image_workflow.py](file:///E:/Agent_reply/tests/test_phase10_image_workflow.py)
- [test_brain_provider_routing.py](file:///E:/Agent_reply/tests/test_brain_provider_routing.py)

## 文件范围
- 已修改或演进：`core/api_server.py`、`core/brain.py`、`core/image_service.py`
- 已新增/扩展：`tests/test_phase10_image_workflow.py`、`tests/test_brain_provider_routing.py`
- 未修改 `core/pipeline.py`；图片生成/理解链路通过新增服务和 API 薄接线完成。
- 执行任务：[[Task 10-baseline]]

## 数据/API 合同
- Feature Flag：`image_assets_v1`。
- Vision/Generation Provider、审核、资产与 Delivery 分离。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] 超时、失败、拒绝不产生重复外部副作用
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `image_assets_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 10 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [image_service.py](file:///E:/Agent_reply/core/image_service.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [test_phase10_image_workflow.py](file:///E:/Agent_reply/tests/test_phase10_image_workflow.py)
- [[90_全局验收清单]] · [[92_回滚演练]]
- 2026-07-21 Red: `python -m pytest tests/test_phase10_image_workflow.py -q` -> expected collection error `ModuleNotFoundError: No module named 'core.image_service'`.
- 2026-07-21 Green: `python -m pytest tests/test_phase10_image_workflow.py -q` -> `8 passed, 4 warnings`.
- 2026-07-21 Regression: `python -m pytest tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_api.py tests/test_phase4_chat_request_service.py tests/test_phase4_api.py tests/test_phase8_proactive_feedback.py tests/test_phase1_proactive_baseline.py -q` -> `106 passed, 4 warnings`.
- 2026-07-21 Syntax: `python -m py_compile core/api_server.py core/attachment_handler.py core/chat_request_service.py core/image_service.py` passed; `node --check electron/src/renderer/js/chat.js` passed; `node --check electron/src/renderer/js/chat-uploader.js` passed.
- 2026-07-21 Provider hardening Red: `python -m pytest tests/test_brain_provider_routing.py::test_generate_image_uses_explicit_openai_compatible_provider tests/test_brain_provider_routing.py::test_generate_image_without_explicit_provider_keeps_stub tests/test_brain_provider_routing.py::test_see_image_uses_explicit_openai_compatible_vision_provider -q` -> `2 failed, 1 passed`，目标缺口为显式图片/视觉 provider 仍返回 stub。
- 2026-07-21 Provider hardening Green: 显式 `AERIE_IMAGE_*`/`OPENAI_IMAGE_*` 与 `AERIE_VISION_*`/`OPENAI_VISION_*` 配置存在时，`Brain.generate_image()` 调 OpenAI-compatible `/images/generations` 并返回 `image_bytes_b64`，`Brain.see_image()` 调 `/chat/completions` 并返回 answer；未显式配置时保持 stub、不发起外部调用。新增工作流测试确认 `BrainImageGenerationProvider` 可将 base64 图片字节接入资产持久化链。
- 2026-07-21 Provider hardening Regression: `python -m py_compile core/brain.py core/image_service.py` passed；`python -m pytest tests/test_brain_provider_routing.py tests/test_phase10_image_workflow.py tests/test_upload.py tests/test_phase14_world_image_candidates.py -q` -> `36 passed, 4 warnings`；`python -m pytest tests -q` -> `536 passed, 6 warnings`；`node --test electron/tests/*.test.js` -> `23 passed`；`npm run check:all`（electron 工作目录）通过；`python tools/scan_provider_key_patterns.py` -> `PROVIDER_KEY_SCAN_OK`。
