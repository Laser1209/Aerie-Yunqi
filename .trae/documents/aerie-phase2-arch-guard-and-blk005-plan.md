---
title: Aerie 二期接力开发实施计划 — 架构守护风险测试 + BLK-005 三项 E2E 收口
kind: implementation_plan
status: draft
version: 1.0
updated_at: 2026-07-22
work_package: P2-00 / 横向守护
gate: G0 (保持 Open)
baseline_source_commit: b8c9397bba935219885adb8c1c73512f66ae1694
owner: ARCH
reviewer: QA / PO
excluded_units: [Spotlight, .codex-deploy-aerie-spotlight, android-client, documents/Android]
---

# Aerie 二期接力开发实施计划

> [!important] 接力边界
> 本计划接力上一个 Agent 的 P2-00 审计工作（B01/B02/B04/B06/B07 Done，B03 Review）。**G0 保持 Open**，本轮只落测试与工具证据，不批准 ADR-P2-009~012、不进入 P2-01 功能开发、不修改任何 ADR 状态。
>
> 全程严格规避 **Spotlight**（`Spotlight/`、`.codex-deploy-aerie-spotlight`）与 **安卓**（`android-client/`、`documents/Android/`）相关文件及代码。

## 1. 摘要（Summary）

用户要求基于 `documents/二期升级` 的审计成果接力开发，核心落点是当初需求架构中规定的**风险测试功能**——架构安全性验证、潜在漏洞检测、合规性评估。结合用户三项决策：

| 决策点 | 结论 |
|---|---|
| 核心范围 | **两者都做**：① 新建架构守护风险测试；② 收口 B02-BLK-005 剩余 3 项离线 E2E |
| G0 / ADR | **保持 G0 Open**，仅落测试证据，不推进 G0、不批准候选 ADR |
| 提交策略 | **显式路径暂存**，逐文件 add，排除 Spotlight/Android/运行数据 |

当前 G0 缺口中，B02-BLK-005 离线 E2E 为 `18/21`，剩 Persona / Prompt Injection / Multimodal 三项；同时全仓**不存在任何架构守护测试**（已用 Grep 验证），而这正是 ADR-P2-001「验证与证据」及主计划 R-01 所要求、G0 尚未补齐的证据。

## 2. 当前状态分析（Current State）

### 2.1 接力基线（来自上一个 Agent 的治理文档）

| 批次 | 状态 | 关键事实 |
|---|---|---|
| P2-00-B01 | Done | 冻结源基线 `b8c9397` / tree `873f0fe`；两个 Git 发布单元边界 |
| P2-00-B02 | Done | 基线采样完成，8 项阻断登记（B02-BLK-001~008） |
| P2-00-B03 | Review | 56 顶层控制行追踪 100%；R-01~R-17 责任就位；4 项候选 ADR 待 PO |
| P2-00-B04 | Done | 关闭 BLK-002 scanner false-pass |
| P2-00-B06 | Done | 关闭 BLK-006 QQ disabled 异常 |
| P2-00-B07 | Done | 收口 BLK-005 的 repo-root 子项，E2E 17/21 → 18/21 |
| **G0** | **Open** | 多项阻断未清零，P2-01 全部 Blocked |

### 2.2 三个 Git 单元（必须隔离）

| 单元 | 路径 | 处置 |
|---|---|---|
| Aerie 主应用 | `<repo-root>` | 本轮唯一工作单元，显式路径暂存 |
| Spotlight 发布仓 | `.codex-deploy-aerie-spotlight` | 排除，禁止暂存/推送 |
| Spotlight 源码 | `Spotlight/` | 排除（当前 dirty：`README.md`、`package*.json`、`SiteHeader.tsx`） |
| Android | `android-client/`、`documents/Android/` | 排除，独立仓库 |

当前 dirty 且须排除：`data/boot_greeting_last_sent.flag`、`data/desire_state.json`、`.codex-temp/`、`electron/src/renderer/styles/dynamic-island.css`（批次外改动）。

