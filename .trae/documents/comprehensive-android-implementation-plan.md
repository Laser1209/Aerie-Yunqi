---
title: 移动端综合实施计划（Flutter 重写 · 跨端路线）
date: 2026-08-10
tags:
  - plan
  - mobile
  - flutter
  - cross-platform
  - cloudflare-tunnel
  - release
status: 待审阅
version: v2.0
deadline: 2026-09-01
---

# 移动端综合实施计划（v2.0 · Flutter 重写）

> 本版基于用户决策重写：**移动端改用 Flutter 跨端重写（Android + iOS）**，桌面端保持 Electron、服务端 7891 网关不变。
> 范围=仅移动端；优先级=文件→Tunnel→发布；硬性截止 2026-09-01。
> 原 v1.0 计划（原生 Kotlin）作废，本版为唯一执行依据。

---

## 1. Summary（概述）

### 1.1 决策变更

| 维度 | v1.0（原生 Kotlin） | v2.0（本版） |
| --- | --- | --- |
| 客户端框架 | Kotlin + Jetpack Compose，仅 Android | **Flutter，Android + iOS 双端一套代码** |
| 移动端功能 | 消息同步 + 文件/图片传输 | 相同，另含**只读能力外接**（简报/世界/记忆/天气） |
| 服务端 | 7891 网关 API 合同不变 | **不变 + 补齐外接只读端点** |
| 桌面端 | Electron 不变 | 不变 |
| 隧道 | Cloudflare Tunnel 独立服务 | 不变（用户已确认独立服务方式） |

### 1.2 核心事实（二次审计结论）

**服务端 7891 移动网关已高度完备**（21 条路由全挂载，Phase 1-3 已验证）：

- 认证与设备 7/7、聊天与请求 6/6、文件 8/8 —— **全部实现**
- 移动消息与桌面共享同一时间线（channel=mobile → 桌面 pipeline），实测 1188 条消息一致
- 文件传输（4MB 分块/SHA-256/Range/Defender 扫描/目录 ACL）代码完备，仅缺真机闭环证据

**服务端缺口（Flutter 接入前需补齐）**：

| 缺口 | 说明 |
| --- | --- |
| 审批路由缺失 | §7.5 承诺的 `/approvals*` 全部未挂载，但 `/me` 却声明 `capabilities.approvals=true`（声明与实现漂移） |
| 访客/审计查询缺失 | `/owner/guests`、`/owner/guests/{id}/messages`、`/owner/audit` 未挂载，审计数据已在写 |
| 只读能力外接缺失 | 简报/世界快照/记忆/天气等桌面能力**无 7891 只读端点** |
| SSE 事件类型受限 | `mobile_events` 仅允许 `message.created`/`request.updated`，无 `file.updated`/`approval.pending` |
| 目录授权 CLI 缺失 | `scripts/mobile_accounts.py` 无 directory grant 子命令 |

### 1.3 执行主线

```
服务端补缺（审批/审计/外接端点/CLI）
  → Flutter 客户端开发（认证→消息→文件→只读能力）
  → 双端真机验收（Android + iOS）
  → Cloudflare Tunnel 独立服务
  → 签名发布
  → 主控文档状态收口
```

---

## 2. Current State Analysis（现状分析）

### 2.1 桌面端近期改动与能力面（7890 API 共 233 端点）

近期（08-08~08-13）桌面端密集迭代：

| 模块 | 近期改动 |
| --- | --- |
| LLM 调用层 | Brain→LLMCaller 收敛、多 Key 轮询、余额显示、功能点面板 |
| 上下文记忆 P0-P3 | 热窗口轮次、通道感知注入、温层分桶、跨端时间线、多端存在提示、主动回忆 |
| 主动消息/推送 | 主动发图预算、生图候选去重、消息上限热更新 |
| 世界模拟 | 房间级定位（home_space 372 行）、对话移动意图、重庆迁移、百度地图 |
| 图片/视觉 | 三视图生图、POV 自拍、SiliconFlow 视觉技能、图片表达层次认知 |
| 简报 | 分层混合爬虫、GitHub trending、今日天象、全屏天气 |
| 文件/文档工具 | 文件整理/去重/过期清理（file_organizer）、文档写作（doc_writer） |
| 管理平台 | 统计看板、决策日志、回收站、记忆全量展示、Origin 守卫 |

### 2.2 7891 移动网关现状（21 条路由）

| 能力域 | 状态 | 说明 |
| --- | --- | --- |
| 认证与设备 | ✅ 完备 | login/refresh/logout/me/devices/revoke 全实现 |
| 聊天与请求 | ✅ 完备 | messages/requests/cancel/retry/events(SSE) 全实现 |
| 文件双向传输 | ✅ 代码完备 | 8 条路由，仅缺真机闭环 |
| SSE 事件 | ⚠️ 部分 | 仅 message.created/request.updated |
| 手机审批 | ❌ 缺失 | Phase 6 未开始 |
| 访客/审计 | ❌ 缺失 | 数据已写，无查询路由 |
| 限流 | ⚠️ 部分 | 仅登录 5/15min、上传 2 会话 |

### 2.3 移动端能力外接评估（价值排序）

基于桌面 API 面调研，**只读优先**外接（走 7891 白名单代理，绝不暴露 7890）：

| 档位 | 能力 | 端点 | 外接方式 |
| --- | --- | --- | --- |
| 首选（首版） | 简报 | `GET /api/brief/today` | 7891 只读代理 |
| 首选（首版） | 世界快照 | `GET /api/world/dashboard/snapshot` | 7891 只读代理 |
| 首选（首版） | 记忆档案 | `GET /api/memory/list` | 7891 只读代理 |
| 首选（首版） | 天气/位置 | `GET /api/weather/current` + `location/status` | 7891 只读代理 |
| 次选（二版） | 主动事件历史 | `GET /api/proactive/events` | 7891 只读代理 |
| 次选（二版） | 情绪/内在状态 | `GET /api/emotion/state` + `/history` | 7891 只读代理 |
| 次选（二版） | 待办/日历 | `GET /api/todos` + `/api/calendar/timeline` | 只读 + 受限 toggle |
| 次选（二版） | 统计看板 | `GET /api/stats/dashboard` + `/tokens` | 7891 只读代理 |
| **绝不外接** | shell/computer_control/permissions/system/env/config/self_evolve/skills/napcat | — | 严格隔离 |

---

## 3. Proposed Changes（建议改动）

### 3.1 服务端补齐（S0，Flutter 接入前置）

**3.1.1 审批路由 + 审计/访客查询（§7.5）**

