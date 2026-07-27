---
title: Phase 3 启动审计记录
date: 2026-07-27
change-id: execute-third-correction-p0-fusion
doc-type: audit-record
audit-type: phase-start
phase: Phase 3
status: task-3-3-start-approved
tags:
  - Aerie
  - 第三次修正计划
  - 阶段门禁
  - 启动审计
---

# Phase 3 启动审计记录

> [!warning]
> Phase 3 面向 P0 功能修复与融合闭环实现。当前已批准并完成 Task 3.1、Task 3.2 与 Task 3.3；不得调用真实模型、QQ、外部向量库或执行非隔离 Electron 真实体验测试。

## 关联文档

- 规格：[spec.md](./spec.md)
- 任务：[tasks.md](./tasks.md)
- 检查清单：[checklist.md](./checklist.md)
- 对应验收审计：[Phase3-验收审计记录.md](./Phase3-验收审计记录.md)
- Phase 2 验收：[Phase2-验收审计记录.md](./Phase2-验收审计记录.md)

## 基本信息

| 字段 | 内容 |
| --- | --- |
| 阶段编号 | Phase 3 |
| 阶段名称 | P0 功能修复与融合闭环实现 |
| 审计日期 | 2026-07-27 |
| 审计人 | TRAE |
| 执行负责人 | TRAE |
| 关联任务范围 | Task 3.1-Task 3.3 |
| 关联检查项 | C3.1-C3.4、C3.6-C3.7 |
| 计划开始时间 | 2026-07-27 |
| 预计完成时间 | Task 3.3 验证通过后 |
| 本阶段结论 | Task 3.1-Task 3.3 有条件通过 |

## 阶段目标

- [x] 修复 Electron HTTP JSON 与 SSE UTF-8 chunk 解码。
- [x] 统一桌面附件 Artifact 管线。
- [x] 接入结构化 ImageObservation。
- [ ] 接入 VisualIntentRouter。
- [ ] 补齐前端附件预览与安全动作。
- [ ] 尝试连接专用向量知识库并记录成功或阻塞证据。

## 任务覆盖审计

| 检查项 | 审计问题 | 结论 | 证据/说明 | 补救动作 |
| --- | --- | --- | --- | --- |
| 目标完整性 | 本阶段目标是否覆盖 spec 中对应要求 | 有条件通过 | 已启动并完成 Task 3.1、Task 3.2 与 Task 3.3；Task 3.4-3.6 仍保持未开始门禁，C3.5 因 Artifact 细粒度 part/page/sheet/range 尚未完整仍不勾选 | 后续任务逐项重新审计 |
| 任务完整性 | tasks.md 中对应任务是否全部纳入执行范围 | 通过 | [tasks.md](./tasks.md) 已列 Task 3.1 子任务，且 Electron 解码入口已定位到 `electron/src/main.js` | 执行 TDD 修复 |
| 检查项映射 | checklist.md 中对应检查项是否有验证计划 | 通过 | C3.1-C3.2 验证标准明确：跨 chunk 中文 JSON/SSE 不出现 `�` 且 frame 边界正确 | 增加 Node 回归测试 |
| 交付物明确性 | 每个任务是否有明确落盘文件、测试结果或证据路径 | 通过 | 交付物为 `electron/src/main.js`、`electron/tests/sse-bridge.test.js` 与测试命令输出 | 记录 RED/GREEN 证据 |
| 边界明确性 | 不做事项、不可破坏接口、兼容层要求是否明确 | 通过 | Task 3.1 不触发真实模型、QQ、外部向量库或敏感数据；仅处理本地合成 UTF-8 分块测试 | 保持外部能力禁用 |
| 附件边界 | Task 3.2 是否避免旧新附件事实源分裂 | 通过 | `desktop_attachments.py` 作为桌面附件事实源，`attachment_handler.py` 仅保留旧上传转换工具；`/api/chat/send` 对带 `attachmentId` 的桌面附件只保留 ID 边界 | 增加 API 契约回归 |
| 图片观察边界 | Task 3.3 是否输出结构化 ImageObservation 且不默认进入长期记忆 | 通过 | `image_service.py` 成功分支新增 `observation`，默认 `memory_eligibility.eligible=false`，未新增 memory store 调用 | 增加中文截图、实物图、低置信度和异常 confidence 回归 |

