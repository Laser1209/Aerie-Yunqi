---
title: 安卓端综合实施计划（Phase 5 文件 + Phase 7 Tunnel + Phase 8 发布）
date: 2026-08-10
tags:
  - plan
  - android
  - phase5
  - file-transfer
  - cloudflare-tunnel
  - release
status: 待审阅
version: v1.0
deadline: 2026-09-01
---

# 安卓端综合实施计划

> 整合范围：Android Master Plan（[Aerie\_Android\_Companion\_Master\_Plan.md](../../documents/Android/Aerie_Android_Companion_Master_Plan.md)）剩余阶段。用户已确认：范围=安卓端路线；优先级=文件→Tunnel→发布；硬性截止 2026-09-01。

***

## 1. Summary（概述）

把上次制定的 Android Master Plan 剩余阶段（Phase 5 文件双向传输、Phase 7 Cloudflare Tunnel、Phase 8 签名发布）与最新需求（用户确认以 Cloudflare Tunnel 作为公网联络中转，域名 `etta.top` 已托管 Cloudflare）整合为一条可执行主线。

**二次审计结论（与主控文档快照的关键差异）**：

| 阶段            | 主控文档快照（07-23）                        | 实际代码状态（08-10 实测）                                                     |
| ------------- | ------------------------------------ | -------------------------------------------------------------------- |
| Phase 5 服务端   | "进入 implementing，尚无 Phase 5 功能可宣称完成" | **已完整实现**：`mobile_files.py` 1335 行无占位、7 组文件路由全挂载、10 项测试全过            |
| Phase 5 服务端缺口 | —                                    | **缺 CLI 目录授权命令**（`scripts/mobile_accounts.py` 无 directory grant 子命令） |
| Phase 5 安卓客户端 | "Android 完成文件选择、进度、取消、恢复、预览和下载"      | **完全未开始**：无 `MobileFileApi`、无 FileRepository、无 Room 文件表、文件 tab 为占位   |
| Phase 7       | 未开始                                  | 未开始：`cloudflared` 未安装、`aerie.etta.top` NXDOMAIN                      |
| Phase 8       | 部分                                   | Release 未签名 APK 已构建（R8 已通过），签名密钥未创建                                  |

**执行主线**：补齐服务端 CLI → 开发安卓文件客户端 → 真机验收 → Cloudflare Tunnel 公网打通 → 签名发布 → 主控文档状态收口。

**定位边界（已确认）**：手机端只承担**登录/会话、消息同步、文件与图片上传下载、指令发送、状态查看、审批**；所有"人格与智能"能力（伊塔人设、情感引擎、分层记忆、简报订阅、世界模拟、主动推送、文生图/视觉理解）均在电脑端运行，手机端既不实现也不感知。图片上传属于 Phase 5 文件传输范畴（MIME 白名单已含 png/jpg/jpeg/gif/webp），走同一分块/续传/校验链路，不单独实现"图片功能"。

***

## 2. Current State Analysis（现状分析）

### 2.1 原计划执行进度评估

| Phase               | 门禁                             | 状态         | 质量证据                                        |
| ------------------- | ------------------------------ | ---------- | ------------------------------------------- |
| 0 文档基线              | UTF-8/Markdown/端口/敏感扫描         | ✅ verified | 主控文档 Evidence 2026-07-21                    |
| 1 最小安全网关            | 7891 独立 app、路由白名单              | ✅ verified | 25 项测试                                      |
| 2 账号/设备/身份          | Argon2id、配对码、令牌轮换              | ✅ verified | 真机 owner 登录 + Keystore 恢复                   |
| 3 持久聊天              | Conversation/Request Queue/SSE | ✅ verified | 服务器回归 632/632                               |
| 4 Android 基础端       | 登录/聊天/任务/前台服务/周期同步             | ✅ verified | Android JVM 38/38、真机 9/9、Room 与服务器 1188 条一致 |
| 5 文件双向传输            | 服务端完整、客户端未动、CLI 缺失             | ⚠️ 半程      | 服务端 10 项测试通过；客户端零代码                         |
| 6 手机审批              | 未开始                            | ⬜ 未开始      | —                                           |
| 7 Cloudflare Tunnel | 未开始                            | ⬜ 未开始      | DNS 已托管 CF，隧道未建                             |
| 8 发布                | 未签名 Release 已构建                | ⬜ 部分       | R8 通过，keystore 未创建                          |