- `core/mobile_approvals.py`（新）：包装现有审批源（`core/computer_control.py` 的 pending/approve/reject）为 owner-only 移动合同：
  - `GET /approvals`（pending 列表）
  - `GET /approvals/{id}`（详情）
  - `POST /approvals/{id}/challenge`（60 秒一次性挑战）
  - `POST /approvals/{id}/decision`（Keystore ECDSA 签名校验 → 执行 approve/reject）
- `core/mobile_gateway.py` 挂载：`GET /owner/guests`、`GET /owner/guests/{accountId}/messages`、`GET /owner/audit`（查询 `mobile_audit` 表，脱敏）
- **审批密钥跨设备策略**：ECDSA 密钥首次审批时生成并注册到设备；换机/撤设备后，新设备重新生成密钥，旧设备密钥随 `DELETE /devices/{id}` 级联作废——杜绝旧设备离线签名
- **一致性修复**：`/me` 的 `capabilities.approvals` 在审批路由未挂载前先置 `false`，避免声明与实现漂移；挂载后改回 `true`

**3.1.2 只读能力外接（7891 白名单代理）**

- `core/mobile_readonly.py`（新）：只读代理层，白名单转发到桌面 service 层（不经 7890 HTTP），**统一挂载于 `/api/mobile/v1/readonly/*` 版本体系**（与网关其他 v1 端点一致）：
  - `GET /readonly/brief`（今日简报）
  - `GET /readonly/world`（世界快照，复用 `world_simulation.get_snapshot` 的脱敏逻辑）
  - `GET /readonly/memory`（记忆四层档案，`LayeredMemory.list_by_user`）
  - `GET /readonly/weather`（天气 + 位置）
  - 二版可加：`/readonly/proactive`、`/readonly/emotion`、`/readonly/stats`、`/readonly/todos`
- 约束：**只读，无 POST/PUT/DELETE 写操作外接**；遵循主控文档 §3.1 强制隔离原则（不代理任意 `/api/*` 路径，走 service 适配器）
- **服务端 API 向后兼容契约（S0 起对全部 v1 端点生效）**：
  1. 只增不改：新增字段必须可选（带默认值），**不得修改既有字段语义/类型/枚举值**
  2. 删前弃用：删除字段/端点必须先经一版弃用期（响应保留字段 + 文档标注 deprecated）
  3. 兼容信号：破坏性变更必须升 `apiVersion`（v2）而非原地改 v1；客户端 OpenAPI 重新生成时对 v1 契约 diff 为**零破坏**视为门禁

**3.1.3 SSE 事件扩展 + 限流 + CLI**

- `core/migrations/__init__.py`：`mobile_events` 表 CHECK 约束放开 `file.updated`/`approval.pending`，补对应触发器与 `_event_payload` 分支
  - **迁移方式**：SQLite 修改 CHECK 需重建表——采用「新建 `mobile_events_v2`（含新事件类型）+ 复制既有行 + 原子 `DROP/RENAME` 替换 + 备份 `mobile_events_bak` 快照」，失败回滚到旧表；不原地 ALTER
- 限流补齐（§12.2）：发消息 10/min 突发 3、认证 API 120/min、SSE 每设备 2 并发
- `scripts/mobile_accounts.py`：新增 `grant-directory`/`list-directory-grants`/`disable-directory-grant`/`enable-directory-grant` 4 个子命令（§8.2 合同缺口）

**3.1.4 测试**

- `tests/test_mobile_approvals.py`、`tests/test_mobile_readonly.py`、`tests/test_mobile_accounts_cli.py` 新增
- 网关路由白名单测试同步更新（新增路由加入 allowlist 断言）

### 3.2 Flutter 客户端开发（主要工作量）

#### 3.2.0 工程基线

- **版本号设定（已锁定）**：移动端首个正式版本定为 **`0.1.0-Beta.1`**，`pubspec.yaml` `version: 0.1.0+1`（`0.1.0` 为语义化版本，`1` 为 build number）；Android `applicationId = top.etta.aerie.mobile` 的 `versionName` 跟随 `0.1.0-Beta.1`，后续迭代按 `0.1.0-Beta.x → 0.1.0 → 0.x.0` 递增
- Flutter SDK + Dart，`flutter create aerie_mobile`，包名 `top.etta.aerie.mobile`（保留 aeries 前缀）
- 目标：Android 8+ / iOS 15+；CI 双端构建
- **选型锁定（评估确认，S1 即定，不得延后）**：
  - 状态管理：**Riverpod 3.x**（编译期安全 + 内置 DI + 生成器；不用 Provider，不用 Bloc）
  - 本地数据库：**drift**（类型安全 + 响应式 `watch()` + 内置迁移；不用裸 sqflite）
  - API 客户端：**openapi_sdk_gen 代码生成**（后端 FastAPI 已有 OpenAPI schema，DTO 与客户端自动生成，合同变更编译期暴露）
- 核心依赖（版本约束锁定，CI 校验 `pubspec.lock` 提交状态，确保构建可复现）：
  - `dio: ^5.9.0`（HTTP + 拦截器 + 进度回调 + `ResponseType.stream` 流式）
  - `flutter_secure_storage: ^9.2.0`（令牌）+ `local_auth: ^2.3.0`（审批生物识别，指纹/人脸）
  - `flutter_riverpod: ^3.0.0` + `riverpod_annotation` + `riverpod_generator`（状态管理）
  - `drift: ^2.28.0` + `drift_flutter: ^0.2.0` + `sqlite3_flutter_libs`（本地消息缓存）
  - `openapi_sdk_gen` + `retrofit: ^4.1.0` + `json_serializable: ^6.9.0` + `build_runner`（API 代码生成）
  - `flutter_foreground_task: ^8.0.0`（大文件传输前台服务，保活）
  - `cached_network_image: ^3.4.0`（消息图片懒加载缓存）
  - `file_picker: ^8.1.0`（SAF 文件选择）+ `open_filex: ^4.5.0`（下载后打开，跨端优于 url_launcher）
  - `path_provider` + `crypto: ^3.0.0`（SHA-256）+ `connectivity_plus: ^6.0.0`（网络状态检测）
- 工程质量门槛（S1 起生效，全部进入 CI）：
  - `flutter analyze` 零告警（`flutter_lints` + `very_good_analysis`）
  - `dart format --set-exit-if-changed` 通过
  - 测试覆盖率：仓库层 ≥80%、Widget ≥60%（`flutter test --coverage` 度量）
  - CI（GitHub Actions 双端矩阵）：analyze → test → build apk debug → build ipa（模拟器签）
  - **CI 签名与密钥注入**：真实签名 keystore/证书不上传仓库，经 GitHub Actions `secrets` 注入（ANDROID_KEYSTORE_B64 / ANDROID_KEYSTORE_PASSWORD / iOS 证书 P12 + 密码）；CI 仅用于构建校验与模拟器签，**真机发布包在本地用仓库外 keystore 签名**（§3.4）

