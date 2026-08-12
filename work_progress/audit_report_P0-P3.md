# 上下文记忆系统改造 P0-P3 交付审计报告（艾莲会签）

- 审计人：艾莲（独立审计）
- 审计日期：2026-08-12
- 审计对象：`work_progress/05_上下文记忆系统改造方案.md` 附录 B.3 门户节点与过关点（P0/P1/P2/P3）
- 约束遵守：严格只读审计，未修改 `core/`、`tests/`、`memory/` 下任何代码；仅新增本报告

---

## 1. 审计范围与证据采集方式

| 维度 | 说明 |
|---|---|
| 文档依据 | 方案 §4 改动文件清单（16 项）、§5 验收标准（7 条）、附录 A（v2 演进）、附录 B.3 门户节点/过关点、B.6~B.9 实施记录 |
| 提交核实 | `git log --oneline` 比对实施记录全部 14 个功能提交 + 3 个证据提交；`git show <hash> --stat --format=%h/%s/%ci/%b` 逐条核对改动文件与提交说明 |
| 代码核实 | 直接读取 `core/conversation_continuity.py`、`core/pipeline.py`、`core/migrations/__init__.py`、`core/database.py`、`core/memory_validation.py`、`core/api_server.py`、`core/evolution_manager.py`、`core/_hist_utils.py`、`core/cognition.py`、`memory/layers/*`、`core/companion.py`、`config/settings.yaml`、`tools/*` 验收脚本 |
| 测试核实 | 定向运行 pytest（`.venv\Scripts\python.exe -m pytest <file> -q`）：P1-P3 新测试 6 个文件、continuity 4 个文件、knowledge 鉴权 + layered adapter；另独立运行全量回归（1259 用例）比对 B.9 声称 |
| 磁盘证据 | 只读查询 `data/aerie.db`（SQLite URI mode=ro）migration_ledger 与表/索引；在 DB 副本上实跑 009/010 迁移验证幂等 |
| 离线证据 | 读取 `work_progress/cross_channel_continuity_acceptance_report.json`、`work_progress/context_assembler_perf_report.json`、`work_progress/security_review_P0-P3.md` |

---

## 2. 实施记录提交哈希真实性核实（B.6~B.9）

> 全部 17 个声称提交均存在于 `git log`，且 `--stat` 改动文件与实施记录描述一致。

| 阶段 | 声称提交 | 核实结果（改动文件与说明匹配） |
|---|---|---|
| P0-安全 #12 | `d9ad40b` | ✅ `core/api_server.py`（+8）+ `tests/test_api.py`（+30）；knowledge 写端点补 `X-Aerie-Main-Token` 鉴权，GET 开放 |
| P0-安全 #13 | `3782c31` | ✅ `core/evolution_manager.py`（+3/-1）；store 补传 channel |
| P0 Step1 | `0fcb755` | ✅ 新增 `core/_hist_utils.py`（+25），`context_builder.py`/`conversation_continuity.py` 去重引用 |
| P0 Step2 | `24afd06` | ✅ `companion.py`（recent_turn_limit/max_turn_chars）+ `conversation_continuity.py`（+79 轮次化/弹性/日志）+ 3 个测试文件 |
| P0 Step3 | `78a79b4` | ✅ `_hist_utils.py` 通道标记 + `conversation_continuity.py` 通道段 + 测试 |
| P0 Step4 | `79a4a7e` | ✅ `long_permanent.py`/`sync_adapter.py`/`pipeline.py`/`companion.py` 来源标注 + identity seed=system + 测试 |
| P0 Step5 | `db6b194` | ✅ 仅测试（摘要兜底与轮次窗口共存） |
| P1-H2 | `9b36ad0` | ✅ `pipeline.py`（+55 清洗/包裹/降权）+ 新增 `test_p1_h2_memory_injection_defense.py` |
| P1 分桶 | `cb247ec` | ✅ `migrations/__init__.py`（+49，009_summary_buckets）+ `conversation_continuity.py`（+186）+ 新增 `test_p1_summary_buckets.py`（184 行）+ 4 个既有测试适配 |
| P2-1 思维链 | `bdc00c9` | ✅ `settings.yaml`（flag）+ `cognition.py`（+76 recent_react_summary）+ 注入 + 新增测试（175 行） |
| P2-2 校验门 | `1a31727` | ✅ 新增 `core/memory_validation.py`（214 行）+ `tools/memory_validation_poc.py` + `api_server.py` 接线 + 新增测试（114 行） |
| P3-1~3 | `e217bd2` | ✅ `migrations/__init__.py`（010_persona_timeline）+ `conversation_continuity.py`（+142 视图B/多端存在）+ `pipeline.py`（+77）+ 新增测试（200 行） |
| P3-4/5 | `50a72a2` | ✅ `pipeline.py`（+167 三触发器/event 记忆召回）+ 新增 `test_p3_recall_triggers.py`（162 行） |
| P3 红线测试 | `a0f1e10` | ✅ 新增视图 B 预算/隔离红线 2 用例（+68） |
| 证据-跨通道验收 | `1344291` | ✅ `tools/cross_channel_continuity_acceptance.py`（245 行）+ JSON 报告（99 行） |
| 证据-性能微基准 | `57e9a3d` | ✅ `tools/context_assembler_perf_check.py`（195 行）+ JSON 报告（30 行） |
| 证据-安全扫描 | `da88fd1` | ✅ `work_progress/security_review_P0-P3.md`（无可利用项结论） |