**完成质量判断**：Phase 0-4 均以自动化 + 真机双重证据收口，主控文档变更规则被严格遵守（每阶段有 Evidence、备份、快速检查）。当前主要欠账集中在 Phase 5 客户端与 Phase 7/8，且服务端 Phase 5 已先行完成——这是显著的正向偏差，意味着客户端开发可立即开始，无需等待服务端。

### 2.2 服务端 Phase 5 现状（已确认可用）

* `core/mobile_files.py`：分块上传会话（4MB 分块、50MB 上限、24h 过期、每账号 2 活动会话）、clientUploadId 幂等、断点续传/乱序分块、块级+整文件 SHA-256、流式组装、14 种 MIME 白名单 + 文件签名交叉校验、Windows Defender fail-closed 扫描、隔离区精确清理、目录 ACL（read/upload/download + enabled 停用即失效）、owner 授权目录 / guest Inbox-Outbox、Range 下载（200/206/416 + ETag + Content-Disposition 脱敏）、电脑产物登记、聊天附件集成、全链路审计。

* `core/mobile_gateway.py` L449-565：文件路由已全部挂载，`/me` 声明 `capabilities.files=True`。

* `tests/test_mobile_files.py`：10 项测试，无 skip/TODO。

* **唯一服务端缺口**：`scripts/mobile_accounts.py`（L114-138 子命令清单）没有目录授权管理命令，与主控文档 §8.2"owner 目录授权只能由电脑本地管理命令创建、停用和修改"冲突。

### 2.3 安卓客户端 Phase 5 现状（零代码）

* `data/remote/`：无文件 API；`SubmitMobileRequestDto.fileIds` 已预留但恒为空。

* Room：`AerieChatDatabase` v3，4 张聊天表，无文件传输状态表。

* UI：`AerieApp.kt` L353 文件 tab 为 `EmptyOperationalScreen("暂无可用文件")` 占位。

* 依赖：okhttp 4.12.0 MultipartBody 可用；Retrofit 内置 multipart 参数处理可用；activity-compose 的 `rememberLauncherForActivityResult` 可拉起 SAF；**缺** `androidx.documentfile`；OkHttp 超时 30s write 不满足大文件上传，需单独客户端配置。

### 2.4 联络与发布现状

* `etta.top` 已完整托管 Cloudflare NS（alina/isaac.ns.cloudflare.com，实测解析正常）。

* `aerie.etta.top` 在 1.1.1.1/8.8.8.8 均 NXDOMAIN（命名隧道未创建）。

* `cloudflared` 未安装，无 Windows 服务。

* 安卓 Release 构建常量已默认 `https://aerie.etta.top`；Debug 默认 `http://127.0.0.1:7891`。

* 服务器仓库 `main` 分支有 6 个 ahead 未推送提交，工作树含运行态文件（chroma/data/desire\_state 等），开发过程需保持白名单纪律。

***

## 3. Proposed Changes（建议改动）

### 3.1 服务端：补齐目录授权 CLI（Phase 5 前置）

**文件**：`e:\Agent_reply\scripts\mobile_accounts.py`

* 新增 4 个子命令：

  * `grant-directory <username> --path <绝对路径> --read/--no-read --upload/--no-upload --download/--no-download [--enable]`：调用 `MobileFileService.register_directory_grant`（`core/mobile_files.py` L388），owner 专用，绝对路径校验 + 幂等 upsert。

  * `list-directory-grants [username]`：列出 owner 目录授权（脱敏展示，不含密码/令牌）。

  * `disable-directory-grant <username> --path <绝对路径>`：`enabled=0`，文件立即不可见（复用已实现行为）。

  * `enable-directory-grant <username> --path <绝对路径>`：恢复。

* `MobileFileService` 需要暴露 store/路径注入方式给 CLI（当前 `register_directory_grant` 走 service 层，CLI 需要能构造 `MobileFileService` 实例，参考 `_store()` 构造 `MobileIdentityStore` 的既有模式）。

* **不做**：不在移动 API 增加目录登记端点（主控文档 §8.2 明确禁止）。

**测试**：`tests/test_mobile_accounts_cli.py` 增加 CLI 级目录授权测试；`tests/test_mobile_files.py` 现有 10 项保持通过。

### 3.2 安卓客户端：Phase 5 文件双向传输（主要工作量）