#### 3.2.1 网络层（`lib/data/remote/`）

- **API 客户端由 OpenAPI 代码生成**：从后端 `openapi.json`（FastAPI 自带）用 `openapi_sdk_gen` 生成 DTO + Retrofit 接口（auth/chat/file/readonly 四组），**不手写 DTO**；服务端改 API 后重新生成，编译期暴露破坏性变更
- `mobile_gateway_client.dart`：API 客户端封装（baseUrl 配置：Debug `http://127.0.0.1:7891`，Release `https://aerie.etta.top`；**真机 Debug 用 `adb reverse tcp:7891` 或电脑局域网 IP**，模拟器才可直接 127.0.0.1）
- 鉴权拦截器：401 单次刷新互斥重试（沿用 Android 版已验证逻辑）；dio `ResponseType.stream` 用于 SSE 与下载
- 错误映射：服务端稳定错误码 → Dart 异常类型（Sealed class `ApiResult<T>`），UI 层 switch 穷尽处理

#### 3.2.2 本地存储（`lib/data/local/`）

- `auth_store.dart`：flutter_secure_storage 存令牌 + 账号元数据；**边界约束**——Android manifest `allowBackup=false` 排除令牌、iOS Keychain 迁移语义（`kSecAttrAccessible` 配置）
- `chat_database.dart`：drift 表（消息/请求/传输状态；accountId 隔离、messageOrder 排序、待确认队列），用 drift 响应式 `watch()` 驱动 UI，内置 schema migration
- `file_transfer_store.dart`：上传/下载进度状态（续传点）
- **数据迁移决策（已确认）**：首版**不做原生 Kotlin Room → drift 的数据迁移**，不做旧数据保留/搬运。首次启动检测到旧 App 数据即清空重建，历史消息从服务端全量重同步（服务端为唯一真相源，`/messages` 游标分页拉取）。升级路径简化为「清库 → 重新登录 → 重同步」，不引入迁移兼容层（遵循"不保留向后兼容"项目纪律）

#### 3.2.3 仓库层（`lib/data/repository/`）

- `auth_repository.dart`：登录流程状态机（含配对码交互）+ Riverpod `AsyncNotifier`
- `chat_repository.dart`：消息分页、发送、取消、重试、SSE 增量
- `file_repository.dart`：分块上传（4MB、逐块 SHA-256、断点续传）、Range 下载续传；大文件传输期间拉起 `flutter_foreground_task` 前台服务保活
- `readonly_repository.dart`：只读能力缓存（Riverpod `FutureProvider` + 过期刷新）

#### 3.2.4 UI 层（`lib/ui/`）

- **目录组织采用 feature-first**（与数据层 repository 互补）：
  - `lib/features/auth/`（auth_screen、auth_notifier）
  - `lib/features/chat/`（chat_screen、chat_notifier、message_bubble）
  - `lib/features/files/`（file_screen、transfer_card）
  - `lib/features/brief/`（brief_screen）、`lib/features/world/`（world_screen）、`lib/features/memory/`（memory_screen）
  - `lib/features/settings/`（settings_screen）
  - `lib/ui/theme/`（设计令牌）、`lib/ui/widgets/`（跨 feature 共享组件）
- 每个 feature 内部：`widgets/` + `notifier/`（Riverpod）+ `models/`，UI 不直接触网络/数据库，经 repository
- 主题沿用伊塔风格（软粉色圆角按钮、小字号、内置图标），保持与桌面视觉一致

#### 3.2.5 文件双向传输细节

- 上传：file_picker 选择 → 计算整文件 SHA-256（`crypto` 分块流式，避免整读进内存）→ 创建会话 → 4MB 分块 PUT（`X-Part-SHA256`）→ complete
- 断点续传：`GET /files/uploads/{id}` 读 uploadedParts 跳过已传块；进程/网络中断恢复
- 下载：`GET /files/{id}/content` 带 `Range` 头，dio `ResponseType.stream` 落盘，记录已下字节，断点续传
- 传输保活（**分平台差异**）：Android 用 `flutter_foreground_task` 前台服务 + 隐私通知（只显示状态不显示文件名，沿用桌面通知隐私合同）；**iOS 无通用前台服务机制**——长传输期间提示用户保持前台，配合 `BGTaskScheduler`（`workmanager_ios`/`background_fetch`）做断点重连，不接受 iOS 后台无限保活
- 聊天附件：完成后 `fileIds` 填入 requests 提交，支持"文本+附件"
- 消息图片：`cached_network_image` 懒加载 + 磁盘缓存，列表滑动不卡顿

#### 3.2.6 SSE 事件流实现（评估确认方案）

- **基于 dio `ResponseType.stream` 自研 SSE 状态机**（不用 web_socket_channel——SSE 是 HTTP 单向流非 WebSocket，也不用第三方 SSE 包，贴合服务端既有 `evt_<seq>` 游标合同）：
  - 连接：`GET /events` + `Last-Event-ID` 头续传（服务端已支持）
  - 解析：UTF-8 流按 `\n\n` 切帧，`data:`/`id:` 字段解析，忽略 `:` 注释行（心跳）
  - 重连：指数退避（1s→2s→4s→8s→30s 封顶）+ 随机抖动；网络恢复（`connectivity_plus`）立即重连
  - 去重：按 `event_id` 去重（重连回放时跳过已处理事件）
  - 状态暴露：`SseController` 暴露 `connectionHealth`（connected/reconnecting/disconnected）供 AppBar 连接状态胶囊渲染

#### 3.2.7 测试

- Flutter 单测：`test/` 下 auth/chat/file 各仓库 Mock（dio 拦截器 mock + drift 内存数据库 `NativeDatabase.memory()`）
- Widget 测试：登录流、聊天列表、文件进度
- **双端真机**：Android vivo V2516A + iOS（待确认设备）+ 局域网/ADB reverse 验收
- 覆盖率门槛：仓库层 ≥80%、Widget ≥60%；CI 用 `flutter test --coverage` + `lcov` 校验，不达标构建失败

#### 3.2.8 平台安全配置（评估确认新增）