### 2.3 三项 E2E 失败根因（已定位）

| 脚本 | 根因 | 证据 |
|---|---|---|
| `e2e_persona_baseline.py` | 第 43 行 `from core.context_builder import _PERSONA_L1, _PERSONA_L2`，两常量已被删除 → import 阶段失败 | 测试文件头注释仍引用旧契约 |
| `e2e_s3_prompt_injection_verify.py` | `ROLEPLAY_PATTERNS = []`（prompt_injection.py:123），代码注释「已内容解放」→ `roleplay_abuse` 类型永不触发，类型覆盖 9/10 | **产品合同漂移，需 PO 裁决** |
| `e2e_s4_multimodal_input_verify.py` | T5 访问 `AudioTranscriber.model`，实际类用 `self._local_model`（vosk 懒加载），无公开 `.model` 属性 → AttributeError | 接口漂移 |

### 2.4 架构守护测试缺口

Grep 确认全仓无 `guard` 类测试。ADR-P2-001 要求「静态守护生产代码中 Pipeline/Builder 定义与组合入口唯一」，主计划 R-01 要求「架构守护测试、入口唯一性测试」，当前均无实现。

## 3. 提议变更（Proposed Changes）

分为两个交付流，均只做**新增测试/工具**，不改产品实现逻辑（Prompt Injection 除外，见 3.4 的裁决点）。

### 3.1 交付流 A：架构守护风险测试（新增）

**A1. `tools/architecture_guard.py`（新增）**

静态守护脚本，纯读取、零副作用，覆盖四大边界：

1. **单一主链**：`core/` 下仅存在一个生产 `Pipeline` 与 `ContextBuilder` 类定义；禁止 `pipeline_v2.py`/`context_builder_v2.py` 等平行实现文件；`Companion` 是唯一组合根。
2. **跨库所有权**：`world_service/` 不得 import `core.database`；`core/` 业务模块不得直接写 `world.db`；禁止跨库 JOIN 关键词。
3. **World 副作用边界**：`world_service/` 不得 import `qq_client`/`send_queue`/图片 Provider/通知/系统工具。
4. **Renderer 不直连 Sidecar**：`electron/src/renderer/` 不得引用 sidecar endpoint/token/端口。

输出机器可读报告（路径、违规行、规则 ID），退出码 0=通过 / 1=违规。扫描范围**显式排除** `Spotlight/`、`android-client/`、`documents/Android/`、`.codex-deploy-aerie-spotlight/`。

**A2. `tests/test_architecture_guard.py`（新增）**

- 正向：当前代码树四大边界全部通过。
- 负向：注入临时违规文件（如伪造 `pipeline_v2.py`、world_service import qq_client）→ 守护器必须报错（Red/Green）。
- 排除项：构造 Spotlight/Android 路径样本 → 必须被忽略。

### 3.2 交付流 B：收口 BLK-005 三项 E2E

**B1. Persona 基线（`tests/e2e/e2e_persona_baseline.py`）**

将 T4 第 10/11 项从「读已删除的 `_PERSONA_L1/_PERSONA_L2` 常量」改为「读当前 Persona 投影合同」——通过 `config/persona_loader.load_persona()` 验证 9/10 基线与直球措辞在投影后的真实人格源中仍然成立。**保留旧行为断言强度，不降低守门标准**。

**B2. Multimodal T5（`tests/e2e/e2e_s4_multimodal_input_verify.py`）**

将 T5 从访问不存在的 `AudioTranscriber.model` 改为断言当前公开配置接口（构造参数 + `_local_model` 懒加载语义的公开等价物）。补一条向后兼容说明断言。

**B3. Prompt Injection `roleplay_abuse`（裁决点）**