新增文件/改动清单（全部在 `e:\Agent_reply\android-client\app\src\main\java\top\etta\aerie\`）：

**3.2.1 网络层**

* 新增 `data/remote/MobileFileApi.kt`：Retrofit 接口 + 文件 DTO。

  * `POST /files/uploads`（CreateUploadRequest：clientUploadId/fileName/size/sha256/mimeType/directoryGrantId）

  * `GET /files/uploads/{id}`（UploadSessionDto：uploadId/partSize/partCount/uploadedParts/expiresAt/status）

  * `PUT /files/uploads/{id}/parts/{partNumber}`（`@PUT` + `@Body RequestBody` 原始二进制 + `@Header("X-Part-SHA256")`）

  * `POST /files/uploads/{id}/complete`

  * `DELETE /files/uploads/{id}`

  * `GET /files`（beforeId 游标分页）

  * `GET /files/{id}`、`GET /files/{id}/content`（`@Streaming` + Range header，返回 ResponseBody）

* 扩展 `data/remote/MobileApiFactory.kt`：新增 `createFile(baseUrl): MobileFileApi`；为文件客户端单独构造 `OkHttpClient`（writeTimeout 提高到 120s+，不污染聊天客户端超时）。

**3.2.2 本地存储**

* 新增 Room 表 `file_transfers`（accountId + fileId/uploadId 主键；类型 upload/download；状态 queued/uploading/paused/completed/failed；本地 Uri 持久化 URI string；已传字节数；总字节数；clientUploadId；partSize；错误码），`AerieChatDatabase` 升到 **v4**，新增 `MIGRATION_3_4`（建表，不破坏聊天数据，遵守既有迁移纪律）。

**3.2.3 仓库层**

* 新增 `data/file/MobileFileRepository.kt`：封装分块上传（1-based 4MB 分块、逐块 SHA-256、幂等重传）、断点续传（从 Room 读 uploadedParts 跳过已传块）、取消、Range 下载续传（记录已下字节，断点后 `bytes=已下-`）、文件列表/元数据；复用 `AuthorizedRequestExecutor` 的单次 401 刷新重试与错误映射。

**3.2.4 UI 层**

* `ui/AerieApp.kt`：文件 tab（`selectedIndex == 2`）替换占位为 `FileScreen`：

  * 文件列表（LazyColumn，fileId/名称/大小/时间，beforeId 加载更多）

  * 上传入口（`rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument())` + SAF，无 documentfile 依赖，直接用 contentResolver + OpenableColumns）

  * 传输进度卡片（进度条、暂停/取消/重试按钮）

  * 下载后打开（`FileProvider` + Intent.ACTION\_VIEW，或临时目录）

  * owner 上传时可选授权目录（`GET /files` 若返回目录信息则选择；目录选择入口来自 CLI 预配的 grant）

* `ui/AerieViewModel.kt`：新增文件相关状态与动作（上传/下载/取消/重试），沿用 `flatMapLatest(accountId)` 隔离模式。

**3.2.5 聊天附件打通**

* 上传完成后把 `fileId` 填入 `SubmitMobileRequestDto.fileIds`，支持"文本 + 附件"同请求（`data/chat/NetworkChatRepository.kt` 的 submit 扩展可选 fileIds 参数）。

* `MessageBubble` 对 `attachmentsJson` 非空消息显示文件占位（下载/打开入口），纯文本消息行为不变。

**3.2.6 文档**

* 新增 `e:\Agent_reply\android-client\docs\phase5-files.md`，记录合同实现与验证证据（沿用 phase4 文档格式）。

**测试**：

* JVM：MockWebServer 覆盖上传会话创建/幂等/续传/完成、分块 SHA-256 冲突、Range 下载续传、401 重试、错误映射（新增 `MobileFileRepositoryTest`）。

* Room：`RoomChatMigrationTest` 增加 v3→v4 迁移保留聊天数据、文件表建表。

* Compose：`MainActivityComposeTest` 增加文件 tab 渲染/上传按钮/进度。

* **真机验收**（沿用 Phase 4 流程）：owner 上传接近 50MB 文件（网络中断续传）、下载 + Range 续传、文件 tab 列表一致性、聊天带附件请求进入任务队列。

### 3.3 Phase 7：Cloudflare Tunnel（公网打通）

1. 安装 `cloudflared`（Windows），下载官方二进制到用户目录（不进 Git）。
2. `cloudflared tunnel login`（**需用户在浏览器完成 Cloudflare OAuth 授权**——唯一用户阻塞点）。
3. 创建命名 Tunnel：`aerie.etta.top → http://127.0.0.1:7891`（`config.yml` 放用户目录，凭据不进 Git）。
4. 注册为 Windows 服务（`cloudflared service install`），验证系统重启后自动恢复。
5. 验收：

   * `aerie.etta.top` 在公共解析器返回 Cloudflare IP（A 记录）。

   * 公网访问 `/api/mobile/v1/health` 返回 200；`/docs`、`/openapi.json`、`/api/system/restart`、`/api/brain/shell` 等 7890 高权限路径经公网 **404/不可达**。

   * 安卓 Release/Debug 切 `https://aerie.etta.top` 真机登录成功（不走 ADB reverse）。