- **Android**：`AndroidManifest` 加 `android:allowBackup="false"`（令牌不进云备份）；`network_security_config.xml` 允许 Debug 构建访问 `http://127.0.0.1` 与局域网明文（Release 仅 HTTPS，`cleartextTrafficPermitted=false`）
- **Android 14+ 前台服务类型**：`flutter_foreground_task` 需声明 `FOREGROUND_SERVICE_DATA_SYNC` 权限 + `foregroundServiceType="dataSync"`，并在 Android 14+ 运行时申请 `FOREGROUND_SERVICE_DATA_SYNC` 权限；targetSdk 升级时同步校验
- **iOS**：`Info.plist` 配置 ATS 例外——`NSAllowsLocalNetworking`（Debug 局域网），Release 保持 HTTPS 强制；`NSLocalNetworkUsageDescription` 提示权限用途
- **生物识别**：审批场景用 `local_auth`（`BiometricPrompt`），失败降级设备锁屏凭据，不回落明文

#### 3.2.9 移动端日志规范（评估确认新增）

- **分级**：debug（请求/响应摘要）、info（登录/传输完成）、warn（重试/降级）、error（异常）；线上默认 warn 起
- **脱敏**：禁止记录访问/刷新令牌、配对码、密码、文件真实路径、签名私钥；文件名/账号名需打码
- **落盘轮转**：`path_provider` 应用文档目录 `logs/`，单文件 ≤5MB、保留最近 3 份；不写入系统 console（避免 Xcode/Logcat 泄漏）
- **可观测**：关键链路（登录/SSE 重连/分块上传失败/审批签名失败）打结构化日志，配合调试期 `flutter run --verbose` 定位

#### 3.2.10 UI 设计规格（移动端设计系统）

> 视觉语言延续桌面端「伊塔」主题：柔和温暖、现代简约、克制的留白。遵循用户既定偏好——**内置图标库（不用 emoji）、小字号非粗体、圆角按钮 + 柔和粉色系（不用纯黑按钮）**、与主程序主题一致。

**① 设计令牌（Design Tokens）**

| 令牌 | 亮色 | 暗色 | 用途 |
| --- | --- | --- | --- |
| `color.primary` | `#F5A3B7`（柔和玫瑰粉） | `#E77F9B` | 主按钮、选中态、进度条 |
| `color.primaryPressed` | `#E77F9B` | `#D96B88` | 按压态、渐变终点 |
| `color.primarySoft` | `#FCE4EC` | `#3A222B` | 浅粉底、选中气泡底 |
| `color.background` | `#FDF8F6`（暖白） | `#241C1F` | 全局背景 |
| `color.surface` | `#FFFFFF` | `#2F2529` | 卡片/导航栏 |
| `color.border` | `#F0E4E4` | `#3E3338` | 分隔线、描边 |
| `color.textPrimary` | `#3D2F35`（暖深灰） | `#F5ECEE` | 正文（不用纯黑） |
| `color.textSecondary` | `#8A7B82` | `#A89A9E` | 次要文字 |
| `color.success/error/warning/info` | `#7BC59B`/`#E87C7C`/`#E8B76F`/`#7FA8D9` | 同左提亮 10% | 状态语义色 |

**字号阶梯（小字号偏好，正文非粗体）**：Display 28 → Title 22 → Section 17 → **Body 15（正文）** → Caption 13 → Micro 11；常规 `FontWeight.w400/w500`，仅标题级 `w600`。

**间距/圆角**：间距 4 的倍数（4/8/12/16/20/24/32/48）；卡片圆角 16、输入框 12、按钮胶囊 999、徽章 999。图标统一 `Icons.*` 内置库。

**② 信息架构与导航**

```
未登录 ──→ AuthScreen（登录/配对码）
已登录 ──→ MainShell（底部导航 5 Tab）
  ├─ 聊天 chat      Icons.chat_bubble_outline / 选中填充
  ├─ 简报 brief     Icons.newspaper
  ├─ 世界 world     Icons.home
  ├─ 文件 file      Icons.folder_open
  └─ 我的 settings  Icons.person_outline
```

- 底部导航条：白底（`surface`）、顶部 1px `border`、选中项 `primary` + 图标填充 + 胶囊背板（`primarySoft`），未选中 `textSecondary`；高度 64dp
- 顶部 AppBar：页面标题（Section 17 非粗体）左对齐 + 右侧**连接状态胶囊**（SSE 在线=`success` 绿点+「在线」，离线=`textSecondary` 灰点+「离线」，点击可重连）

**③ 页面级设计**

| 页面 | 布局要点 |
| --- | --- |
| **AuthScreen** | 暖白背景，顶部伊塔圆形头像（persona avatar）+ 问候语（Body 15 次色）；用户名/密码输入框（圆角 12、浅灰底、聚焦 `primary` 描边）；新设备显示 8 位配对码**分段输入**（4+4）；主按钮胶囊 `primary` 白字，登录中禁用 + spinner |
| **ChatScreen** | 对方（伊塔）左对齐白气泡 + 头像，用户右对齐 `primarySoft` 底、`primaryPressed` 文字气泡；圆角 16（近端 4），max-width 75%；时间戳 Micro 次色；附件消息=文件卡（图标+名+大小）；输入栏胶囊 + 附件按钮（Icons.attach_file）+ 圆形发送钮；任务状态=发送中/已取消/重试 徽章；气泡 12 间距 |
| **BriefScreen** | 顶部日期横幅卡 → 问候语卡 → 逐日天气横滚小卡（温度+图标）→ 新闻列表（来源徽章 + 标题 + 两行摘要）→ GitHub 项目卡 → 趋势标签（新增/升温/持续/回落 语义色） |
| **WorldScreen** | 只读状态卡：房间位置 + 时段 + 天气（温度+图标）；情绪状态=图标 + **强度进度条**（`primary`）；房间/位置卡；无任何写操作入口 |
| **FileScreen** | 文件列表行卡（类型图标 + 文件名 + 大小 + 时间 + 来源徽章：授权目录/Inbox/Outbox）；右上「上传」胶囊钮；**传输进度卡**=文件图标 + `primary` 进度条 + 百分比 + 暂停/取消；空态=居中图标 + 次色文案 |
| **MemoryScreen** | 分层 Tab（transient/short/long/permanent，胶囊切换）；记忆卡=时间 + 内容摘要，只读 |
| **SettingsScreen** | 账号信息卡（头像/用户名/角色）→ 服务器地址 → 设备管理（列表 + 撤销钮）→ 主题跟随系统（亮/暗）→ 关于（版本 `0.1.0-Beta.1`） |

**④ 组件状态规范**