> [!warning] 产品合同漂移，需 PO 裁决
> `ROLEPLAY_PATTERNS = []` 是有意为之（注释「已内容解放」）还是检测缺失？这是安全策略决策，**不能在测试批次里擅自决定**。
> - 若 PO 裁决「恢复检测」→ 在 `prompt_injection.py` 补充 roleplay_abuse 检测规则（此为最小产品改动，需独立 Red/Green）。
> - 若 PO 裁决「保持解放」→ 将 E2E 类型覆盖期望从 10 类调整为 9 类并显式标注 `roleplay_abuse = intentionally_undetected`，同步登记到风险册。

默认按「**先询问 PO**」处理：本轮先在计划中标记，实施时优先恢复检测（符合主计划 Safety 层「不受限制不代表绕过 Safety」原则）。

### 3.3 复跑与证据

- 复跑 21 项离线 E2E allowlist → 目标 **21/21**。
- Python 全量 + Electron Node 全量回归。
- 更新 `04_二期测试与证据索引.md`（追加本轮守护测试与 E2E 收口证据，保持 B02-BLK-005 状态按实际结论更新）。
- 同步 `01_二期需求追踪矩阵.md`、`03_二期风险登记册.md` 中 R-01 的守护证据指针。

### 3.4 提交边界（严格执行）

```powershell
# 仅显式暂存本轮 owned paths（示例，以实际交付为准）
git add -- tools/architecture_guard.py `
          tests/test_architecture_guard.py `
          tests/e2e/e2e_persona_baseline.py `
          tests/e2e/e2e_s4_multimodal_input_verify.py `
          documents/二期升级/04_二期测试与证据索引.md
# 明确不 add：Spotlight/ .codex-deploy-aerie-spotlight android-client documents/Android data/ .codex-temp/ .env
```

提交前 `git diff --cached --name-only` 校验仅含 owned paths。

## 4. 假设与决策（Assumptions & Decisions）

| # | 假设/决策 | 依据 |
|---|---|---|
| D1 | G0 保持 Open，本轮不产生任何 ADR 状态变更 | 用户决策「保持 G0 Open，仅落测试证据」 |
| D2 | 架构守护为纯静态只读扫描，零运行时副作用 | 符合 Contract-09 Flag-off 零副作用精神；守护器本身不进产品路径 |
| D3 | roleplay_abuse 默认先恢复检测，但实施时先向 PO 确认 | 主计划 Safety 层原则；避免在测试批次擅自改安全策略 |
| D4 | Persona 守门强度不降低 | 测试文件头 R8.1「零回退」原则 |
| D5 | 不触碰 Spotlight/Android 任何文件 | 用户硬性要求 + B01/R-13 纪律 |
| D6 | 不改 `ROLEPLAY_PATTERNS` 之外的检测逻辑，不动 `chat_log`、旧 API、Persona YAML 写路径 | 二期兼容原则「先扩展后切换暂不删除」 |

## 5. 验证步骤（Verification）

1. `python tools/architecture_guard.py` → exit 0，四大边界通过。
2. `python -m pytest tests/test_architecture_guard.py -q` → 全绿（含负向注入用例）。
3. 隔离 cwd 复跑 21 项离线 E2E → **21/21**（BLK-005 收口）。
4. `python -m pytest tests -q` → 全量 Python 回归通过（当前基线 609 passed，不得下降）。
5. `node --test electron/tests/*.test.js` → 50 passed 不下降。
6. `git diff --cached --name-only` → 仅含 owned paths，Spotlight/Android/运行数据零混入。
7. 治理文档（04/01/03）状态与实际证据一致。

## 6. 非目标（Non-Goals）

- 不关闭 G0、不进入 P2-01、不批准 ADR-P2-009~012。
- 不处理 B02-BLK-001/003/004/007/008（历史治理、打包、依赖，属后续批次）。
- 不执行历史改写、`--force-with-lease`、真实 Provider/QQ 外呼。
- 不修改 Spotlight 源码、不触发网站部署、不动 Android 仓库。
- 不重构 Pipeline/ContextBuilder，不新建任何 v2 平行主链。