## 技术可行性审计

| 检查项 | 审计问题 | 结论 | 证据/说明 | 补救动作 |
| --- | --- | --- | --- | --- |
| 现有代码定位 | 相关模块、入口、调用链是否已定位 | 通过 | `handleStderr`、`readLegacyBackendDatabasePath`、`healthCheck`、`apiRequest`、multipart bridge 与 `connectSseForWebContents` 已定位 | 限定 Task 3.1 改动 |
| 方案可落地 | 技术方案是否能在当前仓库结构内实现 | 通过 | JSON 使用 Buffer 合并后统一 `utf8` 解码；SSE 使用 `StringDecoder` 保留半个多字节字符 | 执行最小改动 |
| 测试可构造 | 单测、集成测试、E2E 或人工验证是否可执行 | 通过 | Electron 使用 Node 内置 `node:test`，可新增合成分块测试，不依赖真实后端 | 先 RED 后 GREEN |
| 兼容性 | 是否保留旧接口或迁移路径，避免破坏现有行为 | 通过 | 不改 IPC channel、HTTP path、payload 结构或 SSE cursor 语义 | 只替换解码边界 |
| 失败降级 | 外部能力缺失时是否有阻塞记录或降级方案 | 通过 | Task 3.1 不需要外部能力；其余 Task 3.2-3.6 仍待单独启动审计 | 保持未授权能力禁用 |
| 附件兼容 | Task 3.2 是否保留旧同步入口与队列入口兼容 | 通过 | 旧 `/uploads` 附件仍可走 legacy markdown；带 `attachmentId` 的桌面附件跳过旧旁路，由 pipeline/desktop service 解析 | 保留 pipeline-only companion 回退测试 |
| 图片结构化 | Task 3.3 是否不改变真实模型授权边界 | 通过 | 不改 `brain.py` provider 路由，不新增真实 VLM/OCR 调用；只消费 provider 已返回的 `metadata/observation/answer` | 使用 fake provider 合成测试 |

## 资源配置审计

| 资源类型 | 需要资源 | 当前状态 | 缺口 | 处理方式 |
| --- | --- | --- | --- | --- |
| 代码文件 | Electron 主进程与现有 SSE 单测 | 已确认 | 无 | `electron/src/main.js`、`electron/tests/sse-bridge.test.js` |
| 文档资料 | Phase1/2 证据、Task 3.1 规格与清单 | 已确认 | 无 | 当前 spec/tasks/checklist 与本启动审计 |
| 测试数据 | 中文 JSON、中文 SSE、跨多字节 chunk Buffer | 已确认 | 无 | 使用合成文本，不含私人数据 |
| 运行环境 | Node 内置测试环境 | 已确认 | 无 | `npm run test:unit -- sse-bridge.test.js` 或等效命令 |
| 外部依赖 | VLM/OCR、embedding 或向量库 | 不适用 | Task 3.1-3.3 不触发真实外部依赖；Task 3.3 使用 fake provider 与现有 provider 边界 | 后续任务单独确认 |
| 附件测试 | API、desktop attachment、pipeline 回归 | 已确认 | 无 | `pytest` 合成数据与隔离临时目录 |
| 图片测试 | 中文截图、实物图、低置信度、异常 provider metadata | 已确认 | 无 | `pytest` 合成 PNG 与 fake vision provider |

## 风险点审计

| 风险编号 | 风险描述 | 等级 | 触发条件 | 缓解措施 | 是否需用户确认 |
| --- | --- | --- | --- | --- | --- |
| R-P3-01 | 真实模型调用泄露隐私或产生成本 | 高 | VLM/OCR、主动图片、embedding 真实调用 | Task 3.1-3.3 不触发；ADR-TC-005 未确认前禁止 | 否，本任务不涉及 |
| R-P3-02 | 附件旧新路径分裂 | 高 | 同一文件产生多个 id 或事实源 | 启动前定义兼容层与单一真源测试 | 否 |
| R-P3-03 | Renderer 暴露本机路径或敏感令牌 | 高 | 附件预览、日志、DOM 泄露路径 | 启动前定义安全验收 | 否 |
| R-P3-04 | 外部向量库引入不可控依赖 | 高 | 安装服务或写外部数据库 | Task 3.1 不触发；ADR-TC-007 未确认前只做能力探测 | 否，本任务不涉及 |