- **Button**：default（`primary` 白字）/ pressed（`primaryPressed` 微下沉）/ disabled（50% 不透明）/ loading（spinner 替代文字），高度 48dp、圆角胶囊
- **Input**：default（浅灰底）/ focused（`primary` 1.5px 描边 + 阴影）/ error（`error` 描边 + 底部提示小字）/ disabled（次色 40%）
- **Card**：default（白底 16 圆角）/ pressed（轻微下沉 1dp）/ 选中（`primarySoft` 底 + `primary` 描边）
- **Chip/徽章**：默认 `surface` 底次色字 / 选中 `primarySoft` 底 `primaryPressed` 字

**⑤ 无障碍与可访问性**

- 正文 `textPrimary` 对 `background` 对比度 ≥ 4.5:1；次要文字 ≥ 3:1
- 可点击目标 ≥ 48×48dp；焦点可见（`primary` 描边）
- 字号跟随系统缩放；暗色模式随系统自动切换

**⑥ 实现备注**

- 设计令牌落为 `lib/ui/theme/app_colors.dart` + `app_typography.dart`，组件用 Flutter `ThemeExtension` 注入
- 页面骨架 `Scaffold` + `NavigationBar`；列表用 `ListView.builder`（懒加载）
- 图表类（天气/情绪/趋势）优先用轻量自绘 `CustomPaint`，不引入重型图表库

### 3.3 Cloudflare Tunnel（独立服务，用户已确认）

1. 下载 `cloudflared` 到用户目录（不进 Git）
2. `cloudflared tunnel login`（需用户浏览器 OAuth 授权）
3. 创建命名隧道：`aerie.etta.top → http://127.0.0.1:7891`（config.yml 放用户目录）
4. `cloudflared service install` 注册为 Windows 服务，验证重启自恢复
5. 验收：公网 health 200、7890 高权限路径公网 404、双端真机经公网登录

### 3.4 签名发布

1. 创建仓库外 keystore（离线备份，用户确认位置）
2. Flutter `build apk --release` 签名 + iOS 签名（开发者账号，待确认），**产出版本 `0.1.0-Beta.1`**（`versionName` 与 `pubspec` 保持一致）
3. 真机覆盖安装验证数据保留
4. `AERIE_DISABLE_QQ=true` 全链路闭环
5. 主控文档 Evidence 收口
- **签名一致性硬约束**：`0.1.0-Beta.1` 起所有升级与回滚包**必须用同一 keystore/证书签名**（换签名 → 覆盖安装失败、数据隔离），密钥丢失即失去升级能力——keystore 创建后立即离线双备份，密码不进文档/Git

### 3.5 文档

- **新 Flutter 项目文档**：新建 `flutter-mobile/README.md`（定死，不再二选一）记录架构分层、选型、命令（analyze/test/build）、验收证据索引；原生 `android-client/docs/` 不再新增
- 主控文档 `Aerie_Android_Companion_Master_Plan.md` 状态同步更新

---

## 4. Assumptions & Decisions（假设与决策）

| # | 决策/假设 | 依据 |
| --- | --- | --- |
| D1 | 服务端 7891 文件/聊天/认证 API 视为可用基线，Flutter 直接对接 | 08-10 实测代码完整、10 项文件测试通过 |
| D2 | 移动端功能边界：消息同步 + 文件/图片传输 + 只读能力外接；智能推理全在电脑 | 用户确认的定位边界 |
| D3 | Flutter 取代原生 Kotlin，Android + iOS 一套代码；桌面 Electron 不动 | 用户"直接重写"决策 |
| D4 | 只读能力外接走 7891 白名单代理，绝不暴露 7890 写操作 | §3.1 强制隔离原则 |
| D5 | 审批路由在 Flutter 审批 UI 开发前由服务端补齐，`capabilities.approvals` 修正 | 声明/实现漂移修复 |
| D6 | Cloudflare Tunnel 采用独立 Windows 服务方式，不进 exe | 用户已确认 |
| D7 | 签名密钥/密码由用户线下保管，Agent 只生成命令 | 主控文档 §11 |
| D8 | 移动端首版版本号锁定 `0.1.0-Beta.1`（Android versionName / iOS CFBundleShortVersionString 一致） | 用户设定 |
| D9 | 移动端技术选型锁定：Riverpod 3.x（状态管理）+ drift（本地库）+ openapi_sdk_gen（API 代码生成）；SSE 用 dio 流式自研状态机 | 生产级评估确认（2026-08-10） |
| D10 | iOS 真机与开发者账号为可选项，若资源不足先交付 Android 签名版 | 资源条件约束 |
| D11 | 服务器仓库运行态文件与无关提交不在本计划提交范围 | §10.6 仓库边界 |
| D12 | **消息对话数据首版不做保留与迁移**：不清 Room→drift 数据，首次启动清库 + 服务端全量重同步（服务端为唯一真相源） | 用户确认 |

---

## 5. Priority & Timeline（优先级与时间节点）

截止 2026-09-01（今天 08-10，约 3 周）。文件→Tunnel→发布：

| 阶段 | 内容 | 计划窗口 | 依赖 | 里程碑验收 |
| --- | --- | --- | --- | --- |
| **S0 服务端补齐** | 审批路由、只读外接、SSE 扩展、限流、CLI | 08-10 ~ 08-15 | 无 | 新增测试 + 既有回归 632 全过 |
| **S1 Flutter 基线** | 工程创建、网络层、认证、本地存储 | 08-15 ~ 08-20 | S0 | Flutter 单测（auth 流程）通过 |
| **S2 Flutter 消息/文件** | 聊天、SSE、分块上传下载、附件 | 08-20 ~ 08-25 | S1 | Widget 测试 + 文件仓库单测通过 |
| **S3 只读能力 UI** | 简报/世界/记忆/天气 4 屏 | 08-25 ~ 08-27 | S0+S1 | 真机只读接口调通 |
| **S4 双端真机验收** | Android + iOS 登录/消息/文件/只读 | 08-27 ~ 08-29 | S2+S3+真机 | 双端 instrumented + 服务器一致 |
| **S5 Cloudflare Tunnel** | cloudflared、命名隧道、Windows 服务 | 08-29 ~ 08-31 | S4 + 用户 OAuth | aerie.etta.top 可达、7890 不可达 |
| **S6 签名发布** | keystore、双端签名 APK/IPA、QQ 独立 | 08-31 ~ 09-01 | S5 | 签名验收、数据保留、闭环 |
| **S7 收口缓冲** | 主控文档 Evidence、风险清零 | 09-01 | S6 | 文档一致 |