辅助文档提交：`cac3cdc`/`2fa32c1`/`8093f1f`/`acf5a61`/`a494216`/`9003a37`/`406343e` 均存在且为方案文档状态更新。`pre-p0` 基线 tag 已打（`git tag -l` 确认）。

---

## 3. §4 改动文件清单（16 项）代码实现核实

| # | 清单项 | 代码核实 | 状态 |
|---|---|---|---|
| 1 | `conversation_continuity.py` ContextAssembler 轮次化/分桶/通道段/交接棒 | `recent_turn_limit=8`（L488）、`max_turn_chars=6_000`（L489）、`max_summary_buckets=3`（L491）；L649-685 按 `turn_id` groupby 保留最近 8 轮、超 `max_turn_chars` 截断；L611 【当前通道】段；L613-618 【多端存在】段（flag 控制）；L576-581 视图 B `[跨端回忆]`；L769-770 `_format_timeline_events` 每行 80 字符、最多 3 条；L713-732 监控日志含 `l0_turns_requested/l0_turns_included/l0_truncated/summary_bucket_count/timeline_events` | ✅ |
| 2 | `conversation_repository.py` 返回格式不动 + 跨通道查询 | 轮次分组在消费端 groupby 完成（未改 history_page 返回格式）；`find_recent_cross_channel_summary` 已由 P3-5 `PersonaTimelineRepository.recent_events`（L372-393，支持 since/exclude_channel）取代 | ✅ |
| 3 | `companion.py` 参数 | L490-496 `ContextAssembler(recent_turn_limit=8, max_turn_chars=6_000, max_summary_buckets=3)` | ✅ |
| 4 | `context_builder.py` | 已改为引用 `_hist_utils.hist_label`（0fcb755 去重）；FULL=8 打底保留；P1 收敛评估结论：保留（兜底） | ✅ |
| 5 | `layered_memory.py` channel 透传 | `sync_adapter` 链路带 channel 写入 metadata | ✅ |
| 6 | `sync_adapter.py` store/retrieve | `store()` 增 channel 参数；`retrieve()` 返回带 channel 字段 | ✅ |
| 7 | `long_permanent.py` ChromaDB metadata | L166-L171 类 store 路径与 update 路径补 channel；检索 `.get("channel", "unknown")` 兜底 | ✅ |
| 8 | `pipeline.py` | `_retrieve_memory_snippets`（L1552-1599）：无来源降权排序 + `_sanitize_memory_text` 清洗 + `<memory source>` 包裹 + `[来源:XX]` 前缀；store 调用处传 channel；摘要分桶调度 | ✅ |
| 9 | `settings.yaml` flags | `thinking_trace_injection_v1: false` / `memory_write_validation_v1: false` / `multi_channel_identity_v1: false` 均默认关闭 | ✅ |
| 10 | migrations 009/010 统一管理 | `009_summary_buckets`（建表+idx_summary_buckets_lookup+CHECK 约束）与 `010_persona_timeline`（DDL 与附录 A.3.1 逐字段一致）均注册于 `core/migrations/__init__.py`，`core/database.py` L377-378 经 `MigrationRunner` 按序执行，旧表只读兼容 | ✅ |
| 11 | 8 类测试用例 | 对应测试均存在：轮次窗口（`test_turn_grouping_keeps_recent_turns_complete`/`test_turn_window_elasticity_truncates_oldest`）、token 弹性、通道感知、跨通道隔离、记忆来源、ChromaDB 同步、H2 注入防御（`test_p1_h2_*`） | ✅ |
| 12 | `api_server.py` knowledge 鉴权 | L5034/L5067/L5082：POST/PUT/DELETE 均 `_main_process_request_authorized` 未认证返 403；GET（list/get）保持开放（L4999/L5013）；验收测试 `test_knowledge_writes_require_auth` 存在且通过 | ✅ |
| 13 | `evolution_manager.py` 签名兼容 | L362/L519 store 调用均带 `"channel": "system"` | ✅ |
| 14 | `core/_hist_utils.py` 去重 | `hist_label(row, current_channel=...)` + `channel_short()` 公共函数，`context_builder.py`/`conversation_continuity.py` 统一引用 | ✅ |
| 15 | H2 记忆注入防御 | `_sanitize_memory_text` + `<memory>` 包裹 + 无来源降权（见 #8） | ✅ |
| 16 | identity seed channel="system" | `companion.py` IdentityMemory seed store 带 `channel="system"`（79a4a7e） | ✅ |