6. **约束**：Tunnel 只指向 7891；7890 保持本地绑定；不使用通配 CORS；不开放路由器端口。

### 3.4 Phase 8：签名发布

1. 创建仓库外固定签名密钥（keystore 放仓库外 + 离线备份，密码不进文档/Git；用户确认备份位置）。
2. `assembleRelease` 产出签名 APK；`apkanalyzer` + APK 敏感字符串扫描（沿用 07-23 流程）。
3. 真机覆盖安装验证数据保留（Room/WorkManager/Keystore 会话不丢失）。
4. `AERIE_DISABLE_QQ=true` 全链路闭环验证（聊天/文件/审批），确认 Android 路径独立于 QQ。
5. 主控文档 §16 追加 Evidence，状态更新为 `released`。

### 3.5 Phase 6 手机审批（排后，视时间执行）

* 服务端：挂载 `/approvals`、`/approvals/{id}`、`/approvals/{id}/challenge`、`/approvals/{id}/decision`、`/owner/audit`（审计数据已在写，只缺查询面）。

* 客户端：审批列表/详情、Keystore ECDSA 密钥 + `BiometricPrompt` 签名、挑战应答。

* **若 2026-09-01 前 Phase 5/7/8 已完成且质量达标**则实施；否则标记为下阶段，不牺牲 Phase 5/7/8 质量。

***

## 4. Assumptions & Decisions（假设与决策）

| #  | 决策/假设                                                     | 依据                    |
| -- | --------------------------------------------------------- | --------------------- |
| D1 | 服务端 Phase 5 文件 API 视为**可用基线**，客户端直接对接，不返工                 | 08-10 实测代码完整、10 项测试通过 |
| D2 | 主控文档 Phase 5 状态在收口时同步更新（`implementing → verified`），消除文档漂移 | 主控文档 §18 变更规则         |
| D3 | 目录授权 CLI 是 Phase 5 客户端前置条件（owner 上传必须选 grant）             | 主控文档 §8.2             |
| D4 | 大文件传输使用独立 OkHttp 客户端超时，不污染聊天客户端                           | 现有 30s write 超时不满足    |
| D5 | Tunnel 创建需用户在浏览器完成 Cloudflare OAuth（阻塞点，安排在客户端开发完成后触发）    | cloudflared 机制        |
| D6 | 签名密钥密码/位置由用户线下保管，Agent 只负责生成命令与使用                         | 主控文档 §11              |
| D7 | 服务器仓库 `main` 分支 6 个 ahead 提交与工作树运行态文件不在本计划提交范围            | 主控文档 §10.6 仓库边界       |
| D8 | 真机验收需要 vivo V2516A 在线连接（ADB），验收窗口由用户提供                    | Phase 4 流程            |

***

## 5. Priority & Timeline（优先级与时间节点）

截止 2026-09-01（今天 08-10，约 3 周）。按"文件 → Tunnel → 发布"排序，含缓冲期：

| 阶段                       | 内容                                       | 计划窗口           | 依赖            | 里程碑验收                                |
| ------------------------ | ---------------------------------------- | -------------- | ------------- | ------------------------------------ |
| **S1 服务端 CLI**           | directory grant 4 子命令 + 测试               | 08-10 \~ 08-12 | 无             | CLI 定向测试 + 文件回归 10 项通过               |
| **S2 客户端网络/存储**          | MobileFileApi/DTO、Room v4、FileRepository | 08-12 \~ 08-18 | S1            | JVM 测试（MockWebServer 上传/下载）通过        |
| **S3 客户端 UI/聊天附件**       | 文件 tab、SAF 选择、进度、消息附件                    | 08-18 \~ 08-22 | S2            | Compose 测试 + assembleDebug + lint    |
| **S4 真机文件验收**            | 50MB 上传/续传/下载、聊天附件                       | 08-22 \~ 08-25 | S3 + 真机在线     | 真机 instrumented 通过，Room/服务器一致        |
| **S5 Cloudflare Tunnel** | cloudflared、命名隧道、Windows 服务、公网验收         | 08-25 \~ 08-27 | S4 + 用户 OAuth | aerie.etta.top 可达、7890 不可达、真机公网登录    |
| **S6 签名发布**              | keystore、签名 APK、覆盖安装、QQ 独立验收             | 08-27 \~ 08-29 | S5            | 签名 APK 验收、数据保留、AERIE\_DISABLE\_QQ 闭环 |
| **S7 收口与缓冲**             | 主控文档 Evidence/状态、Phase 6 视时间执行           | 08-29 \~ 09-01 | S6            | 文档一致、风险清零、缓冲消化                       |

