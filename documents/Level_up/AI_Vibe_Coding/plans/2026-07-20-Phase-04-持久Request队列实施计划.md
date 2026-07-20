# Phase 04 持久 Request 队列实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development before implementation and superpowers:executing-plans to execute this plan task-by-task. Every implementation batch uses checkbox (`- [ ]`) tracking, must personally observe the target Red, and must not write implementation before that Red is recorded.

**Goal:** 在不重写现有 Pipeline、不破坏 Flag 关闭旧同步合同的前提下，建立可持久、可取消、可重试、可恢复的聊天 Request 队列，并完成同 Conversation 串行、跨 Conversation 最多四路、纯附件和 Renderer 请求级状态管理。

**Architecture:** 由 `Companion` 作为唯一组合根创建并注入 `ChatRequestRepository`、`ChatRequestService` 与 `ChatRequestWorker`；API 只在依赖门禁完整且 `chat_request_queue_v1` 开启时提交持久 Request，Worker 用短事务原子 claim 后在事务外调用现有 FULL/BASIC Pipeline。规范 Conversation/Turn/Message 继续由 `ConversationRepository` 维护，Request 状态是恢复真源，`EventEnvelope` 复用于 stderr/IPC/SSE，Renderer 将三条输入通道汇入同一幂等 ingest。

**Tech Stack:** Python 3、FastAPI、asyncio、SQLite/WAL、pytest/pytest-asyncio、Electron 28、原生 JavaScript、Node `node:test` + `vm`、Obsidian Markdown、PowerShell。

---

## 0. 执行纪律与不可越界项

- [ ] 每个执行批次开始前重新阅读 `E:\Agent_reply\documents\Level_up\实施计划.md`、`E:\Agent_reply\documents\Level_up\AI_Vibe_Coding\phases\Phase 04.md`、`E:\Agent_reply\documents\Level_up\AI_Vibe_Coding\tasks\Task 04-baseline.md`、`E:\Agent_reply\documents\Level_up\AI_Vibe_Coding\06_AI_Vibe_Coding批次规约.md`；不得只依赖压缩摘要或上一批记忆。
- [ ] Phase 04 开始前执行 Phase 00–03 门禁复核；进入 Phase 05 前再次复查 Phase 00–04 全部门禁。任一前序门禁失败即停止，不以“与本批无关”为由继续。
- [ ] 每批严格执行：写目标失败测试 → 亲自运行并观察目标能力缺失的 Red → 写最小 Green → 定向回归 → 关联/完整回归 → 保存脱敏 Evidence → 更新 Phase/Task/验收/迁移核对/回滚文档。
- [ ] 禁止在目标 Red 出现前写生产实现；导入错误、语法错误、Fixture 错误、测试自身错误不算目标 Red。
- [ ] 本计划不包含任何版本控制操作；每批只更新文档状态与 Evidence。
- [ ] 不直接读写生产库 `data/aerie.db`；迁移与恢复演练只能使用 SQLite Backup API 生成的一致性副本和独立 rehearsal 副本。
- [ ] 不修改 `electron/dist-*`、`electron/_tmp_asar_*`、历史备份、构建产物、无关日志或 Phase 07 图片资产系统。
- [ ] 日志、Fixture、截图和 Evidence 不得包含消息正文、附件 Markdown、账号、凭据、密钥、绝对用户文件路径或内部堆栈。

### 每批压缩后快速自检

- [ ] 是否重新阅读了总实施计划和 Phase 04 权威文件？
- [ ] 当前工作是否仍严格属于 Phase 04，而未扩展到 Phase 05/06/07？
- [ ] 是否亲自观察了目标缺失导致的 Red，而不是先写实现？
- [ ] 是否保护了 `chat_request_queue_v1=false` 的旧同步 200 路径？
- [ ] 是否未写生产库、构建产物或无关文件？
- [ ] 是否已更新 Phase、Task、全局验收、迁移核对和回滚文档？
- [ ] 是否在推进下一阶段前复核了全部前序门禁？

## 1. 文件结构与职责锁定

### Create

- `core/chat_request_repository.py`：Request/Turn 持久状态机、提交事务、claim、lease、heartbeat、恢复、所有权和 retry 数据操作；不得调用模型或发事件。
- `core/chat_request_service.py`：受信任本地身份、附件验证、纯附件 effective content、脱敏 DTO、404/409 合同和 API 用例编排。
- `core/chat_request_worker.py`：四槽调度、真实 `asyncio.Task`、heartbeat、用户取消、停止、恢复与 Pipeline 调用。
- `tests/test_phase4_migration.py`：006 字段、索引、checksum、dry-run、幂等、部分应用恢复、旧 completed NULL、quick_check。
- `tests/test_phase4_chat_request_repository.py`：提交原子性、claim、Conversation 互斥、状态守恒、lease、恢复、retry。
- `tests/test_phase4_chat_request_service.py`：受信任身份、纯附件、附件 ready、所有权、404/409、脱敏。
- `tests/test_phase4_chat_request_worker.py`：四槽、第五等待、同会话串行、跨会话并行、heartbeat、取消、stop 与恢复。
- `tests/test_phase4_pipeline.py`：FULL/BASIC 取消边界、effective content、可见 content、规范镜像 ID、事件信封、QQ 副作用。
- `tests/test_phase4_api.py`：202/200 双合同、status/cancel/retry、400/404/409/503、单实例注入。
- `tests/test_phase4_integration.py`：端到端提交、完成、取消、恢复、事件失败与状态查询。
- `electron/tests/chat-request-queue.test.js`：Node `node:test` + `vm` 的连续三次 POST、状态 Map、去重排序、恢复、cancel/retry。

### Modify

- `core/migrations/__init__.py`：新增独立 `006_chat_request_queue`，保留 004/005 定义与 checksum 不变。
- `core/database.py`：在 `migration_framework_v1=true` 时注册 006；006 不受 queue 运行 Flag 控制。
- `tests/conftest.py`：增加隔离 Phase 04 数据库、可注入 UTC 时钟、ready 附件和异步 Pipeline doubles。
- `core/conversation_repository.py`：公开 deterministic conversation resolution/ensure；完成预分配 Request/Turn；历史仅 completed。
- `communication/message.py`：仅增加 Request 上下文和 internal effective content 所需字段，保持用户可见 `content` 不变。
- `core/pipeline.py`：FULL/BASIC 接收 RequestContext/CancellationToken，在明确副作用边界检查；镜像沿用已有 ID。
- `core/companion.py`：唯一实例创建和依赖门禁；Worker 在 QQ 等待前启动，stop 时有序停止。
- `core/api_server.py`：Flag 双路径、status/cancel/retry API、错误合同、纯附件与未就绪处理；不得创建第二 Repository。
- `config/settings.yaml`：只保留/确认 `chat_request_queue_v1: false` 默认关闭，不新增绕过依赖的隐式开关。
- `electron/src/renderer/js/chat.js`：移除 `_loading`，请求状态 Map、统一 ingest、页面恢复、cancel/retry。
- `electron/src/preload.js`：如测试证明监听无法清理，则让 `onMessage` 返回 unsubscribe；不扩大 IPC 能力。
- `electron/src/renderer/js/chat-uploader.js`：仅当纯附件 ready 合同 Red 证明必要时，最小改为使用既有 `window.aerie.api.upload` 并同步 ready 状态；不得扩展 Phase 07 资产管理。
- `documents/Level_up/AI_Vibe_Coding/phases/Phase 04.md`：每批记录 Red/Green/回归/Evidence 和最终门禁。
- `documents/Level_up/AI_Vibe_Coding/tasks/Task 04-baseline.md`：逐批 checkbox 与 `rollback_ready`。
- `documents/Level_up/AI_Vibe_Coding/90_全局验收清单.md`：关闭 A-04 对应能力。
- `documents/Level_up/AI_Vibe_Coding/91_数据迁移核对.md`：006 与副本迁移守恒。
- `documents/Level_up/AI_Vibe_Coding/92_回滚演练.md`：Flag 关闭、停止消费、恢复副本与数据损失。

## 2. 固定接口、数据类与状态合同

后续任务使用以下名称，不得在不同批次自行改名。

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Protocol

UtcClock = Callable[[], datetime]

@dataclass(frozen=True)
class RequestIdentity:
    actor_id: str
    channel: str                 # desktop | qq
    channel_account_id: str
    user_id: int                 # legacy compatibility

@dataclass(frozen=True)
class RequestContext:
    request_id: str
    conversation_id: str
    turn_id: str
    identity: RequestIdentity
    input_content: str
    effective_content: str
    attachments: list[dict[str, Any]] = field(default_factory=list)
    reply_to_id: int = 0