---

## 4. 测试运行核实

| 测试集 | 结果 | 证据 |
|---|---|---|
| `test_p1_summary_buckets.py` + `test_p2_thinking_trace_injection.py` + `test_p2_memory_validation.py` + `test_p3_multi_channel_timeline.py` + `test_p3_recall_triggers.py` + `test_p1_h2_memory_injection_defense.py` | **39 passed** (2.07s) | 实跑 |
| `test_conversation_continuity.py` + `test_desktop_chat_continuity.py` + `test_desktop_chat_continuity_acceptance.py` + `test_continuity_pipeline_integration.py` | **20 passed** (2.17s) | 实跑 |
| `test_api.py::test_knowledge_writes_require_auth` + `test_p1_d5_3_layered_adapter.py` | **6 passed** (4.40s) | 实跑 |
| 全量回归 `pytest tests -q --tb=no` | **1259 passed / 26 failed** (82.4s) | 实跑；与 B.9 声称 1259 一致，失败数 27→26（与"修复 1 个 continuity 集成测试"叙述吻合） |

26 个失败逐条核对，全部为既有环境性失败，无一属于 P0-P3 改动范围：世界模拟时间/相位断言（`test_p1_c1_world_snapshot`、`test_phase12_world_domain`、`test_world_runtime_lifecycle`、`test_p1_c3_*`）、QQ 表情/贴纸（`test_qq_sticker`、`test_qq_media`）、phase4 集成/流水线（`test_phase4_integration`、`test_phase4_pipeline`、`test_pipeline`）、schema 预期（`test_phase2_identity`：no such column: source_message_id）、attachment-worker 环境（`test_desktop_attachment_offline_acceptance`）、world dashboard（`test_phase15_world_dashboard_*`、`test_world_reality`）。

---

## 5. 离线证据报告核实

| 报告 | 声称 | 实测 | 状态 |
|---|---|---|---|
| `work_progress/cross_channel_continuity_acceptance_report.json` | 连续率 100% | `treated_continuity_rate: 1.0`（5 用例，control 0.4，viewB_injected 1.0，elapsed 60.1s），报告由 `tools/cross_channel_continuity_acceptance.py` 落盘 | ✅（样本量见 §6-2） |
| `work_progress/context_assembler_perf_report.json` | 视图 B 增量 ≈0 | `overhead_pct: -1.03%`、`abs_overhead_ms: -0.009`、`view_b_added_chars: 213`（阈值 ≤500）、50 runs、`pass: true` | ✅ |
| `work_progress/security_review_P0-P3.md` | 无可利用项 | TRAE-security-review 三遍法，覆盖 pre-p0→1344291（48 文件/2663 插入），SQL 注入/鉴权/代码执行/密钥/Prompt 注入/敏感数据/日志泄漏 7 个安全面全绿 | ✅ |

---

## 6. 发现的问题与风险

### P2 级（建议整改，不阻塞交付）