**资源分配**：

* Agent（当前任务）：S1-S3、S5 前半、S6 前半、S7 全部代码与验证；S4 真机指令执行。

* 用户：S4/S6 真机接入与系统授权（允许后台耗电）；S5 的 Cloudflare OAuth 浏览器授权；S6 keystore 备份保管；验收确认。

***

## 6. Risk Register（风险与应对）

| #  | 风险                              | 概率/影响 | 应对                                                              |
| -- | ------------------------------- | ----- | --------------------------------------------------------------- |
| R1 | Cloudflare OAuth 授权阻塞 S5        | 高/中   | S5 排在客户端完成后；如用户延迟，先做 S6 中不依赖公网的部分；预留缓冲期                         |
| R2 | 真机不在线导致 S4/S6 验收延迟              | 中/高   | 客户端阶段用 JVM/MockWebServer + Compose 测试保底；真机窗口压缩为两次集中验收（文件、发布）    |
| R3 | 50MB 上传在 OriginOS 后台被冻结         | 中/中   | 前台服务在传输期间保持活动；参考 Phase 4 已通过的"允许后台耗电"配置；续传机制兜底                  |
| R4 | 大文件上传触发 OkHttp/Retrofit 超时或内存峰值 | 中/中   | 独立客户端 + 独立超时；分块流式写入；分块级 fsync 语义依赖服务端已实现                        |
| R5 | Room v3→v4 迁移破坏既有聊天数据           | 低/高   | 沿用 MIGRATION\_1\_2/2\_3 模式，只 ADD TABLE；迁移测试 + 真机覆盖安装验证 1188 条保留 |
| R6 | 服务器仓库工作树运行态文件被误提交               | 中/低   | 按 §10.6 白名单纪律，只提交 owned 路径；git status 复核                        |
| R7 | 3 周时间不足完成 Phase 6 审批            | 中/低   | 已明确 Phase 6 排后；S5/S6 质量优先，审批不强推                                 |
| R8 | 签名密钥丢失导致无法覆盖升级                  | 低/高   | keystore 创建后立即离线双备份（用户确认位置）后才执行 S6                              |
| R9 | Defender 扫描拖慢大文件完成时间            | 中/低   | 120s 超时 fail-closed 为既有合同；真机验收用真实 Defender 记录耗时，不绕过             |

***

## 7. Verification（验证方案）

每个阶段按主控文档 §14 测试合同执行，逐阶段记录 Evidence：

1. **S1**：`python -m pytest tests/test_mobile_accounts_cli.py tests/test_mobile_files.py -q` 全过；`scripts/mobile_accounts.py grant-directory/list/disable/enable` 手工验证 owner 目录授权生命周期。
2. **S2/S3**：`.\gradlew.bat :app:testDebugUnitTest :app:assembleDebug :app:lintDebug --no-daemon`（沿用 1.5GB 堆基线参数）；新增 `MobileFileRepositoryTest`、Room 迁移测试、Compose 文件 tab 测试。
3. **S4**：vivo V2516A 真机 `am instrument` + 手工上传/续传/下载；Room 与服务器文件列表核对；聊天附件请求进入任务队列并完成。
4. **S5**：`Resolve-DnsName aerie.etta.top` 返回 Cloudflare IP；公网 health 200；7890 高权限路由公网 404；`Get-Service cloudflared` 为 Running；重启电脑后隧道自动恢复。
5. **S6**：`apkanalyzer` 验证签名与包信息；APK 敏感字符串零命中；覆盖安装后 1188 条消息保留；`AERIE_DISABLE_QQ=true` 全链路闭环。
6. **S7**：主控文档 §16 追加本计划全部 Evidence，Phase 5/7/8 状态同步；`git diff --check` 通过；文档 UTF-8/Markdown/敏感扫描复核。

***

## 8. 变更纪律

* 本计划实施期间，公共 API、端口、权限、目录边界或文件类型的任何变更，先更新主控文档决策日志再改实现。

* 每阶段先跑定向测试，再跑相关回归；数据库变更必须备份 + dry-run + quick\_check。

* 不把调试令牌、测试账号、真实目录、Cloudflare 凭据或签名密码写入源码/测试/日志/文档。