class CancellationToken(Protocol):
    def is_cancelled(self) -> bool: ...
    def raise_if_cancelled(self) -> None: ...

@dataclass(frozen=True)
class SubmittedRequest:
    request_id: str
    conversation_id: str
    turn_id: str
    status: str = "queued"

@dataclass(frozen=True)
class ClaimedRequest:
    context: RequestContext
    lease_owner: str
    lease_expires_at: str

@dataclass(frozen=True)
class RequestStatusView:
    request_id: str
    conversation_id: str
    turn_id: str
    status: str
    error_code: str | None
    created_at: str
    started_at: str | None
    completed_at: str | None
    cancelled_at: str | None
    can_cancel: bool
    can_retry: bool
    user_message_id: int | None
    assistant_message_ids: tuple[int, ...]
```

```python
class ChatRequestRepository:
    def submit(self, *, context: RequestContext, retry_of_request_id: str | None = None) -> SubmittedRequest: ...
    def get_owned(self, *, request_id: str, actor_id: str) -> dict | None: ...
    def claim_next(self, *, lease_owner: str, lease_seconds: int) -> ClaimedRequest | None: ...
    def heartbeat(self, *, request_id: str, lease_owner: str, lease_seconds: int) -> bool: ...
    def request_cancel(self, *, request_id: str, actor_id: str) -> str | None: ...
    def mark_completed(self, *, request_id: str, lease_owner: str, result: dict) -> None: ...
    def mark_failed(self, *, request_id: str, lease_owner: str | None, error_code: str) -> None: ...
    def mark_cancelled(self, *, request_id: str, lease_owner: str | None) -> None: ...
    def recover_interrupted(self) -> int: ...
    def create_retry(self, *, source_request_id: str, actor_id: str, request_id: str, turn_id: str) -> dict: ...
```

```python
class ChatRequestService:
    def submit(self, *, text: str, attachments: list[dict], reply_to_id: int, user_id: int | None) -> RequestStatusView: ...
    def get(self, *, request_id: str, user_id: int | None) -> RequestStatusView: ...
    async def cancel(self, *, request_id: str, user_id: int | None) -> RequestStatusView: ...
    def retry(self, *, request_id: str, user_id: int | None) -> RequestStatusView: ...

class ChatRequestWorker:
    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def cancel_running(self, request_id: str) -> bool: ...