**F1（证据链缺口）B.7 声称"migration 实库执行成功验证 —— 磁盘 DB 实跑：009 建表/索引/幂等均通过"在现盘 DB 不可复查。**
- 现状：`data/aerie.db`（gitignored，不随代码版本化）的 `migration_ledger` 无 `009_summary_buckets`/`010_persona_timeline` 条目，库中亦无对应表/索引（现盘最后账本条目为 `010_session_tracking`——该版本号在当前代码中已不存在，说明现盘 DB 从未以 P1/P3 之后代码启动过，与"运行时验收待会签"状态自洽）。
- 审计补证：在 `data/aerie.db` 副本上实跑 `MigrationRunner`，009/010 均成功建表/建索引并写入账本 `completed`，幂等机制正常（产品路径 `database.py` L344 已设 `row_factory=sqlite3.Row`，checksum 校验可正常走通）。
- 结论：迁移实现本身正确；B.7"磁盘 DB 实跑"的描述与现盘证据不符，建议修正表述为"副本 DB 实跑验证"或在 P0-P3 交付后的首次真实启动时复核账本出现 009/010。

**F2（验收样本量）§5 验收 2 规格"构造 ≥ 10 组跨通道对话测试用例"，离线代理验收实际仅 5 组（`SCENARIOS` 5 个场景，`case_count: 5`）。**
- **状态：已整改（2026-08-13，`28a758e` 后复跑）**——`SCENARIOS` 扩展至 10 组多元话题主体（饮食/出行/宠物/工作/健康/家庭/爱好/计划/购物/阅读），`case_count: 10` 达规格 ≥10；实验组（视图 B 开启）连续率 10/10（100%）、对照组 4/10（40%）、视图 B 注入率 10/10。样本量达标，结论强度由"5/5"升级为"10/10"。
- 剩余边界：仍属"离线代理"（本地 DB + LLM 模拟跨端），非 QQ/桌面真实链路；真实链路复测仍待用户验收（B.9 待办），本整改不替代该待办。

### P3 级（观察项，无需整改）

**F3（版本号语义）**：新迁移沿用 `009_`/`010_` 数字前缀，与既有 `009_batch_request_support`、`010_session_tracking`（现盘账本）数字前缀重复，"schema_version 顺序执行"约定被削弱。实际执行顺序由 `database.py` 注册顺序决定（功能无冲突），但版本号不再是唯一有序标识。建议后续迁移采用全局唯一递增版本号（如 `011_...` 起）。
- **状态：已解决（2026-08-13）**——P4b 迁移 `011_admin_management` （`migrations/__init__.py` L640）已采用全局唯一递增版本号，审计建议落实。

**F4（注释与实现不一致）**：`pipeline._resolve_recall_events` docstring 写"显式回忆 > 跨端切换检测 > 长间隔回归"，实际代码顺序为"显式回忆 > 长间隔回归（≥2h）> 跨端切换（≥30min）"（L2527/L2549/L2562）。docstring 与实现不符，行为以代码为准（与 B.9 记录顺序一致），建议修正注释。
- **状态：已修复（2026-08-13）**——docstring 优先级描述与三处触发器编号注释已同步为实际执行顺序（显式回忆>长间隔≥2h>跨端切换≥30min）；`tests/test_p3_recall_triggers.py` 7 例全绿，行为不变。

---

## 7. 需艾莲会签的过关点逐项结论

