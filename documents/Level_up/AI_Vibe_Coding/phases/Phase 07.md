---
title: Phase 07 - 拟人化流式、Typing、多气泡与 Pacing
kind: phase
phase: Phase 07
status: done
progress_note: "2026-07-21: renderer typing-bubble, request rebinding, reduced-motion fallback, chat_stream_v1-off path, optional Brain and multimodal-output TTS provider wiring, and rollback matrix checks are green."
tags: [aerie, phase, phase07]
---
# Phase 07：拟人化流式、Typing、多气泡与 Pacing
> [!info] 执行边界
> 只按获批实施计划执行；当前阶段未通过验收时停止后续阶段。

## 目标
delta 临时气泡、最终语义拆分、Typing 与 Persona Pacing；保持兼容、可观测与可回滚。

## 非目标
不整体重写 Pipeline；不删除旧表或旧文件；不创建平行 v2；不复制疑似凭据。

## 依赖
- Phase 06
- [[05_Feature_Flag与回滚矩阵]]、[[06_AI_Vibe_Coding批次规约]]

## 当前代码证据
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [api_server.py](file:///E:/Agent_reply/core/api_server.py)
- [brain.py](file:///E:/Agent_reply/core/brain.py)
- [multimodal_output.py](file:///E:/Agent_reply/voice/multimodal_output.py)
- [test_brain_provider_routing.py](file:///E:/Agent_reply/tests/test_brain_provider_routing.py)
- [test_multimodal_output_tts.py](file:///E:/Agent_reply/tests/test_multimodal_output_tts.py)

## 文件范围
- 计划修改或演进：`core/pipeline.py`、`electron/src/renderer/js/chat.js`
- 新文件仅限计划列明的模块、迁移和测试。
- 执行任务：[[Task 07-baseline]]

## 数据/API 合同
- Feature Flag：`chat_stream_v1`。
- delta 临时气泡、最终语义拆分、Typing 与 Persona Pacing。
- ID、状态、sequence、幂等键和所有权边界必须可审计。
- 涉及迁移时支持 backup、dry-run、checksum、幂等、cursor、断点续跑与守恒。

## TDD 步骤
1. 先新增失败测试覆盖主路径、异常路径与回滚路径。
2. 实现最小变更使测试通过，保留兼容适配器。
3. 运行受影响模块测试与完整回归。
4. 验证 Flag 关闭、迁移/协议恢复和 Evidence 脱敏。

## 验收
- [x] Typing/首 delta/取消/多气泡顺序达标
- [x] Feature Flag 关闭恢复旧路径且不丢新数据
- [x] 不产生重复副作用、历史串线或敏感值泄漏

## 回滚
关闭 `chat_stream_v1`，恢复备份或旧读路径；保留新表、元数据、Outbox、旧表和旧文件。

## 指标
成功率、延迟、重复计数、守恒差异、恢复时间和回滚耗时；禁止记录消息正文、个人数据或凭据。

## 提交边界
只提交 Phase 07 相关源码、测试、迁移与文档；不混入无关重构、格式化或构建产物。

## Evidence
- [实施计划](file:///E:/Agent_reply/.trae/documents/Aerie_AI_Vibe_Coding_全面升级实施计划.md)
- [pipeline.py](file:///E:/Agent_reply/core/pipeline.py)
- [chat.js](file:///E:/Agent_reply/electron/src/renderer/js/chat.js)
- [[90_全局验收清单]] · [[92_回滚演练]]
- 2026-07-21：`node --test electron/tests/chat-request-queue.test.js` → `15 passed`；`node --test electron/tests/sse-bridge.test.js` → `5 passed`。
- 2026-07-21：`pytest -q tests/test_phase5_event_stream.py` → `5 passed`；`pytest -q tests/test_phase4_integration.py -k flag_rollback_matrix` → `1 passed`。
- 2026-07-21 TTS provider hardening Red: `python -m pytest tests/test_brain_provider_routing.py::test_speak_text_uses_explicit_openai_compatible_tts_provider tests/test_brain_provider_routing.py::test_speak_text_without_explicit_provider_keeps_stub -q` -> `1 failed, 1 passed`，目标缺口为显式 TTS provider 仍返回 stub。
- 2026-07-21 TTS provider hardening Green: `Brain.speak_text()` 在显式 `AERIE_TTS_*`/`OPENAI_TTS_*` 配置存在时调用 OpenAI-compatible `/audio/speech` 并返回 `audio_bytes_b64`、`mime_type`、`voice`；未显式配置时保持 stub 且不外呼。
- 2026-07-21 TTS provider hardening Regression: `python -m py_compile core/brain.py` passed；`python -m pytest tests/test_brain_provider_routing.py tests/test_phase10_image_workflow.py -q` -> `18 passed, 4 warnings`；`python -m pytest tests -q` -> `538 passed, 6 warnings`；`node --test electron/tests/*.test.js` -> `23 passed`；`npm run check:all`（electron 工作目录）通过；`python tools/scan_provider_key_patterns.py` -> `PROVIDER_KEY_SCAN_OK`。
- 2026-07-21 Multimodal TTS provider Red: `python -m pytest tests/test_multimodal_output_tts.py -q` -> `2 failed`，目标缺口为 `TTSProvider.OPENAI` 未实现且会落到 Edge TTS fallback。
- 2026-07-21 Multimodal TTS provider Green: `voice.multimodal_output.EnhancedTTSEngine` 的 `TTSProvider.OPENAI` 显式调用 OpenAI-compatible `/audio/speech`，写入 `data/tts/<output_name>.<format>`；无显式 key 时返回 `no API key`，不落到 Edge，不发送 QQ 或外部投递副作用。
- 2026-07-21 Multimodal TTS provider Regression: `python -m py_compile voice/multimodal_output.py` passed；`python -m pytest tests/test_multimodal_output_tts.py tests/test_brain_provider_routing.py -q` -> `11 passed`；`PYTHONPATH=E:\Agent_reply PYTHONIOENCODING=utf-8 PYTHONUTF8=1 python tests/e2e/e2e_s4_multimodal_output_verify.py` -> `11/11 通过`；`python -m pytest tests -q` -> `540 passed, 6 warnings`；`node --test electron/tests/*.test.js` -> `23 passed`；`npm run check:all`（electron 工作目录）通过；`python tools/scan_provider_key_patterns.py` -> `PROVIDER_KEY_SCAN_OK`。