**资源分配**：
- Agent：S0-S3、S5-S7 代码与验证；S4 真机指令执行
- 用户：S4/S6 真机接入（Android + iOS）；S5 Cloudflare OAuth；S6 keystore 备份；iOS 开发者账号（若需）

---

## 6. Risk Register（风险与应对）

| # | 风险 | 概率/影响 | 应对 |
| --- | --- | --- | --- |
| R1 | Flutter 重写 + 服务端补缺 3 周工期偏紧 | 高/高 | 只读能力 S3 可砍至简报单屏；审批 UI 移到二版；核心是消息+文件 |
| R2 | iOS 真机/开发者账号不可用 | 中/中 | D10：先交付 Android 签名版，iOS 保留 Flutter 代码可编译 |
| R3 | Cloudflare OAuth 阻塞 S5 | 高/中 | S5 排后；用户延迟时先做 S6 中不依赖公网部分 |
| R4 | 双端真机窗口不足 | 中/高 | 客户端阶段 Flutter 单测保底；真机压缩为两次集中验收 |
| R5 | 大文件上传后台冻结（双端） | 中/中 | 前台服务/通知保持活动；续传兜底 |
| R6 | 服务端只读外接被误扩大成写暴露 | 中/高 | 白名单严格只读；路由 allowlist 测试强制约束 |
| R7 | 审批声明/实现漂移导致客户端误渲染 | 中/低 | S0 先行修正 capabilities |
| R8 | ~~Flutter 本地库选型拖慢~~（已解决：Riverpod + drift + openapi_sdk_gen 在 S1 锁定） | — | — |
| R9 | OpenAPI 代码生成产物与手写拦截器冲突 | 中/低 | 生成物独立目录 `lib/gen/`，手写层在其上封装，build_runner 增量重建 |
| R10 | iOS ATS/Debug 明文被误带入 Release | 低/高 | 平台配置按 buildType 区分（debug 允许明文，release 强制 HTTPS），S4 双端验收专项检查 |
| R11 | 大文件分块 SHA-256 流式计算内存峰值 | 低/中 | 分块流式读（1MB 缓冲），不整读文件 |

---

## 7. Verification（验证方案）

每个阶段执行后填写门禁记录（沿用主控文档 §16 Evidence 风格，追加至本计划 `flutter-mobile/README.md` 验收索引）：

| 阶段 | PASS/FAIL | 证据摘要（命令输出/测试数/真机记录） | 日期 |
| --- | --- | --- | --- |
| S0 | ✅ PASS | 新增 test_mobile_approvals/readonly 各5项、CLI lifecycle 1项、网关白名单32路由全过；完整 tests 回归 exit 0；008 迁移新事件类型可写 | 2026-08-10 |
| S1 | ☐ | | |
| S2 | ☐ | | |
| S3 | ☐ | | |
| S4 | ☐ | | |
| S5 | ☐ | | |
| S6 | ☐ | | |
| S7 | ☐ | | |

1. **S0**：`python -m pytest tests/test_mobile_approvals.py tests/test_mobile_readonly.py tests/test_mobile_accounts_cli.py tests/test_mobile_files.py -q` 全过；`pytest tests/test_mobile_gateway.py` 路由白名单含新增路由；完整回归 632/632
2. **S1-S3**：`flutter analyze` 零告警；`dart format --set-exit-if-changed` 通过；`flutter test --coverage` 达标（仓库 ≥80%、Widget ≥60%）；`flutter build apk --debug` 成功；OpenAPI 生成物 `lib/gen/` 与后端 schema 一致
3. **S4**：Android vivo + iOS 真机：登录/配对/消息双向/50MB 文件上传续传/Range 下载/只读简报世界；Room 与服务器一致；**专项**——Debug 明文仅开发可用、Release HTTPS 强制、SSE 断网重连回放去重
4. **S5**：`Resolve-DnsName aerie.etta.top` 返回 CF IP；公网 health 200；7890 公网 404；`Get-Service cloudflared` Running；重启自恢复
5. **S6**：双端签名包验收；APK 敏感字符串零命中；覆盖安装数据保留；`AERIE_DISABLE_QQ=true` 闭环；**性能 KPI**——Android 冷启动 <2s、APK 体积 <100MB、消息列表 60fps（`flutter run --profile` 实测）
6. **S7**：主控文档 Evidence 追加；文档 UTF-8/Markdown/敏感扫描复核

---

## 8. 变更纪律

- 公共 API、端口、权限、目录边界、文件类型的任何变更，先更新主控文档决策日志再改实现
- 每阶段先跑定向测试再跑相关回归；数据库变更必须备份 + dry-run
- 不把调试令牌、测试账号、真实目录、Cloudflare 凭据、签名密码写入源码/测试/日志/文档
- Flutter 与原生 Kotlin 并存期间，原生代码不删（回滚保险），新功能只入 Flutter 分支

---

## 9. 任务门户体系（Task Portals · 执行层）

> 本体系将 §3-§5 的执行内容分解为可勾选、可并联、可追踪的任务门户。每个门户含：**开发目标 / 技术要求 / 时间节点 / 负责人 / 子任务清单**。每完成一项即在对应 `[ ]` 打勾并更新状态；阶段结束填写 §7 门禁 PASS/FAIL。
>
> **负责人约定**：`Agent` = 当前 Agent 主执行；`Agent∥` = 可派发并联子 agent（互不依赖的分支）；`User` = 需用户配合（真机/OAuth/密钥/验收）。
>
> **多级审查机制**：
> - **L1 自检**：每子任务完成即跑其验证命令（§7 对应项），失败不勾选
> - **L2 阶段门禁**：每个门户全绿后，在 §7 表填 PASS/FAIL + 证据摘要
> - **L3 集成回归**：S0/S2/S4/S6 完成后跑完整回归（服务端 632 / 客户端覆盖率），防并联分支互相破坏
> - **L4 用户验收**：S4/S5/S6 关键节点由 User 真机/公网确认后，才进入下一阶段

---

### 9.0 门户总览

| 门户 | 内容 | 计划窗口 | 负责人 | 状态 |
| --- | --- | --- | --- | --- |
| P-S0 | 服务端补齐（审批/审计/只读/SSE/限流/CLI） | 08-10 ~ 08-15 | Agent∥（3 路并联） | ✅ |
| P-S1 | Flutter 基线（工程/选型/网络/认证/存储） | 08-15 ~ 08-20 | Agent∥（2 路并联） | ⬜ |
| P-S2 | 消息/文件（聊天/SSE/分块传输/附件） | 08-20 ~ 08-25 | Agent | ⬜ |
| P-S3 | 只读能力 UI（简报/世界/记忆/天气） | 08-25 ~ 08-27 | Agent∥（2 路并联） | ⬜ |
| P-S4 | 双端真机验收 | 08-27 ~ 08-29 | Agent + **User**（真机） | ⬜ |
| P-S5 | Cloudflare Tunnel | 08-29 ~ 08-31 | Agent + **User**（OAuth） | ⬜ |
| P-S6 | 签名发布 | 08-31 ~ 09-01 | Agent + **User**（keystore） | ⬜ |
| P-S7 | 收口缓冲 | 09-01 | Agent | ⬜ |