## 启动前四问

- [x] 计划是否覆盖全部目标：Task 3.1 目标、子任务与 C3.1-C3.2 已覆盖；Task 3.2 目标、子任务与 C3.3-C3.4 已覆盖；Task 3.3 目标、子任务与 C3.6-C3.7 已覆盖；Task 3.4-3.6 不纳入本次启动。
- [x] 技术方案是否可行：Buffer 合并 JSON 与 StringDecoder SSE 可在现有 Electron 主进程实现。
- [x] 资源是否充分：测试样本可用合成中文 Buffer，Node 测试环境已存在。
- [x] 风险是否受控：本次任务不触发外部模型、QQ、向量库、真实隐私数据或长期记忆写入。

## 问题与措施清单

| 编号 | 审计问题 | 来源检查项 | 影响范围 | 措施 | 负责人 | 状态 | 关闭证据 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| I-P3-01 | Phase 3 尚未完成启动前代码定位、资源确认和风险确认 | 技术可行性 / 资源配置 / 风险点 | Task 3.4-3.6 | Task 3.1、Task 3.2 与 Task 3.3 已单独通过；其余任务保留未开始门禁 | TRAE | partially-closed | 本文件 Task 3.1-3.3 启动审计 |

## 阻塞项

| 编号 | 阻塞项 | 影响范围 | 解除条件 | 负责人 | 状态 |
| --- | --- | --- | --- | --- | --- |
| B-P3-01 | Phase 3 高风险未确认 | Task 3.4-3.6 | 后续任务启动前完成单独风险确认或降级记录 | TRAE | open |

## 用户确认项

| 确认项 | 选项 | 用户选择 | 确认时间 | 记录位置 |
| --- | --- | --- | --- | --- |
| 真实模型调用边界 | A 模拟/本地；B 受控真实调用；C 逐次授权 | Task 3.1-3.3 不涉及真实调用，后续再确认 | 2026-07-27 | [02_第三次修正计划决策记录.md](../../../documents/第三次修正计划/02_第三次修正计划决策记录.md) |
| 外部向量库依赖 | A 缺口报告；B 本地轻量库；C 外部托管库 | Task 3.1 不涉及，后续再确认 | 2026-07-27 | [02_第三次修正计划决策记录.md](../../../documents/第三次修正计划/02_第三次修正计划决策记录.md) |

## 启动结论

- 结论：Task 3.1-Task 3.3 有条件通过
- 是否允许进入实施：是，仅限 Task 3.1-Task 3.3
- 有条件通过条件：只允许修改 Electron UTF-8 解码、同步发送附件可信边界、ImageObservation 结构化输出与对应合成测试，不触发真实模型、QQ、外部向量库、长期记忆写入或真实隐私数据
- 不通过范围：Task 3.4-3.6 仍未启动，需后续单独执行启动审计
- 下一步动作：执行 Task 3.4 VisualIntentRouter 启动审计与 TDD 实现

## 审计日志

| 时间 | 操作 | 结果 | 证据路径 |
| --- | --- | --- | --- |
| 2026-07-27 | 创建 Phase 3 未开始启动门禁 | 不通过 | 本文件 |
| 2026-07-27 | 重新审计 Task 3.1 Electron UTF-8 解码修复 | 有条件通过 | `electron/src/main.js`、`electron/tests/sse-bridge.test.js` |
| 2026-07-27 | 重新审计 Task 3.2 附件 Artifact 管线收敛 | 有条件通过 | `core/api_server.py`、`tests/test_desktop_shared_api_contract.py`、`tests/test_phase4_api.py` |
| 2026-07-27 | 重新审计 Task 3.3 ImageObservation 结构化输出 | 有条件通过 | `core/image_service.py`、`tests/test_phase10_image_workflow.py` |