```

受信任 desktop identity 固定由后端已有 IdentityRepository 解析，不硬编码或猜测 Actor：

```python
identity = identity_repository.resolve("desktop", "local")
RequestIdentity(
    actor_id=identity.actor_id,
    channel=identity.channel,
    channel_account_id=identity.channel_account_id,
    user_id=int(user_id if user_id is not None else get_master_qq()),
)
```

同一 `(desktop, local)` 绑定必须稳定复用 Actor；Renderer 请求体不得接受或透传 `actor_id`、`conversation_id`、`turn_id`。后端可接受 legacy `user_id` 以保持当前桌面寻址，但 actor/channel/conversation 必须由受信任本地规则解析。

状态转换固定为：

```text
queued -> running | cancelled
running -> completed | cancelling | failed
cancelling -> cancelled | failed
completed -> terminal
failed -> terminal; retry creates a new queued Request and Turn
cancelled -> terminal; retry creates a new queued Request and Turn
```

错误合同固定为：

- 非所有者和不存在的 Request 对 GET/cancel/retry 统一返回 `404`，不得泄露存在性。
- 非法状态操作返回 `409`；例如对 queued/running 执行 retry。
- 对 `completed`、`failed`、`cancelled` 再次 cancel 为幂等 `200`，返回当前真实终态，不改写为 cancelled。
- retry 只允许 `failed`/`cancelled`，成功返回 `202` 和新的 `request_id`/`turn_id`，新行 `retry_of_request_id` 指向原请求。
- 队列 Flag 开启但依赖不完整或 Worker/Service 未就绪返回 `503`，不得静默退回不完整队列或旧同步路径。

## Task 1: Phase 00–03 全门禁复核与 Phase 04 基线冻结

**Files:**
- Test: `tests/test_phase0_baseline.py`
- Test: `tests/test_phase1_proactive_baseline.py`
- Test: `tests/test_phase2_identity.py`
- Test: `tests/test_phase2_persona_source.py`
- Test: `tests/test_phase3_conversation_model.py`
- Test: `tests/test_api.py`
- Test: `tests/test_pipeline.py`
- Modify: `documents/Level_up/AI_Vibe_Coding/phases/Phase 04.md`
- Modify: `documents/Level_up/AI_Vibe_Coding/tasks/Task 04-baseline.md`

- [ ] **Red：新增/确认基线探针。** 在 Phase 04 测试文件尚未创建前只复核现有门禁；记录当前源码事实：`requests` 缺少 Phase 04 字段、API 仍同步、Renderer 仍有 `_loading`，这些是本阶段目标缺失，不改生产代码。
- [ ] **亲自观察门禁与目标缺失。** 运行：

```powershell
Set-Location E:\Agent_reply
python -m pytest tests/test_phase0_baseline.py tests/test_phase1_proactive_baseline.py tests/test_phase2_identity.py tests/test_phase2_persona_source.py tests/test_phase3_conversation_model.py tests/test_api.py tests/test_pipeline.py -q
Select-String -Path core\migrations\__init__.py -Pattern '006_chat_request_queue'
Select-String -Path electron\src\renderer\js\chat.js -Pattern '_loading'
```

预期：Phase 00–03 测试全部 PASS；第一条 `Select-String` 无匹配，第二条命中 `_loading`。前序测试若失败，停止 Phase 04；不得把前序失败写成 Phase 04 Red。
- [ ] **最小 Green：冻结基线而不实现功能。** 仅在 Phase/Task 文档写入本次门禁命令、结果、源码缺口和“尚未实施”；不修改源码。
- [ ] **定向回归。** 重跑同一 Phase 00–03 命令，预期结果与首次一致。
- [ ] **关联/完整回归。** 运行 `python -m pytest -q`，预期现有完整套件 PASS；此任务只记录基线，不宣称 Phase 04 Green。
- [ ] **Evidence。** 仅保存 passed/failed 计数、耗时、测试文件名、缺失符号名；不得保存聊天正文、账号或本地生产库内容。
- [ ] **文档更新。** 更新 Phase 04 与 Task 04 的基线段；`90/91/92` 的 Phase 04 checkbox 保持未勾选。
- [ ] **批后自检。** 回答七个快速自检问题，并明确“前序门禁 PASS、仍在 Phase 04、未写生产库”。

## Task 2: 006 migration 与 Database 注册

**Files:**
- Modify: `core/migrations/__init__.py`
- Modify: `core/database.py`
- Create: `tests/test_phase4_migration.py`
- Modify: `documents/Level_up/AI_Vibe_Coding/91_数据迁移核对.md`

- [ ] **Red：先写迁移测试。** 固定测试函数名：

```python
def test_phase4_migration_adds_request_queue_columns_and_indexes(): ...
def test_phase4_migration_checksum_is_fixed_and_004_005_unchanged(): ...
def test_phase4_migration_dry_run_has_zero_schema_writes(): ...
def test_phase4_migration_is_idempotent_after_second_run(): ...
def test_phase4_migration_recovers_partially_applied_columns_and_indexes(): ...
def test_phase4_migration_preserves_legacy_completed_null_snapshots(): ...
def test_database_runs_006_when_migration_framework_is_on_even_queue_flag_is_off(): ...
def test_database_does_not_run_versioned_006_when_migration_framework_is_off(): ...
def test_phase4_migration_quick_check_is_ok(): ...
```

断言 16 个新增列完整、至少三个索引存在、历史 `completed` 行新字段为 NULL、004 checksum 仍为 `7b808212291a457ff3ca1cc2a54e60a58192f80356f59ebefbb3de8349417702`，005 以当前已发布 checksum 精确断言。
- [ ] **亲自观察目标 Red。** 运行：

```powershell
python -m pytest tests/test_phase4_migration.py -q
```

预期：FAIL，明确显示 `phase4_request_queue_migrations`/006 或列、索引不存在；不得接受 Fixture 建库失败作为 Red。
- [ ] **最小 Green：实现固定 006。** 使用以下合同骨架，最终 checksum 必须由固定 contract 文本产生并在测试中写死：

```python
def _apply_phase4_request_queue(conn: sqlite3.Connection) -> None:
    columns = (
        ("actor_id", "TEXT DEFAULT NULL"),
        ("channel", "TEXT DEFAULT NULL"),
        ("channel_account_id", "TEXT DEFAULT NULL"),
        ("user_id", "INTEGER DEFAULT NULL"),
        ("input_content", "TEXT DEFAULT NULL"),
        ("effective_content", "TEXT DEFAULT NULL"),
        ("attachments", "TEXT DEFAULT NULL"),
        ("reply_to_id", "INTEGER DEFAULT NULL"),
        ("retry_of_request_id", "TEXT DEFAULT NULL REFERENCES requests(request_id)"),
        ("cancel_requested_at", "TEXT DEFAULT NULL"),
        ("cancelled_at", "TEXT DEFAULT NULL"),
        ("started_at", "TEXT DEFAULT NULL"),
        ("lease_owner", "TEXT DEFAULT NULL"),
        ("lease_expires_at", "TEXT DEFAULT NULL"),
        ("last_heartbeat_at", "TEXT DEFAULT NULL"),
        ("error_code", "TEXT DEFAULT NULL"),
    )
    for name, declaration in columns:
        _add_column_if_missing(conn, "requests", name, declaration)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_status_created ON requests(status, created_at, request_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_conversation_status ON requests(conversation_id, status, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requests_lease_expires ON requests(lease_expires_at) WHERE lease_expires_at IS NOT NULL")
```

`Database._init_schema()` 在 `migration_framework_v1=true` 时按 002/003 → 004 → 005 → 006 注册。**006 受 `migration_framework_v1` 控制，不受 `chat_request_queue_v1` 控制**；这样可先建 schema，再开运行 Flag。不得修改 004/005 contract 文本或 apply 函数。
- [ ] **定向回归。** 运行 `python -m pytest tests/test_phase4_migration.py tests/test_phase0_baseline.py tests/test_phase3_conversation_model.py -q`，预期全部 PASS。
- [ ] **关联/完整回归。** 运行 `python -m pytest tests/test_phase0_baseline.py tests/test_phase2_identity.py tests/test_phase3_conversation_model.py tests/test_api.py tests/test_pipeline.py -q`，随后 `python -m pytest -q`；预期全部 PASS。
- [ ] **Evidence。** 保存 006 固定 checksum、字段集合、索引名、dry-run pending 列表、二次运行行数不变、`PRAGMA quick_check=ok`；不保存数据库正文。
- [ ] **文档更新。** 更新 Phase 04、Task 04、`91_数据迁移核对.md`；`92_回滚演练.md` 仅记录尚待副本恢复的未完成项。
- [ ] **批后自检。** 明确 006 未依赖 queue Flag、004/005 未变、未直接操作生产库。

## Task 3: Phase 04 测试 Fixtures 与可注入 UTC 时钟

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_phase4_chat_request_repository.py`
- Create: `tests/test_phase4_chat_request_service.py`
- Create: `tests/test_phase4_chat_request_worker.py`

- [ ] **Red：写 Fixture 消费测试。** 固定测试函数名：

```python
def test_phase4_db_fixture_has_006_and_foreign_keys(phase4_db): ...
def test_frozen_utc_clock_advances_without_local_timezone(frozen_utc_clock): ...
def test_ready_attachment_fixture_contains_only_server_metadata(ready_attachment): ...
```

Fixture 必须使用临时目录和 `Database.reset_instance()`；附件仅含脱敏名、`/uploads/<uuid>.txt`、`state="ready"`、size/type，不含真实路径或正文。
- [ ] **亲自观察目标 Red。** 运行 `python -m pytest tests/test_phase4_chat_request_repository.py::test_phase4_db_fixture_has_006_and_foreign_keys tests/test_phase4_chat_request_service.py::test_ready_attachment_fixture_contains_only_server_metadata -q`，预期 ERROR/FAIL 指向 Fixture 尚未定义。
- [ ] **最小 Green：增加专用 Fixture。** 骨架：

```python
@pytest.fixture
def frozen_utc_clock():
    current = datetime(2026, 7, 20, 0, 0, tzinfo=timezone.utc)
    def now() -> datetime:
        return current
    def advance(seconds: int) -> None:
        nonlocal current
        current += timedelta(seconds=seconds)
    return SimpleNamespace(now=now, advance=advance)

@pytest.fixture
def phase4_db(tmp_path, monkeypatch):
    monkeypatch.setenv("AERIE_FEATURE_MIGRATION_FRAMEWORK_V1", "true")
    Database.reset_instance()
    db = Database(tmp_path / "phase4.db")
    yield db
    Database.reset_instance()
```

异步 doubles 必须显式暴露 `started`, `release`, `cancel_seen` Event，以便测试并发顺序，禁止真实模型、QQ、网络和 sleep 长等待。
- [ ] **定向回归。** 运行三个 Phase 04 Fixture 探针，预期 PASS。
- [ ] **关联/完整回归。** 运行 `python -m pytest tests/test_phase0_baseline.py tests/test_phase3_conversation_model.py tests/test_phase4_migration.py -q`，随后完整 `python -m pytest -q`。
- [ ] **Evidence。** 只记录临时 DB 文件名、固定 UTC 时间和 Fixture 状态，不记录临时绝对路径。
- [ ] **文档更新。** 在 Phase/Task 文档记录 Fixture 隔离策略；验收与回滚项仍保持未完成。
- [ ] **批后自检。** 确认可注入时钟统一返回 timezone-aware UTC，测试不依赖本机 Asia/Shanghai 时间。

## Task 4: ChatRequestRepository 持久状态机、claim、lease 与恢复

**Files:**
- Create: `core/chat_request_repository.py`
- Create: `tests/test_phase4_chat_request_repository.py`
- Modify: `core/conversation_repository.py`

- [ ] **Red：写仓储失败测试。** 固定测试函数：

```python
def test_submit_atomically_ensures_conversation_pending_turn_and_queued_request(): ...
def test_submit_rolls_back_all_three_records_on_request_insert_failure(): ...
def test_claim_next_is_atomic_and_skips_conversation_with_running_request(): ...
def test_claim_next_orders_by_created_at_then_request_id(): ...
def test_heartbeat_requires_matching_lease_owner_and_extends_utc_lease(): ...
def test_recovery_fails_running_cancelling_and_expired_lease_but_keeps_queued(): ...
def test_cancel_and_failure_keep_request_turn_status_invariant(): ...
def test_retry_creates_new_request_and_turn_with_original_unchanged(): ...
def test_repository_operations_do_not_hold_connection_during_pipeline_call(): ...
```

- [ ] **亲自观察目标 Red。** 运行 `python -m pytest tests/test_phase4_chat_request_repository.py -q`，预期 FAIL：模块/方法不存在或状态仍为 Phase 03 `completed` 镜像模式。
- [ ] **最小 Green：实现短事务与 UTC SQL 参数。** `submit()` 必须在一个 `BEGIN IMMEDIATE`/SAVEPOINT 中调用公共 `ensure_conversation()`、插入 pending Turn、插入 queued Request，保持 `turn_id NOT NULL`。claim 使用单事务选择最早 queued 且同 Conversation 无 `running/cancelling` 的行：

```sql
SELECT r.request_id
FROM requests r
WHERE r.status = 'queued'
  AND NOT EXISTS (
      SELECT 1 FROM requests active
      WHERE active.conversation_id = r.conversation_id
        AND active.status IN ('running', 'cancelling')
  )
ORDER BY r.created_at ASC, r.request_id ASC
LIMIT 1;
```

随后同事务执行带旧状态条件的 UPDATE：

```sql
UPDATE requests
SET status='running', started_at=?, updated_at=?, lease_owner=?,
    lease_expires_at=?, last_heartbeat_at=?, error=NULL, error_code=NULL
WHERE request_id=? AND status='queued';
```

`rowcount != 1` 时回滚并重试 claim。所有时间由 `clock()` 生成 `datetime.now(timezone.utc).isoformat()` 等价值，禁止 SQLite `localtime` 写入新队列字段。数据库上下文必须在调用 Pipeline 前退出。
- [ ] **状态守恒实现。** 每次 Request 转换在同事务同步 Turn：queued↔pending、running/cancelling↔running、completed/failed/cancelled↔同名 Turn；终态清空 lease。恢复先把 `running/cancelling` 或 lease 已过期的运行项置 `failed/process_interrupted`，queued 保持 queued，绝不自动重排。
- [ ] **定向回归。** 运行 `python -m pytest tests/test_phase4_chat_request_repository.py -q`，预期 PASS。
- [ ] **关联/完整回归。** 运行 `python -m pytest tests/test_phase3_conversation_model.py tests/test_phase4_migration.py tests/test_phase4_chat_request_repository.py -q`，随后完整回归。
- [ ] **Evidence。** 记录状态转换计数、并发 claim 冲突数、恢复数量和脱敏 request 前缀；不记录 input/effective content。
- [ ] **文档更新。** 更新 Phase/Task、全局验收的状态守恒子项、迁移核对；回滚文档记录 Flag 关闭时 queued 保留。
- [ ] **批后自检。** 确认仓储没有导入 Brain/Pipeline/chat_events/QQ，模型调用期间无数据库事务。

## Task 5: ConversationRepository 完成预分配 Turn/Request

**Files:**
- Modify: `core/conversation_repository.py`
- Modify: `tests/test_phase3_conversation_model.py`
- Create: `tests/test_phase4_chat_request_repository.py`

- [ ] **Red：写兼容与原子性测试。** 固定测试函数：

```python
def test_resolve_conversation_id_is_public_and_deterministic(): ...
def test_ensure_conversation_reuses_same_identity_key(): ...
def test_persist_turn_completes_existing_request_and_turn_without_duplicate_pk(): ...
def test_persist_turn_legacy_path_still_creates_completed_request_and_turn(): ...
def test_existing_request_completion_rolls_back_messages_and_status_on_failure(): ...
def test_recent_turn_history_reads_completed_turns_only(): ...
def test_failed_cancelled_pending_turns_never_enter_history(): ...
def test_completion_never_leaves_orphan_turn_or_half_completed_request(): ...
```

- [ ] **亲自观察目标 Red。** 运行上述新测试，预期 FAIL：`_conversation_id` 非公共、`persist_turn` 总是生成新 Turn 并插入 Request、history 未过滤 completed。
- [ ] **最小 Green：公开解析并扩展签名。** 固定签名：

```python
def resolve_conversation_id(*, actor_id: str | None, channel: str | None,
                            channel_account_id: str | None, user_id: int) -> str: ...

def ensure_conversation(self, conn: sqlite3.Connection, *, conversation_id: str,
                        actor_id: str | None, channel: str | None,
                        channel_account_id: str | None) -> None: ...

def persist_turn(self, *, request_id: str, user_id: int, actor_id: str | None,
                 channel: str | None, channel_account_id: str | None,
                 user_content: str, user_attachments: list[dict] | None,
                 assistant_segments: list[str],
                 conversation_id: str | None = None,
                 turn_id: str | None = None) -> dict[str, str] | None: ...
```

若 `request_id` 已存在，则校验其 conversation/turn 与参数一致，UPDATE 同一 Request/Turn 为 completed 并插入规范 Message；若不存在，保留 Phase 03 legacy 同步创建合同。整个 ensure/update/message insert 使用同一 SAVEPOINT。`recent_turn_history()` 的 CTE 增加 `AND status = 'completed'`。
- [ ] **防重复断言。** 同一 `request_id/turn_id` 再次完成必须幂等返回原 ID，不新增第二组 Message；若传入的 conversation/turn 或完成结果与已存结果不一致，则抛出 `RequestConflict`，不得覆盖已完成数据。
- [ ] **定向回归。** 运行 `python -m pytest tests/test_phase3_conversation_model.py tests/test_phase4_chat_request_repository.py -q`，预期 PASS。
- [ ] **关联/完整回归。** 运行 Phase 0–4 repository/migration/API/Pipeline 相关测试，随后完整回归。
- [ ] **Evidence。** 记录 Conversation/Turn/Request/Message 计数和孤立 FK 查询为 0，不记录 content。
- [ ] **文档更新。** 更新 Phase/Task、`91_数据迁移核对.md` 的完成已有 Request/Turn、SAVEPOINT、history completed-only 项。
- [ ] **批后自检。** 确认 legacy 同步路径仍可创建完整 Turn，队列路径不重复主键或生成孤立 Turn。

## Task 6: ChatRequestService、受信任身份、纯附件与错误合同

**Files:**
- Create: `core/chat_request_service.py`
- Create: `tests/test_phase4_chat_request_service.py`
- Modify: `communication/message.py`

- [ ] **Red：写 Service 测试。** 固定测试函数：

```python
def test_submit_ignores_renderer_actor_and_conversation_fields_by_signature(): ...
def test_submit_uses_trusted_desktop_local_identity_and_legacy_user_id(): ...
def test_submit_textless_ready_attachment_preserves_empty_input_and_internal_effective_content(): ...
def test_submit_rejects_empty_text_and_no_attachments_with_400_contract(): ...
def test_submit_rejects_non_ready_or_malformed_attachment(): ...
def test_get_non_owner_and_missing_are_indistinguishable_404(): ...
def test_cancel_terminal_is_idempotent_200_and_illegal_transition_is_409(): ...
def test_retry_only_failed_cancelled_and_returns_new_ids(): ...
def test_status_view_redacts_input_effective_attachments_lease_owner_and_error_stack(): ...
```

- [ ] **亲自观察目标 Red。** 运行 `python -m pytest tests/test_phase4_chat_request_service.py -q`，预期 FAIL：Service 不存在；不得先改 API。
- [ ] **最小 Green：实现验证和 DTO。** 纯附件规则：`input_content=""`；`effective_content="请结合用户提供的附件内容进行回应。"` 仅进入 Pipeline/Context，不写用户 Message、legacy `chat_log` 或事件的可见 content。文本存在时 effective content 等于原文本。附件必须为 dict，`state == "ready"`，URL 为单层 `/uploads/<safe-name>` 或兼容无前导 `/` 形式，禁止 `..`、反斜杠、绝对路径；不得接受 converting/failed。
- [ ] **所有权与异常类型。** 定义内部 `RequestNotFound`, `RequestConflict`, `QueueUnavailable`, `InvalidChatInput`，API 后续映射 404/409/503/400。所有者 actor 由后端 identity 生成；不存在与非所有者走同一路径。
- [ ] **定向回归。** 运行 Service 测试，预期 PASS。
- [ ] **关联/完整回归。** 运行 migration/repository/service/Phase 2 identity/Phase 3 conversation 测试，随后完整回归。
- [ ] **Evidence。** 只保存状态、HTTP 映射、附件数量和稳定 error_code；断言序列化结果不含 `input_content/effective_content/attachments/lease_owner/error`。
- [ ] **文档更新。** 更新 Phase/Task/全局验收的纯附件、所有权和错误合同；回滚文档仍不勾 Worker 项。
- [ ] **批后自检。** 确认 Renderer 无法指定 actor/conversation，内部中性指令未进入任何用户可见字段。

## Task 7: ChatRequestWorker 四槽、真实 Task、heartbeat 与恢复

**Files:**
- Modify: `core/chat_request_repository.py`
- Create: `core/chat_request_worker.py`
- Modify: `tests/test_phase4_chat_request_worker.py`

- [x] **Red：写 Worker 并发/取消测试。** 固定测试函数：

```python
async def test_worker_recovers_before_first_claim(): ...
async def test_worker_runs_four_distinct_conversations_and_fifth_waits(): ...
async def test_worker_serializes_requests_in_same_conversation(): ...
async def test_worker_keeps_real_asyncio_task_by_request_id(): ...
async def test_worker_heartbeats_while_pipeline_is_running(): ...
async def test_cancel_queued_never_calls_pipeline(): ...
async def test_cancel_running_cancels_task_and_marks_cancelled(): ...
async def test_cancelled_error_never_becomes_completed(): ...
async def test_event_emit_failure_does_not_reverse_database_terminal_state(): ...
async def test_stop_does_not_masquerade_as_user_cancel(): ...
async def test_cancel_running_missing_task_fails_request_instead_of_hanging(): ...
```

风险复核另固定 Repository 严格 completed/cancelled、过期 lease、claimed failure 双表回滚，以及 Worker lease_lost、deferred cancel、cancelling stop、deferred cancel + stop、pre-start cancel/stop 和 done-before-slot stop 场景；连同 UTC Fixture 共 23 项。

- [x] **亲自观察目标 Red。** 接管时 `13 failed, 1 passed`：严格完成接口和 Worker 缺失，且现有取消终态错误允许 running 直接 cancelled；并发测试均用 Event 控制。
- [x] **最小 Green：四个 slot loop。** 构造函数固定包含 `repository`, `pipeline`, `emit`, `clock`, `max_concurrency=4`, `lease_seconds`, `heartbeat_seconds`, `worker_id`。`start()` 先 `recover_interrupted()`，再创建四个 slot task；每次 claim 后创建真实执行 task 并写入 `self._running_tasks[request_id]`，heartbeat 单独 task。第五个 Conversation 在前四个至少一个结束后才运行。
- [x] **取消与 stop 区分。** 用户 cancel：Service 先将 running 转 cancelling，再调用 `cancel_running()`；执行 task 捕获 `asyncio.CancelledError`，仅 cancelling + matching lease 标 cancelled。`stop()` 先设置 stopping，再取消和等待执行，把本 Worker 持有的 running/cancelling 标为 `failed/worker_stopped`；queued 保持 queued。丢失 execution Task 的 cancelling 请求标为 `failed/cancel_task_missing`。
- [x] **事件失败边界。** Worker 所有的 running/completed/failed/cancelled 事件均在数据库提交后 best-effort emit；emit 抛错只记录结构化错误，不回滚数据库终态。queued 提交事件归属后续 Service/API 接线，不在未接线 Worker 中伪造。
- [x] **定向回归。** 初始 Green 后风险复核 Red 为 `5 failed, 15 passed`；最终 Worker 专项 `23 passed in 5.09s`，最大 active=4，`len(_running_tasks) <= 4`。
- [x] **关联/完整回归。** 加固关联 `136 passed, 4 warnings`；完整 `433 passed, 1 deselected, 6 warnings`；被排除的办公目录环境用例在工作区临时目录单独通过。
- [x] **Evidence。** 最大并发 4、第五等待、heartbeat 至少 1 次、用户取消等待上限 250ms/确认 `<500ms`、启动恢复 1 条遗留 active Request；过期 lease 不复活，lease_lost 停止 execution，stop 覆盖仍 active 的 deferred/pre-start cancel；未记录请求正文。
- [x] **文档更新。** 已更新 Phase/Task/全局验收/回滚和当前移交；复合端到端验收仍保持未勾选。
- [x] **批后自检。** recovery 先于首次 claim；Worker stop 不伪造用户 cancel；`_running_tasks` 保存并真实取消 execution Task。Worker 仍未接线，不影响旧 API/Pipeline/QQ/Renderer。

> Fail-closed 限制：若 heartbeat 数据库异常与随后的 failed 终态写入同时失败，execution 已停止，但 Request 依赖下一次进程启动的 recovery；Task 7 不承诺进程内数据库恢复后自动收口。

## Task 8: Pipeline FULL/BASIC RequestContext 与取消边界

**Files:**
- Modify: `communication/message.py`
- Modify: `core/pipeline.py`
- Create: `tests/test_phase4_pipeline.py`
- Modify: `tests/test_pipeline.py`

- [x] **Red：分别覆盖 FULL 与 BASIC。** 固定参数化合同：

```python
@pytest.mark.parametrize("route_mode", ["FULL", "BASIC"])
async def test_pipeline_uses_effective_content_for_model_but_visible_content_for_persistence(route_mode): ...
@pytest.mark.parametrize("boundary", [
    "before_model", "after_model", "before_legacy_user", "before_legacy_assistant",
    "before_canonical", "before_event", "before_qq_enqueue",
])
async def test_pipeline_cancellation_stops_before_named_side_effect(boundary): ...
async def test_pipeline_uses_existing_request_turn_and_conversation_for_canonical_mirror(): ...
async def test_irreversible_terminal_side_effect_prevents_fake_cancelled(): ...
async def test_request_events_include_complete_envelope_ids_and_monotonic_sequence(): ...
async def test_document_markdown_is_reextracted_from_trusted_upload_url(): ...
```

- [x] **亲自观察目标 Red。** 已运行 `python -m pytest --basetemp=E:\Agent_reply\tmp\pytest-task8-red tests/test_phase4_pipeline.py -q`，观察到收集期 `ImportError: cannot import name 'CancellationToken'`，目标缺口明确为 Pipeline/Message 取消合同尚不存在。
- [x] **最小 Green：扩展入口但保持旧调用兼容。** 固定签名：

```python
async def handle(self, msg: IncomingMessage, force_full: bool = False, *,
                 request_context: RequestContext | None = None,
                 cancellation_token: CancellationToken | None = None) -> dict | None:
```

旧同步调用可传 None。队列调用中 `msg.content` 始终是 `input_content`；Context/Brain 的用户输入改用 `request_context.effective_content`，但 legacy user row、规范 user Message、user event 均使用 `msg.content`。FULL/BASIC 都必须传附件给 Context Builder。
- [x] **可信文档提取。** Request 附件只把 Task 6 已验证的服务端 URL/元数据传入 Pipeline；文档 Markdown 由后端按可信 `/uploads/<filename>` URL 重新提取，客户端提交的 `content/markdown/path` 字段会被过滤。
- [x] **逐边界检查。** 在模型前/后、legacy user 持久化前、每个 legacy assistant 持久化前、canonical mirror 前、每个事件前、QQ enqueue 前调用 token。取消早于终态副作用时抛 `asyncio.CancelledError`；legacy 已写但 canonical 未完成时抛 `CancellationTooLate("terminal_side_effect_committed")`；canonical 已完成后采用 completion-wins，并停止后续事件/QQ 副作用。
- [x] **ID 与 EventEnvelope。** `_persist_canonical_turn()` 在 request context 存在时复用 context 的 request/turn/conversation；消息事件携带 `event_id/request_id/conversation_id/turn_id/message_id/response_group_id/sequence`，Pipeline 内部 request-scoped sequence 单调递增。
- [x] **定向回归。** `python -m pytest --basetemp=E:\Agent_reply\tmp\pytest-task8-post-doc-fix tests/test_phase4_pipeline.py tests/test_pipeline.py -q` → `36 passed in 2.36s`。
- [x] **关联/完整回归。** Phase 4 repository/service/worker/pipeline/API 相关：`135 passed, 4 warnings in 17.68s`；完整 `tests` 收集：`447 passed, 6 warnings in 26.85s`。仓库根完整收集曾因 `tmp/` 历史无权限目录产生 35 个 collection `WinError 5`，改用明确 `tests` 范围复验通过，未清理历史目录。
- [x] **Evidence。** `tests/test_phase4_pipeline.py` 覆盖 FULL/BASIC 可见输入隔离、各 boundary 副作用阻断、canonical ID 复用、事件完整 ID + 单调 sequence、可信 URL Markdown 重提取；测试不保存真实正文、真实路径或附件正文。
- [x] **文档更新。** 更新 Phase/Task/全局验收/回滚/移交说明的取消边界、可见 content、ID 复用和事件合同。
- [x] **批后自检。** FULL/BASIC 均覆盖；未整体重写 Pipeline；未实现 Phase 06 token streaming/pacing；Task 8 收口当时 Companion/API/Renderer 仍待 Task 9–11。

## Task 9: Companion 唯一实例、依赖门禁与 API 双合同

**Files:**
- Modify: `core/companion.py`
- Modify: `core/api_server.py`
- Modify: `core/chat_request_service.py`
- Modify: `core/chat_request_repository.py`
- Modify: `config/settings.yaml`
- Create: `tests/test_phase4_api.py`
- Create: `tests/test_phase4_integration.py`
- Modify: `tests/test_phase4_chat_request_service.py`
- Modify: `tests/test_api.py`

- [x] **Red：写组合根与 API 测试。** 固定测试函数：

```python
def test_companion_injects_one_repository_instance_into_service_worker_and_pipeline(): ...
def test_queue_flag_requires_migration_and_conversation_flags_fail_closed(): ...
async def test_worker_starts_before_qq_wait_until_ready(): ...
def test_api_queue_flag_on_returns_202_queued_without_waiting_pipeline(): ...
def test_api_queue_flag_off_preserves_legacy_200_shape_and_empty_400(): ...
def test_api_pure_attachment_202_and_empty_no_attachment_400(): ...
def test_api_unready_queue_returns_503_not_legacy_fallback(): ...
def test_api_get_cancel_retry_404_409_200_202_contracts(): ...
def test_api_non_owner_never_leaks_request_existence(): ...
def test_reply_to_requires_owned_message_in_same_actor_channel_conversation(): ...
def test_reply_to_missing_or_foreign_is_indistinguishable(): ...
def test_api_server_never_constructs_chat_request_repository(): ...
def test_flag_off_worker_does_not_consume_existing_queued_rows(): ...
```

- [x] **亲自观察目标 Red。** 已运行 `python -m pytest --basetemp=E:\Agent_reply\tmp\pytest-task9-red tests/test_phase4_api.py tests/test_phase4_integration.py -q`，观察到 `13 failed, 2 passed`：API 仍同步 200、组合根无 Service/Worker、门禁不存在、新端点不存在；3 个静态身份 FK 失败为测试夹具缺 actor/foreign conversation，已先修正夹具。
- [x] **最小 Green：组合根和依赖策略。** `Companion` 只创建一个 `ConversationRepository` 和一个 `ChatRequestRepository`，并把同一对象注入 Service/Worker/Pipeline。启动条件：

```python
queue_requested = flags.is_enabled("chat_request_queue_v1")
deps_ready = (
    flags.is_enabled("migration_framework_v1")
    and flags.is_enabled("conversation_model_v1")
)
if queue_requested and not deps_ready:
    self.chat_request_queue_ready = False   # API -> 503
    self.chat_request_queue_error = "queue_dependencies_unavailable"
elif queue_requested:
    self.chat_request_queue_ready = True
else:
    self.chat_request_queue_ready = False   # old sync path, not an error
```

Queue Flag 开启时 Worker 必须在 `await qq.wait_until_ready(...)` 之前启动，保证 desktop/local 不被 QQ readiness 阻塞。Flag 关闭不启动/消费 Worker，queued 行原样保留。
- [x] **API 路由。** `POST /api/chat/send`：Flag 关沿用现有同步代码与 200 shape；Flag 开调用 `comp.chat_request_service.submit()` 并 `JSONResponse(..., status_code=202)`。新增：

```text
GET  /api/chat/requests/{request_id}
POST /api/chat/requests/{request_id}/cancel
POST /api/chat/requests/{request_id}/retry
```

API 只取 `comp.chat_request_service`，不得导入/实例化 Repository。Service/Repository 在提交事务前验证非零 `reply_to_id` 对应 Message 属于同一 Actor、Channel、Channel Account 和 Conversation；不存在与跨所有权引用走同一错误路径。pure attachment 允许 202；空文本无附件 400；依赖或 Worker 未就绪 503。
- [x] **错误映射。** `RequestNotFound -> 404`，`RequestConflict -> 409`，`QueueUnavailable -> 503`，`InvalidChatInput -> 400`。终态 cancel 200；retry 成功 202 新 ID。响应不得包含 actor、输入快照、lease owner、堆栈。
- [x] **定向回归。** `python -m pytest --basetemp=E:\Agent_reply\tmp\pytest-task9-green tests/test_phase4_api.py tests/test_phase4_integration.py -q` → `15 passed, 4 warnings in 5.06s`。
- [x] **关联/完整回归。** 旧 API、Service、Repository、Worker、Pipeline：`135 passed, 4 warnings in 18.46s`；修复 integration 真实 `Companion` 与旧 API mock 模块级污染后，按反向敏感顺序复验 `67 passed, 4 warnings in 12.55s`；完整明确 `tests` 范围：`462 passed, 6 warnings in 35.41s`；`py_compile` 与 `git diff --check` 通过。
- [x] **Evidence。** HTTP 状态矩阵、响应 key 集合、单例对象身份、启动调用顺序、Flag 关闭 queued 数不变均由 `tests/test_phase4_api.py` 与 `tests/test_phase4_integration.py` 覆盖；不保存请求正文。
- [x] **文档更新。** 更新 Phase/Task/全局验收/回滚/移交说明：明确 fail closed、503、Flag 关旧路径和不消费 queued。
- [x] **批后自检。** 006 与运行 Flag 解耦；queue Flag 开但依赖缺失绝不静默回退，Flag 关仍是旧同步路径。Task 9 收口当时 Renderer 请求级状态、统一 ingest 与端到端 smoke 仍待 Task 10–11。

## Task 10: Renderer/Electron 请求状态、统一 ingest 与纯附件最小修复

**Files:**
- Modify: `electron/src/renderer/js/chat.js`
- Modify: `electron/src/preload.js`（仅监听清理 Red 需要时）
- Modify: `electron/src/renderer/js/chat-uploader.js`（仅 ready/upload Red 需要时）
- Create: `electron/tests/chat-request-queue.test.js`

- [x] **Red：用 Node VM 测试真实 `chat.js`。** 固定测试名：

```javascript
test("three rapid sends issue three POST requests without a global loading lock", async () => {});
test("client id is rebound to request id after each 202", async () => {});
test("request map tracks queued running cancelling failed cancelled completed", () => {});
test("cancel and retry call request-scoped endpoints", async () => {});
test("ipc sse and poll share one ingest path", () => {});
test("event_id deduplicates across transports", () => {});
test("request sequence buffers out-of-order events", () => {});
test("legacy numeric message ids remain compatible", () => {});
test("page restore queries non-terminal request statuses", async () => {});
test("sse disconnect is best effort and status polling recovers truth", async () => {});
```

VM sandbox 提供最小 DOM、`window.aerie.api.request/onMessage`、`window.aerie.sse.subscribe`、localStorage 和 fake timers；不得引入 jsdom 新依赖。
- [x] **亲自观察目标 Red。** 运行：

```powershell
Set-Location E:\Agent_reply\electron
node --test tests\chat-request-queue.test.js
```

已观察到 `10 failed, 0 passed`：第二/第三次 send 被 `_loading` 阻止，只发 1 个 POST；其余失败分别指向缺 request Map、统一 ingest、cancel/retry、页面恢复和 SSE best-effort 断线处理。
- [x] **最小 Green：请求级状态。** 删除 `_loading`；新增：

```javascript
this._requests = new Map();          // request_id -> RequestViewState
this._clientToRequest = new Map();   // client_id -> request_id
this._seenEventIds = new Set();
this._requestSequences = new Map();  // request_id -> { next, pending }
```

每次 send 生成稳定 client id，立即渲染独立用户气泡并 POST；202 后绑定真实 request id。每个请求独立跟踪 queued/running/cancelling/failed/cancelled/completed，提供 cancel/retry；retry 新建请求状态，不覆盖原请求。
- [x] **统一 ingest。** 实现 `_ingestChatSignal(signal, transport)`：先解析 SSE 字符串；有 `event_id` 先去重；有 `request_id+sequence` 按 sequence 缓冲并顺序应用；legacy poll/IPC numeric `id` 继续通过 `_seenIds` 去重。SSE 为 best-effort，断线不伪造失败；页面启动和重连调用 GET status 恢复后端真源。
- [x] **Uploader 限界。** 本批 Red 未证明 uploader 需要改动，因此未修改 `chat-uploader.js` 功能；仅运行 `node --check` 语法门禁。不新增图片元数据、EXIF、哈希、缩略图、GC 或 Phase 07 类型扩展。
- [x] **定向回归。** `node --test tests\chat-request-queue.test.js` → `10 passed in 149.8285ms`；`node --check src\renderer\js\chat.js`、`src\renderer\js\chat-uploader.js`、`src\preload.js` 均通过。
- [x] **关联/完整回归。** `node --test tests\persona-hub.test.js tests\chat-request-queue.test.js` → `13 passed in 115.723ms`；仓库根明确 `tests` 范围 `462 passed, 6 warnings in 35.06s`。
- [x] **Evidence。** 记录三次 POST 数、event 去重计数、sequence 应用顺序、恢复 GET 数和 Node 测试结果；未使用截图，未保存真实正文/账号。
- [x] **文档更新。** 更新 Phase/Task/全局验收/回滚/移交说明的连续输入、请求级状态、统一 ingest、页面恢复和 SSE best-effort。
- [x] **批后自检。** 确认没有全局 loading、没有引入新 npm 依赖、没有扩展 Phase 07 资产系统、legacy numeric id 仍兼容；Electron smoke 和生产副本演练仍待 Task 11/12。

## Task 11: 端到端集成、Electron smoke 与副作用守恒

**Files:**
- Create: `tests/test_phase4_integration.py`
- Modify: `tests/test_phase4_chat_request_service.py`
- Modify: `electron/tests/chat-request-queue.test.js`
- Modify: `core/brain.py`
- Modify: `communication/qq_client.py`
- Modify: `electron/src/main.js`
- Modify: `documents/Level_up/AI_Vibe_Coding/phases/Phase 04.md`

- [x] **Red：写端到端场景。** 固定测试函数：

```python
async def test_submit_claim_pipeline_complete_status_and_events_end_to_end(): ...
async def test_three_same_conversation_requests_complete_in_order(): ...
async def test_four_conversations_run_and_fifth_waits_end_to_end(): ...
async def test_queued_and_running_cancel_have_no_duplicate_model_message_event_or_qq(): ...
async def test_retry_creates_one_new_model_execution_and_preserves_original_terminal(): ...
async def test_restart_recovery_marks_interrupted_failed_and_keeps_queued_claimable(): ...
async def test_event_transport_failure_recovers_via_get_status(): ...
async def test_flag_off_preserves_old_sync_contract_and_does_not_consume_queue(): ...
```

- [x] **亲自观察目标 Red。** `python -m pytest --basetemp=E:\Agent_reply\tmp\pytest-task11-red tests/test_phase4_integration.py -q` → `3 failed, 12 passed, 4 warnings`；失败为 status DTO 和 retry DTO 的目标缺口，未制造虚假失败。
- [x] **最小 Green：只修集成接线缺口。** 未重构已 Green 模块；修复限定在 legacy↔canonical id 接线、request event sequence、Service DTO/worker notify、Electron smoke 临时路径和 smoke 安全开关。Task 11 自动化断言每个 request 的 model call、规范 Message、事件和 QQ 副作用不重复。
- [x] **Electron smoke。** 使用开发环境且临时 DB/Flag，不连接真实 QQ、不调用真实模型：启动后验证窗口加载、连续三次发送产生三个 202、请求状态可查询、cancel/retry 端点可达、GET status 作为恢复真源。实际命令：

```powershell
$env:AERIE_DB_PATH = "E:\Agent_reply\tmp\aerie-phase4-smoke3.db"
$env:AERIE_DATA_DIR = "E:\Agent_reply\tmp\aerie-phase4-smoke3-data"
$env:LOG_DIR = "E:\Agent_reply\tmp\aerie-phase4-smoke3-logs"
$env:AERIE_DISABLE_QQ = "true"
$env:AERIE_DISABLE_MODEL_CALLS = "true"
$env:AERIE_FEATURE_MIGRATION_FRAMEWORK_V1 = "true"
$env:AERIE_FEATURE_CONVERSATION_MODEL_V1 = "true"
$env:AERIE_FEATURE_CHAT_REQUEST_QUEUE_V1 = "true"
Set-Location E:\Agent_reply\electron
npm start -- --start-minimized
```

证据：renderer 窗口已加载；健康检查 `data_path_id=e:\agent_reply\tmp\aerie-phase4-smoke3.db`；日志确认 `QQ client disabled by AERIE_DISABLE_QQ` 与 `LLM provider calls disabled by AERIE_DISABLE_MODEL_CALLS`。三次 send 均 202，最终三个 request 均 completed；临时 DB 汇总 `requests=6`、`turns=6`、`messages=18`、`chat_log=18`。烟测完成后已按精确项目 PID 停止 node/electron/python 进程；保留临时 DB/log 作为本批 Evidence，未删除历史 pytest 临时目录。
- [x] **定向回归。** `tests/test_phase4_integration.py` → `15 passed, 4 warnings`；关联 Python（含 Brain provider routing）`188 passed, 4 warnings in 26.11s`；Node 两个测试文件 `14 passed`。
- [x] **关联/完整回归。** 完整显式 `tests` 收集 `471 passed, 6 warnings in 35.86s`；`py_compile` 与 `node --check src\renderer\js\chat.js`、`chat-uploader.js`、`preload.js`、`main.js` 通过。
- [x] **Evidence。** 已记录调用计数、状态序列、HTTP 状态、smoke 步骤、日志和临时 DB 脱敏计数；未保存模型正文、附件内容、账号、凭据或真实数据库路径。未保存截图，采用 renderer load 日志、健康检查和 API/DB 脱敏证据替代，避免采集用户界面内容。
- [x] **文档更新。** 更新 Phase/Task/全局验收/回滚/移交说明；迁移与恢复未演练前不得把 Phase 04 标为 done。
- [x] **批后自检。** Electron smoke 使用临时 DB/临时 data/log，无真实 QQ、无真实模型 provider、无生产库写入；事件失败不反转数据库终态由自动化覆盖。Task 12 仍待完成。

## Task 12: 生产数据一致性副本迁移、恢复与完整收口

**Files:**
- Modify: `documents/Level_up/AI_Vibe_Coding/phases/Phase 04.md`
- Modify: `documents/Level_up/AI_Vibe_Coding/tasks/Task 04-baseline.md`
- Modify: `documents/Level_up/AI_Vibe_Coding/90_全局验收清单.md`
- Modify: `documents/Level_up/AI_Vibe_Coding/91_数据迁移核对.md`
- Modify: `documents/Level_up/AI_Vibe_Coding/92_回滚演练.md`

- [x] **Red：先定义副本演练断言并在未迁移副本上观察缺失。** 当前只读生产检查发现源库已存在 006 completed ledger、新列和索引；原“006 pending/缺列”目标缺失不再适用于当前状态。未伪造 pre-006 生产副本；已记录 current-state contradiction，并继续对 SQLite Backup API 副本执行幂等/恢复演练。
- [x] **亲自观察目标缺失。** rehearsal B dry-run 返回 `[]` 而不是 `["006_chat_request_queue"]`，且字段断言已通过；这是因为当前源库已经完成 006。该项以“已观察当前状态与原 Red 预期矛盾”收口，不制造虚假失败。
- [x] **最小 Green：仅迁移 rehearsal B。** 使用现有 `MigrationRunner(...).run(phase4_request_queue_migrations())` 只作用于 B；dry-run、首次、二次 pending 均为 `[]`；16 列、三个索引、旧 completed 快照 NULL、记录数不变、`foreign_key_check=0`、`quick_check=ok`。
- [x] **实际恢复演练。** 从一致性快照 A 使用 SQLite Backup API 恢复到独立 restore C；A/C 六张关键表计数和脱敏有序摘要一致，数据损失 0；未覆盖真实生产库。
- [x] **Flag 回滚演练。** 新增 `test_task12_flag_rollback_matrix_reenables_queue_without_data_loss`，在临时数据库验证 queue Flag true 完成提交；停止 Worker；queue Flag false 旧 `/api/chat/send` 同步 200；既有 queued 不消费不删除；依赖缺失 + queue true 返回 503；重新开启且依赖完整后 queued 正常完成。
- [x] **完整回归。** 准确命令：

```powershell
Set-Location E:\Agent_reply
python -m pytest tests/test_phase0_baseline.py tests/test_phase1_proactive_baseline.py tests/test_phase2_identity.py tests/test_phase2_persona_source.py tests/test_phase3_conversation_model.py tests/test_phase4_migration.py tests/test_phase4_chat_request_repository.py tests/test_phase4_chat_request_service.py tests/test_phase4_chat_request_worker.py tests/test_phase4_pipeline.py tests/test_phase4_api.py tests/test_phase4_integration.py tests/test_api.py tests/test_pipeline.py -q
python -m pytest -q
Set-Location E:\Agent_reply\electron
node --test tests\persona-hub.test.js tests\chat-request-queue.test.js
node --check src\renderer\js\chat.js
node --check src\renderer\js\chat-uploader.js
node --check src\preload.js
node --check src\main.js
```

结果：Phase 00–04 关联门禁 `259 passed, 4 warnings in 29.21s`；完整显式 `tests` 收集 `472 passed, 6 warnings in 36.51s`；Electron Node `14 passed`；四个 `node --check` 无输出且退出码 0；`py_compile` 通过。裸 `python -m pytest -q` 未使用，因为当前工作区历史 `.pytest-task7-*` 权限目录会污染根收集，按批次约束改用显式 `tests` 范围。
- [x] **脱敏 Evidence。** 记录源 SHA 前后相同、dry-run/migration pending、006 checksum、表计数、NULL 计数、索引名、quick_check、恢复耗时、数据损失 0、回归计数；摘要使用长度/哈希，不保存正文。
- [x] **文档收口。** A-04-01 至 A-04-10 全部证据闭环、回滚演练成功、前序 Phase 00–04 关联门禁 PASS；已将 Phase 04 设为 done、Task checkbox 勾选、`rollback_ready: true`，并更新 `90/91/92`。
- [x] **批后自检。** 已重新回答七个快速自检问题；未直接写生产库、未提交/推送、未修改无关文件，且进入 Phase 05 前已复核 Phase 00–04。

## 3. 关键 SQL 与一致性查询

实现和验收至少使用以下查询；不得用只看总数替代状态守恒。

```sql
-- 同 Conversation 活跃请求不超过 1
SELECT conversation_id, COUNT(*) AS active_count
FROM requests
WHERE status IN ('running', 'cancelling')
GROUP BY conversation_id
HAVING COUNT(*) > 1;

-- Request/Turn 状态守恒
SELECT r.request_id, r.status AS request_status, t.status AS turn_status
FROM requests r JOIN turns t ON t.turn_id = r.turn_id
WHERE NOT (
    (r.status = 'queued' AND t.status = 'pending') OR
    (r.status IN ('running', 'cancelling') AND t.status = 'running') OR
    (r.status IN ('completed', 'failed', 'cancelled') AND t.status = r.status)
);

-- 孤立 Turn / Request / Message
SELECT t.turn_id FROM turns t
LEFT JOIN conversations c ON c.conversation_id=t.conversation_id
WHERE c.conversation_id IS NULL;
SELECT r.request_id FROM requests r
LEFT JOIN turns t ON t.turn_id=r.turn_id
WHERE t.turn_id IS NULL;
SELECT m.message_id FROM messages m
LEFT JOIN turns t ON t.turn_id=m.turn_id
WHERE t.turn_id IS NULL;

-- 历史 completed 行不被猜测式回填
SELECT COUNT(*)
FROM requests
WHERE status='completed'
  AND (input_content IS NOT NULL OR effective_content IS NOT NULL
       OR actor_id IS NOT NULL OR channel IS NOT NULL)
  AND created_at < :migration_started_at;
```

最后一条需以演练前快照中的 legacy request ID 集合限定，避免把迁移后真实 completed 请求误判为猜测回填。

## 4. API 响应骨架

```json
// POST /api/chat/send, queue on, 202
{
  "request_id": "req_...",
  "conversation_id": "conv_...",
  "turn_id": "turn_...",
  "status": "queued"
}
```

```json
// GET status, 200
{
  "request_id": "req_...",
  "conversation_id": "conv_...",
  "turn_id": "turn_...",
  "status": "running",
  "error_code": null,
  "created_at": "2026-07-20T00:00:00+00:00",
  "started_at": "2026-07-20T00:00:01+00:00",
  "completed_at": null,
  "cancelled_at": null,
  "can_cancel": true,
  "can_retry": false,
  "user_message_id": null,
  "assistant_message_ids": []
}
```

```json
// retry, 202
{
  "request_id": "req_new",
  "conversation_id": "conv_same",
  "turn_id": "turn_new",
  "status": "queued",
  "retry_of_request_id": "req_old"
}
```

错误只暴露稳定 code：

```json
{"error": "request_not_found"}
{"error": "request_state_conflict", "status": "running"}
{"error": "queue_dependencies_unavailable"}
{"error": "empty_message"}
{"error": "attachment_not_ready"}
```

## 5. Spec Coverage Matrix

| 验收 ID | 验收内容 | 主要任务 | 自动化测试 | 必需 Evidence |
|---|---|---|---|---|
| A-04-01 | 连续三条输入全部持久 queued，无全局 loading 丢失 | Task 9、10、11 | `test_api_queue_flag_on_returns_202_queued_without_waiting_pipeline`；Node `three rapid sends issue three POST requests without a global loading lock` | 三次 POST、三个不同 request/turn、queued 计数 3 |
| A-04-02 | 同 Conversation 严格串行 | Task 4、7、11 | `test_claim_next_is_atomic_and_skips_conversation_with_running_request`；`test_worker_serializes_requests_in_same_conversation` | 同会话最大 active=1、完成顺序 |
| A-04-03 | 跨 Conversation 最大四路，第五等待 | Task 7、11 | `test_worker_runs_four_distinct_conversations_and_fifth_waits` | 最大并发 4、第五启动时间晚于任一完成 |
| A-04-04 | queued/running 真实取消，cancelled 不误 completed | Task 6、7、8、11 | `test_cancel_queued_never_calls_pipeline`；`test_cancel_running_cancels_task_and_marks_cancelled` | 模型/Message/event/QQ 重复计数 0，状态守恒 |
| A-04-05 | retry 新 Request+Turn，关联原请求且无重复副作用 | Task 4、6、11 | `test_retry_creates_new_request_and_turn_with_original_unchanged`；`test_retry_creates_one_new_model_execution_and_preserves_original_terminal` | 新旧 ID、retry link、原终态不变、模型调用 +1 |
| A-04-06 | heartbeat/lease/重启恢复；running 失败且不自动重排 | Task 4、7、11 | `test_recovery_fails_running_cancelling_and_expired_lease_but_keeps_queued`；`test_worker_recovers_before_first_claim` | heartbeat 时间、`process_interrupted`、queued 保留 |
| A-04-07 | Request/Turn/Message 守恒；纯附件不污染可见历史 | Task 3–6、8 | `test_submit_textless_ready_attachment_preserves_empty_input_and_internal_effective_content`；`test_pipeline_uses_effective_content_for_model_but_visible_content_for_persistence` | 守恒 SQL 零行、可见 content 为空、内部字段不出响应 |
| A-04-08 | event_id 去重、request+sequence 有序、IPC/SSE/poll 不重复及页面恢复 | Task 8、10、11 | `test_request_events_include_complete_envelope_ids_and_monotonic_sequence`；Node `event_id deduplicates across transports`、`request sequence buffers out-of-order events` | 单 event_id 单渲染、sequence 单调、重连 GET 恢复 |
| A-04-09 | Flag 开 202；关 200 旧合同；依赖缺失 fail closed/503；关闭不消费 queued | Task 2、9、12 | `test_api_queue_flag_on_returns_202_queued_without_waiting_pipeline`；`test_api_queue_flag_off_preserves_legacy_200_shape_and_empty_400`；`test_queue_flag_requires_migration_and_conversation_flags_fail_closed`；`test_flag_off_worker_does_not_consume_existing_queued_rows` | HTTP 状态矩阵、旧响应 key、queued 数不变 |
| A-04-10 | 006 backup/dry-run/checksum/幂等/部分恢复/quick_check/实际恢复；所有权不泄露 | Task 2、6、9、12 | `test_phase4_migration_checksum_is_fixed_and_004_005_unchanged`；`test_phase4_migration_dry_run_has_zero_schema_writes`；`test_phase4_migration_is_idempotent_after_second_run`；`test_phase4_migration_recovers_partially_applied_columns_and_indexes`；`test_phase4_migration_quick_check_is_ok`；`test_get_non_owner_and_missing_are_indistinguishable_404` | 固定 checksum、quick_check=ok、数据损失 0、404 等价响应 |

## 6. 最终自审清单（实施计划作者与执行者均需执行）

- [x] 搜索计划和实施差异中是否出现模糊占位语句；若出现必须替换为具体接口、断言或命令。
- [x] 核对 `RequestIdentity`、`RequestContext`、`SubmittedRequest`、`ClaimedRequest`、`RequestStatusView` 的字段在 Repository、Service、Worker、Pipeline、API、Renderer 测试中完全同名。
- [x] 核对 Request 状态只使用 queued/running/cancelling/completed/failed/cancelled，Turn 使用 pending/running/completed/failed/cancelled；不得新增未迁移状态。
- [x] 核对 16 个 006 字段名与 Phase 04 权威文档完全一致，至少三个索引名和用途已测试。
- [x] 核对所有新队列时间为 UTC ISO 8601 且时钟可注入；不得在新逻辑使用 `datetime('now','localtime')`。
- [x] 核对 `migration_framework_v1` 控制 006 执行，`chat_request_queue_v1` 只控制运行路径；queue Flag 开启还必须依赖 migration + conversation 两 Flag。
- [x] 核对 API 非所有者统一 404、非法状态 409、终态 cancel 幂等 200、retry 仅 failed/cancelled 且 202 新 ID。
- [x] 核对 Flag 关闭保持旧 `/api/chat/send` 同步 200 和空消息 400，不启动 Worker、不消费 queued。
- [x] 核对 `api_server.py` 没有创建第二 Repository，Companion 注入对象身份一致。
- [x] 核对 Pipeline FULL/BASIC 都检查取消边界，visible `msg.content` 不被 effective content 替换，镜像不再生成第二 request ID。
- [x] 核对 Renderer 的 IPC/SSE/poll 只进入统一 ingest，SSE 仍为 best-effort，legacy numeric id 仍兼容。
- [x] 核对 uploader 修改若存在，仅解决本阶段 ready/IPC 合同，未实现 Phase 07 资产能力。
- [x] 核对所有测试和演练使用临时数据库或一致性副本，从未直接写生产库。
- [x] 核对每批均有真实 Red、最小 Green、定向回归、关联/完整回归、脱敏 Evidence 和五份控制文档更新记录；Task 12 的原 Red 预期因当前源库已完成 006 而以 current-state contradiction 记录。
- [x] 核对计划和实施均无 commit/push 步骤，最终进入 Phase 05 前重新复核 Phase 00–04 全部门禁。