---

### 9.1 P-S0 服务端补齐

**开发目标**：补齐 7891 网关缺失能力，为 Flutter 接入提供完整合同（§3.1）。
**技术要求**：FastAPI + 现有 `core/mobile_*` 模块 + `core/migrations/__init__.py`；遵循 §3.1 强制隔离（只读外接不代理 7890）。
**时间节点**：08-10 ~ 08-15（依赖：无）。
**负责人**：`Agent∥`（三路并联：T0.1 / T0.2 / T0.3 互不依赖）。

- [x] **T0.0 前置核对（L1）**：确认 `tests/test_mobile_gateway.py` 现有 21 条路由白名单、`core/computer_control.py` 审批 pending/approve/reject 签名、`mobile_audit` 表列结构。产出：现状核对记录。

- [x] **T0.1 审批 + 审计/访客路由（并联支路 A）**
  - [x] 新建 `core/mobile_approvals.py`：包装 `ComputerController`，实现 4 路由（§3.1.1）
  - [x] `mobile_gateway.py` 挂载 `GET /owner/guests`、`GET /owner/guests/{accountId}/messages`、`GET /owner/audit`
  - [x] 审批密钥跨设备：`DELETE /devices/{id}` 级联作废审批密钥（§3.1.1）
  - [x] `/me` capabilities 一致性：审批路由未就绪前 `approvals=false`，就绪后 `true`
  - [x] L1 自检：`pytest tests/test_mobile_approvals.py -q` 全过

- [x] **T0.2 只读外接代理（并联支路 B）**
  - [x] 新建 `core/mobile_readonly.py`：白名单代理（§3.1.2），挂载 `/api/mobile/v1/readonly/{brief,world,memory,weather}`
  - [x] 复用 `world_simulation.get_snapshot` 脱敏逻辑 / `LayeredMemory.list_by_user`
  - [x] 约束校验：无 POST/PUT/DELETE 外接
  - [x] L1 自检：`pytest tests/test_mobile_readonly.py -q` 全过

- [x] **T0.3 SSE 扩展 + 限流 + CLI（并联支路 C）**
  - [x] `mobile_events` 表重建（`_v2` + 复制 + 原子替换 + `_bak` 备份）放开 `file.updated`/`approval.pending` + 触发器 + `_event_payload` 分支（§3.1.3）
  - [x] 限流补齐：发消息 10/min 突发 3、认证 API 120/min、SSE 每设备 2 并发
  - [x] `scripts/mobile_accounts.py` 新增 4 个 directory grant 子命令
  - [x] L1 自检：`pytest tests/test_mobile_accounts_cli.py tests/test_mobile_files.py -q` 全过

- [x] **T0.4 集成回归（L3）**：路由白名单测试含新增路由；完整回归通过（exit 0）；§7 S0 门禁填 PASS

---

### 9.2 P-S1 Flutter 基线

**开发目标**：建立可构建、可测试的 Flutter 双端工程 + 认证闭环 + 本地存储（§3.2.0-3.2.3）。
**技术要求**：Flutter/Dart；Riverpod 3.x + drift + openapi_sdk_gen（D9 锁定）；版本约束见 §3.2.0。
**时间节点**：08-15 ~ 08-20（依赖：P-S0）。
**负责人**：`Agent∥`（两路并联：T1.2 网络层 / T1.3 存储层 互不依赖，均在 T1.1 骨架就绪后启动）。

- [ ] **T1.1 工程骨架**
  - [ ] `flutter create aerie_mobile`，包名 `top.etta.aerie.mobile`，`pubspec.yaml version: 0.1.0+1`
  - [ ] 按 §3.2.0 添加依赖（锁定版本）+ `flutter_lints`/`very_good_analysis`
  - [ ] 建 `lib/features/*` + `lib/ui/theme|widgets` + `lib/gen/` 目录骨架
  - [ ] 平台安全配置落地（§3.2.8）：Android `allowBackup=false` + `network_security_config`（debug 明文/release HTTPS）+ `FOREGROUND_SERVICE_DATA_SYNC` 前台服务类型；iOS `Info.plist` ATS 例外 + `NSLocalNetworkUsageDescription`
  - [ ] 日志规范落地（§3.2.9）：分级（debug/info/warn/error）+ 脱敏 + 落盘轮转（`logs/` ≤5MB × 3 份）
  - [ ] L1 自检：`flutter analyze` 零告警；`flutter test` 默认测试通过

- [ ] **T1.2 网络层（并联支路 A）**
  - [ ] 后端 `openapi.json` → `openapi_sdk_gen` 生成 `lib/gen/`（auth/chat/file/readonly）
  - [ ] `mobile_gateway_client.dart`：baseUrl 策略（Debug 127.0.0.1 / Release https://aerie.etta.top）
  - [ ] 鉴权拦截器（401 单次刷新互斥重试）+ `ApiResult<T>` 错误映射
  - [ ] L1 自检：网络层单测（MockWebServer/dio 拦截器 mock）通过

- [ ] **T1.3 本地存储（并联支路 B）**
  - [ ] `auth_store.dart`（flutter_secure_storage + allowBackup 排除）
  - [ ] `chat_database.dart`（drift 表 + schema migration）
  - [ ] `file_transfer_store.dart`（续传点）
  - [ ] L1 自检：drift 内存库 `NativeDatabase.memory()` 单测通过

- [ ] **T1.4 认证闭环 + 集成（L2/L3）**
  - [ ] `auth_repository.dart`（登录状态机 + 配对码）+ `auth_screen.dart`
  - [ ] 仓库层覆盖率 ≥80%、Widget ≥60% 校验
  - [ ] §7 S1 门禁 PASS/FAIL

---

### 9.3 P-S2 消息 / 文件

**开发目标**：聊天双向 + SSE 实时 + 分块文件传输 + 附件（§3.2.4-3.2.6）。
**技术要求**：dio 流式 SSE 状态机；4MB 分块 + SHA-256 + Range 续传；`flutter_foreground_task` 保活。
**时间节点**：08-20 ~ 08-25（依赖：P-S1）。
**负责人**：`Agent`（串行主线，任务间强依赖）。