| 过关点 | 依据证据 | 结论 |
|---|---|---|
| **P0 过关点：审计（艾莲）交付评审通过** | §5-1 轮次窗口（`test_turn_grouping_keeps_recent_turns_complete`/`test_turn_window_elasticity_truncates_oldest` 实跑通过）；§5-3 通道感知（`test_channel_awareness_injected_into_system_prompt` 通过 + `_hist_utils` 通道标记）；§5-5 记忆来源（`test_adapter_store_channel_then_retrieve_tags_source` 通过，identity seed=system 已实现）；§5-7 安全（`test_knowledge_writes_require_auth` 实跑通过 + evolution_manager 签名兼容）；§6.1 监控日志（`context_assemble` 结构化日志含 9 项指标在 assemble() 落地） | **通过** |
| **P0 过关点：Agent 安全扫描无新增高危** | `work_progress/security_review_P0-P3.md`（提交 `da88fd1`）：TRAE-security-review 三遍法，"No exploitable issues found"，7 个安全面全绿；扫描范围覆盖 pre-p0→1344291 全部 P0-P3 交付 | **通过** |
| **P1 过关点：Agent 回归复核通过** | B.7 记载"伊塔执行 1228 passed/27 failed……待 Agent 正式会签"；艾莲本次独立全量回归 1259 passed/26 failed，与声称一致且无新增回归；**Agent 补签（2026-08-13）**：独立 Agent 全量回归 1406 passed/27 failed 零新增，正式记录 `work_progress/agent_regression_recheck_P0-P4.md`（hash `822a826e`） | **通过** |
| **P2 门户节点：审计确认 P2 项 ROI 可行（写入校验门 PoC 范围界定）** | `1a31727` 提交 `core/memory_validation.py` + `tools/memory_validation_poc.py`；B.8 实测：11 合成用例判定一致率 100%（误判 0）、平均时延 3436.7ms/次、平均 179.9 tokens/次、估算成本约 0.054 元/千次；结论建议异步 fire-and-forget 或仅 importance≥7 同步校验。PoC 范围界定（importance≥7 + knowledge_add 接线 + flag 默认关闭 + fail-open）合理，成本与误判率双达标，`validate_fact`/`MemoryFactValidator` 实现与 PoC 描述一致 | **通过** |
| **P3 门户节点：persona_timeline 表设计评审（艾莲）通过** | `010_persona_timeline` DDL（`migrations/__init__.py` L563-578）与附录 A.3.1 规格逐字段一致：`id/actor_id/user_id/channel/turn_id/event_summary/occurred_at` + `UNIQUE(actor_id, user_id, turn_id)` 幂等键 + `idx_timeline_lookup (actor_id, user_id, occurred_at DESC)`；写入时机（摘要刷新同步写事件）与 A.3.1 一致；副本 DB 实跑建表/索引/账本成功 | **通过** |
| **P3 过关点：多端自我叙事实测（用户验收）** | B.9 明确"需 QQ/桌面真实链路，开启 `multi_channel_identity_v1` 后实测"，当前未执行 | **待用户**（本审计仅记录状态；离线代理证据见 §5，视图 B 注入率 10/10） |
| **P3 过关点：视图 B token 预算合规 + 写入隔离红线** | `test_view_b_budget_within_500_chars`/`test_write_isolation_red_line_l0_never_injects_other_channels`（`a0f1e10`）实跑通过；性能报告视图 B 新增 213 字符 ≤ 500、增量 -1.03%；隔离红线实现：L0/L1 按 conversation_id（含 channel）取历史，视图 B 仅摘要级只读注入 | **通过** |
| **艾莲交付评审（会签 P0-P3 交付）** | 见 §2-§6 全部证据 | **通过**（附 P2 级发现 F1/F2 与 P3 级观察 F3/F4，均不阻塞） |

---

## 8. 会签结论

> **P0-P3 交付评审：通过（有条件）**

- **通过**：P0 交付评审 ✅、Agent 安全扫描无新增高危 ✅、P2 门户 ROI 可行 ✅、P3 门户 persona_timeline 表设计 ✅、视图 B 预算/隔离红线 ✅、实施记录全部提交哈希真实且内容匹配 ✅、§4 十六项改动全部落实 ✅、定向测试与全量回归（1259 passed/26 failed，失败均为既有环境性）✅、三份离线证据报告真实有效 ✅。
- **条件**：
  1. P1 过关点"Agent 回归复核"——**已补签闭环（2026-08-13）**：独立 Agent（general_purpose_task）全量回归实测 **1406 passed / 27 failed**（总 1433，89.26s），与 P4 基线 1405/27 对比零新增失败；正式复核记录 `work_progress/agent_regression_recheck_P0-P4.md`（含基线三要素 hash+命令+日期），git hash-object 校验 `822a826e...` 落盘确认。
  2. F1：B.7"磁盘 DB 实跑"证据表述需修正（现盘 DB 账本无 009/010，副本实跑已验证迁移正确）；P0-P3 交付后的首次真实启动应复核账本出现 009_summary_buckets/010_persona_timeline。
  3. F2：§5 验收 2 离线代理样本量已整改为 10/10（100%，对照组 4/10），规格 ≥10 达成；真实 QQ/桌面链路复测随用户验收（B.9 待办）一并关闭。
- **遗留（不属本交付）**：26 个既有环境性测试失败（F3 版本号语义、F4 注释不一致已分别解决/修复，2026-08-13）。