- [ ] **T2.1 聊天核心**
  - [ ] `chat_repository.dart`：分页 / 发送 / 取消 / 重试 / 待确认队列
  - [ ] `chat_screen.dart` + `message_bubble.dart`（附件卡 + 任务状态徽章）
  - [ ] L1 自检：聊天仓库单测 + Widget 测试通过

- [ ] **T2.2 SSE 状态机（§3.2.6）**
  - [ ] `SseController`：dio 流式解析 / Last-Event-ID / 指数退避+抖动 / 去重 / connectionHealth
  - [ ] 接入 AppBar 连接状态胶囊
  - [ ] L1 自检：SSE 断线重连回放去重单测通过

- [ ] **T2.3 文件双向传输**
  - [ ] `file_repository.dart`：分块上传（流式 SHA-256）/ Range 下载 / 断点续传
  - [ ] `file_screen.dart`：列表 / 上传入口（file_picker）/ 传输进度卡 / 下载打开
  - [ ] 传输保活：Android 前台服务 / iOS 前台提示（§3.2.5 分平台）
  - [ ] L1 自检：文件仓库单测（MockWebServer）通过

- [ ] **T2.4 附件打通 + 集成（L2/L3）**
  - [ ] 上传完成 `fileIds` 填入 requests（文本+附件）
  - [ ] `cached_network_image` 图片懒加载
  - [ ] §7 S2 门禁 PASS/FAIL

---

### 9.4 P-S3 只读能力 UI

**开发目标**：简报/世界/记忆/天气 4 屏（§2.3 首选外接项 + §3.2.4）。
**技术要求**：Riverpod `FutureProvider` + 缓存过期刷新；读 `readonly_api.dart`；设计令牌（§3.2.10）。
**时间节点**：08-25 ~ 08-27（依赖：P-S0 + P-S1）。
**负责人**：`Agent∥`（两路并联：T3.1 简报+天气 / T3.2 世界+记忆）。

- [ ] **T3.1 简报 + 天气屏（并联支路 A）**
  - [ ] `brief_screen.dart`（日期横幅/问候/新闻列表/GitHub 卡/趋势标签）
  - [ ] `world_screen.dart` 天气段 + 5 日预报横滚卡
  - [ ] L1 自检：只读接口 Widget 测试通过

- [ ] **T3.2 世界 + 记忆屏（并联支路 B）**
  - [ ] `world_screen.dart` 状态卡（房间/时段/情绪强度进度条）
  - [ ] `memory_screen.dart`（四层 Tab 胶囊切换）
  - [ ] L1 自检：只读接口 Widget 测试通过

- [ ] **T3.3 集成（L2）**：真机/模拟器只读接口调通；§7 S3 门禁 PASS/FAIL

---

### 9.5 P-S4 双端真机验收

**开发目标**：Android + iOS 全链路真机验证（§7 第 3 项）。
**技术要求**：vivo V2516A（Android）+ iOS 设备（待确认）；ADB reverse / 局域网；覆盖 §7 专项（明文/HTTPS/SSE）。
**时间节点**：08-27 ~ 08-29（依赖：P-S2 + P-S3 + **真机在线**）。
**负责人**：`Agent`（指令执行）+ **`User`**（设备接入、授权后台耗电、验收确认）。

- [ ] **T4.1 Android 真机**：登录/配对/消息双向/50MB 上传续传/Range 下载/只读四屏
- [ ] **T4.2 iOS 真机**（若设备可用，否则标记 D10 降级）：同上
- [ ] **T4.3 专项验收**：Debug 明文仅开发可用 / Release HTTPS 强制 / SSE 断网重连回放去重
- [ ] **T4.4 一致性**：本地消息与服务端一致（全量对比）；§7 S4 门禁 PASS/FAIL（**User 确认**）

---

### 9.6 P-S5 Cloudflare Tunnel

**开发目标**：`aerie.etta.top → 7891` 公网打通（§3.3）。
**技术要求**：cloudflared 独立 Windows 服务；config.yml 用户目录；7890 永不暴露。
**时间节点**：08-29 ~ 08-31（依赖：P-S4 + **User OAuth**）。
**负责人**：`Agent`（安装/配置/验收）+ **`User`**（浏览器 OAuth 授权）。

- [ ] **T5.1** 下载 cloudflared（用户目录，不进 Git）
- [ ] **T5.2** `cloudflared tunnel login`（**User** 浏览器授权）
- [ ] **T5.3** 创建命名隧道 `aerie.etta.top → http://127.0.0.1:7891`
- [ ] **T5.4** `cloudflared service install` + 重启自恢复验证
- [ ] **T5.5 验收（L3/L4）**：公网 health 200 / 7890 公网 404 / 双端真机经公网登录；§7 S5 门禁 PASS/FAIL

---

### 9.7 P-S6 签名发布

**开发目标**：产出 `0.1.0-Beta.1` 签名包 + QQ 独立闭环（§3.4）。
**技术要求**：同一 keystore 全生命周期（§3.4 硬约束）；CI 用 secrets 仅模拟器签。
**时间节点**：08-31 ~ 09-01（依赖：P-S5）。
**负责人**：`Agent` + **`User`**（keystore 离线双备份保管）。

- [ ] **T6.1** 创建仓库外 keystore + 离线双备份（**User** 确认位置）
- [ ] **T6.2** `build apk --release` 签名 + iOS 签名（若可用）
- [ ] **T6.3** 覆盖安装数据保留验证 + APK 敏感字符串零命中
- [ ] **T6.4** `AERIE_DISABLE_QQ=true` 全链路闭环
- [ ] **T6.5** 性能 KPI（冷启动 <2s / APK <100MB / 60fps）；§7 S6 门禁 PASS/FAIL

---

### 9.8 P-S7 收口缓冲

**开发目标**：文档收口 + 风险清零（§3.5 + §7 第 6 项）。
**技术要求**：主控文档 Evidence 追加；`flutter-mobile/README.md` 验收索引。
**时间节点**：09-01（依赖：P-S6）。
**负责人**：`Agent`。

- [ ] **T7.1** 主控文档 `Aerie_Android_Companion_Master_Plan.md` 状态同步 + §16 Evidence 追加
- [ ] **T7.2** `flutter-mobile/README.md` 写入架构/选型/命令/验收索引
- [ ] **T7.3** 文档 UTF-8/Markdown/敏感扫描复核；`git diff --check`
- [ ] **T7.4** §7 S7 门禁 PASS/FAIL + 风险表全项复核
