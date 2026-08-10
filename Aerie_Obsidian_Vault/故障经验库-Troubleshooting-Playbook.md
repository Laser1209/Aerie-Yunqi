---
title: 故障经验库 · Troubleshooting Playbook
aliases:
  - 故障经验库
  - Troubleshooting Playbook
  - 踩坑记录
  - 排障手册
tags:
  - knowledge/troubleshooting
  - knowledge/best-practices
  - vault/knowledge
  - type/moc
status: active
created: 2026-08-11
updated: 2026-08-11
---

# 故障经验库 · Troubleshooting Playbook

本页将 Aerie 项目 `README.md`「故障排查」章节的全部故障记录，按**问题类型**重新分类、提炼「现象 → 根因 → 方案」并沉淀**可迁移的最佳实践**，便于检索与跨项目复用，减少重复踩坑。

> 详细原始内容以 [README](../README.md#故障排查--troubleshooting) 为准；本页是面向复用的结构化蒸馏。

## 一、分类索引

| 分类 | 关键教训（一句话） | 跳转 |
| --- | --- | --- |
| [[#二、环境配置与依赖]] | 启动前先清端口孤儿进程、验模块可独立导入 | [[#二、环境配置与依赖]] |
| [[#三、能力声明与依赖矩阵]] | 能力声明必须与实际模式一致，fail-closed | [[#三、能力声明与依赖矩阵]] |
| [[#四、后端进程与端口]] | 捕获 `SystemExit`、先后端后前端、单实例锁 | [[#四、后端进程与端口]] |
| [[#五、数据一致性与落库]] | emit 前必须落库；返回统一规范化映射 | [[#五、数据一致性与落库]] |
| [[#六、前端渲染与 Electron]] | 相对路径补绝对 API 前缀；CSS 作用域防覆盖 | [[#六、前端渲染与 Electron]] |
| [[#七、安全与输入校验]] | 归档/文件 fail-closed，MIME 双向匹配 | [[#七、安全与输入校验]] |
| [[#八、并发、去重与一致性]] | 跨重启去重走持久化存储，非进程内存 | [[#八、并发、去重与一致性]] |
| [[#九、时区与世界模拟]] | 统一 `LOCAL_TZ`，跨来源时间先归一 | [[#九、时区与世界模拟]] |
| [[#十、模型与 API 调用]] | 轻量任务走轻量模型，超时可回退 | [[#十、模型与 API 调用]] |
| [[#十一、检索与知识库]] | `db` 依赖必须显式传入；OR 检索而非整句拼接 | [[#十一、检索与知识库]] |
| [[#十二、业务逻辑与功能异常]] | 输入规范化、统一格式常量、能力认知与开关联动 | [[#十二、业务逻辑与功能异常]] |
| [[#十三、工具链与脚本]] | PowerShell 长内联脚本改 `.py`；`import core` 需项目根 | [[#十三、工具链与脚本]] |
| [[#十四、可迁移最佳实践]] | 跨项目通用的八条工程铁律 | [[#十四、可迁移最佳实践]] |

---

## 二、环境配置与依赖

> 标签：`trouble/env` `trouble/dependency`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 后端冷启动崩溃、重启后需手动重启 | 移动网关 7891 被孤儿进程占用，uvicorn `sys.exit(3)` 抛 `SystemExit` 未被 `except Exception` 捕获 | 启动前端口预检测 + 捕获 `SystemExit` + Electron 启动前清理 7890/7891 孤儿进程 |
| pytest 收集阶段卡住无输出 | `conftest.py` 导入 `core.api_server` 等重型模块，本机环境下阻塞 | 先用 `python -c "import <module>"` 验证被测模块可独立导入；业务逻辑用独立脚本等价验证 |
| `ModuleNotFoundError: No module named 'core'` | 脚本在 `tools/` 等子目录裸跑，项目根不在 `sys.path` | 设 `PYTHONPATH=<root>` 或用 `python -m` 方式执行 |
| 语音时长始终为 0 | `ffprobe` 缺失 | 降级返回 0.0 不阻塞转写；需要时长则内置/随包分发 ffmpeg |
| `tools/restart.bat` 提示文件名语法不正确 | `start` 无法直接启动 `.cmd` 垫片 | 直接启动 `electron\dist\electron.exe` 二进制 |
| PowerShell 中文乱码 | PowerShell 5 控制台代码页非 UTF-8 | 数据本身正确；用 `[Text.Encoding]::UTF8` 或 `PYTHONIOENCODING=utf-8` 校验 |

**可迁移**：环境问题排查第一步永远是「被测对象能否独立运行」，把环境阻塞与代码缺陷分开。

---

## 三、能力声明与依赖矩阵

> 标签：`trouble/capability` `trouble/dependency`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 上传媒体提示解析失败（T01） | `analysis_mode=extract` 但系统声明 `contentExtractionAvailable=False`，能力声明与实际模式脱节 | 媒体一律 `metadata` 模式，与能力声明一致；能力矩阵同步更新 |
| 附件无语义检索 | `chromadb` 未装或缺 embedding Key | 安装依赖并配置 Key |

**可迁移**：「能力声明」与「实际实现/开关」必须双向一致，禁止"声明不可用却走该路径"；新增能力先查依赖矩阵。

---

## 四、后端进程与端口

> 标签：`trouble/process` `trouble/port` `trouble/backend`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| Electron 反复 `ECONNREFUSED 7890`（T02） | 前端先于后端就绪 + preload 无重试 + 多实例竞争端口 | 单实例锁 + preload 自动重试 + 启动顺序先后端再前端 |
| 后端改动不生效（404） | `main.py` 用 `asyncio.run()` 无热重载 | 结束进程 → 等端口释放 → 用 `-X dev main.py` 重启 |

**可迁移**：多进程应用务必保证**启动顺序**与**端口独占**；长期运行的进程要提供明确的重启方式，避免"改代码靠玄学"。

---

## 五、数据一致性与落库

> 标签：`trouble/data-consistency` `trouble/persistence`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 时间戳只部分显示/随机（T03） | legacy `chat_log` 未填 `ts`、接口 `SELECT *` 不映射、CSS hover 才显 | 所有条目统一 `ts=created_at`；接口逐条补 `ts`；CSS 始终显示 |
| 主动发图重启后气泡消失（T04） | 图片路径只 `emit` 不落库，"内存幽灵" | emit 前必须先 `db.insert`；用 rowid 作为 emit id |
| 人设同步脚本 `PermissionError` | `os.replace` 写在 `with open` 块内，Windows 自锁 | `os.replace` 移到块外 + 先 `os.fsync` |
| 消息重复渲染 / typing 残留 / 徽标丢失 | 多通道信号 domId 分裂、typing 绕过 store | 归一 domId、分片到达清理遗留 typing、渲染后重放状态 |

**可迁移**：任何 `emit`/推送前先持久化；返回给前端的映射必须用统一规范化函数，禁止 `SELECT *` 裸抛；Windows 写文件遵守"关句柄再重命名"。

---

## 六、前端渲染与 Electron

> 标签：`trouble/frontend` `trouble/electron` `trouble/ui`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 图片附件被裁切/留白（T05） | 全局 `.chat-attach-card img` 源序在后覆盖专用规则 + `object-fit:cover` | 收窄选择器作用域；容器 shrink-wrap；`object-fit:contain` |
| 时间戳只到分钟（T06） | 格式化硬编码 `HH:MM` 无秒 | 用常量 `DATE_FMT`，统一 秒/毫秒/ISO 输入 |
| Markdown 图片 file:// 404（T09） | Electron `file://` 下相对路径解析错 | 统一 rewrite helper：相对路径 → 绝对 `http://127.0.0.1:7890` 前缀 |
| PAD 圆环与数值不显示 | `--mask-size:56px` 是半径非直径，挖空整个圆环 | 改为 `28px`（对应 56px 直径的"数字洞"） |
| 对话加载历史卡顿 | 一次性加载全部 + DOM 过大 | 只加载最近一批，滚动分页，DOM 上限裁剪 |

**可迁移**：写组件专用 CSS 后 grep 同名全局规则是否覆盖；对 `file://` 渲染环境统一"本地相对路径 → 绝对 URL"的 rewrite helper，避免各模块各写一套。

---

## 七、安全与输入校验

> 标签：`trouble/security`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 伪造 RAR 被误判 ready（T07） | `rarfile` 对空成员伪造文件宽容，返回空清单不抛错 | 归档解析后强制「有效成员 ≥ 1」闸门，fail-closed |
| 归档被隔离签名不匹配（T08） | magic bytes 与扩展名不一致，或传输损坏 | 保留原扩展名上传；校验 MIME 与扩展名双向匹配 |

**可迁移**：安全边界一律 **fail-closed**——拿不到"明确安全"的证据就按拒绝处理；输入校验在系统边界做双向匹配。

---

## 八、并发、去重与一致性

> 标签：`trouble/concurrency` `trouble/dedup`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 自动发图重复生成相同图片 | `recent_intents` 只活进程内存，重启清零，幂等键按秒全新 | 去重读**持久化审计存储**（`has_recent_completed`，30min 窗口），仅 `completed` 计数 |
| 决策赛马与实际撤回不一致 | 决策输出仅遥测，未被执行链路消费 | 明确预测与实际执行机制的边界；以"实际执行"徽章为准 |

**可迁移**：需要跨重启生效的去重/幂等必须基于**持久化**而非进程内存；去重只拦成功记录，失败可重试；"预测"与"执行"链路要显式分离。

---

## 九、时区与世界模拟

> 标签：`trouble/timezone` `trouble/world-sim`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 深夜发"白天照"，光线错位 8 小时（14） | 世界时钟与生图时间注入用 UTC 未转本地 | 导出 `LOCAL_TZ(+08:00)`，默认时钟与兜底统一；跨来源时间先 `astimezone` 归一 |
| 无法注入外部生活事件 | 无外部事件数据结构与注入 API | 新增 `ExternalEvent` + `inject_event()` + `POST /api/world/events/inject` 双模实现 |
| 天气始终确定性一致 | 由 `seed+ts+phase` 确定性派生 | 需要变化时 `set_reality()` 刷新或注入事件驱动 |

**可迁移**：凡"按当前时刻生成内容"的功能必须统一时区常量并覆盖凌晨/正午边界单测；确定性派生适合可复现，但需随机/外部时提供显式入口。

---

## 十、模型与 API 调用

> 标签：`trouble/llm` `trouble/api`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 生图触发但无产出 | 图片服务商断连（`httpcore.RemoteProtocolError`） | 重试或检查 `IMAGE_GEN_BASE_URL` / Key |
| 提示词缺时间/天气或堆叠 | 静态模板未接 WorldSnapshot + 无选择层 | 两步接力：基础提示词 → 轻量 LLM 判断注入哪些数据 → 确定性兜底 |
| 轻量模型不可用（MiMo 400） | 模型 id 不存在/未开通 | 控制台确认真实 id；不确定时保留可用模型兜底 |
| `generate_push` 无法分场景调温 | `temperature` 进 `**kwargs` 被当占位符；`chat()` 写死温度 | `chat()` 加 `temperature` 参数穿透；具名参数置于 `**kwargs` 前 |
| 错字/同音字被误解 | 主模型无独立纠错 | 独立订正通道（轻量模型高置信替换）→ 理解前订正，不写回记录 |

**可迁移**：快速辅助任务用独立轻量模型，主模型不参与；外部模型调用一律带超时与确定性兜底；`**kwargs` 慎用，具名参数优先。

---

## 十一、检索与知识库

> 标签：`trouble/retrieval` `trouble/knowledge`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 主动消息检索命中 0（dialogue） | 整句拼接做 `tags LIKE`（带空格）永远匹配不到；content 需完整包含整串 | 每关键词独立 OR 过滤，category 命中优先；LIMIT 用 list 追加 |
| `KnowledgeBase().search()` 永远空 | 构造不传 `db` → `if not self.db: return []` 短路 | 生产用 `KnowledgeBase(self.db)`；独立脚本显式 `KnowledgeBase(Database())` |

**可迁移**：检索按**词元拆分**做 OR 而非整串匹配；有条件的依赖（如 db）必须显式注入，避免静默短路被误判为"数据不存在"。

---

## 十二、业务逻辑与功能异常

> 标签：`trouble/business-logic`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| 今日待办点击报 500 | `<input type=time>` 传裸 `HH:MM`，按天查询失配 + `StopIteration` | `_normalize_due_time` 补全为 `YYYY-MM-DDTHH:MM`；按 `external_id` 回读 |
| 日历事件未同步到待办 | 简报只查 `todo` 表 | `get_today_todos` 合并当天 `schedule/reminder`，前端 `is-event` 只读区分 |
| 简报欢迎语每天一样/快速生成被掐 | 缓存当日 JSON；轻量 LLM 4s 超时过紧 | 新增实时生成接口；超时上调 6s，失败回退随机模板 |
| AI 不主动发图/分不清表情包与图片（3） | 能力认知未注入 system prompt；L6 未分层 | 新增 L6「表达层次认知」；能力认知与 `world_image_candidates_v1` 开关联动；分层检测 |
| QQ 语音/表情无法解析（15/16） | CQ 码未解析、无 ASR、无视觉解析、无出站能力 | `QQMediaPreprocessor` 统一解析；ASR 转写 + 视觉解析；`fetch_custom_face` 出站收藏表情 |

**可迁移**：输入必须在边界规范化（补全缺失字段）；「能力认知」与「能力开关」用同一开关联动，防止"认知超前于能力"。

---

## 十三、工具链与脚本

> 标签：`trouble/tooling`

| 问题 | 根因 | 方案 |
| --- | --- | --- |
| PowerShell 内联 `python -c` 转义失败 | PS5 引号/转义处理与 bash 不同 | 复杂逻辑改用临时 `.py` 脚本落盘再执行 |
| 独立脚本 `import core` 失败 | 项目根不在 `sys.path` | `PYTHONPATH=<root>` 或 `python -m` |

**可迁移**：跨 shell 复杂逻辑优先落 `.py` 文件；可复用逻辑做 CLI/入口，避免把命令写死在交互式 shell。

---

## 十四、可迁移最佳实践

> 标签：`practice/best` 跨项目通用，可直接复用。

1. **启动顺序与端口独占**：多进程应用先后端后前端；启动前清理孤儿端口进程；用单实例锁防止重复拉起。
2. **持久化优先**：任何 emit/推送/幂等/去重，跨进程/重启生效者必须落持久化存储，禁止只活内存。
3. **fail-closed 安全**：拿不到"明确安全"证据就拒绝；归档/文件校验"有效成员 ≥ 1"；MIME 与扩展名双向匹配。
4. **能力声明与开关联动**：能力认知（prompt）与能力链路（feature flag）同开关，防止脱节。
5. **边界输入规范化**：用户输入在边界补全缺失字段、校验类型，避免下游按错误格式查询而 500。
6. **统一返回映射**：给前端的接口用统一规范化函数，禁止 `SELECT *` 裸抛；格式化用常量不用硬编码。
7. **时区单一来源**：所有"按当前时刻生成内容"统一时区常量并 `astimezone` 归一，覆盖边界单测。
8. **降级优先**：外部依赖（模型/API/ffmpeg）调用带超时与确定性兜底，核心链路永不因辅助能力失败而中断。
9. **独立可验证**：判定测试/环境问题时，先验"被测对象可独立 import/运行"，把环境阻塞与代码缺陷分开。
10. **写后自检**：写组件专用 CSS/代码后 grep 同名全局规则与覆盖关系；先持久化再 emit。

---

## 互链

- 回到首页：[[00_首页]]
- 模块入口：[[01_模块总览]]
- 当前状态：[[09_当前状态]]
- 相关模块：[[modules/QQMediaPipeline]]
- 原始来源：[README 故障排查](../README.md#故障排查--troubleshooting)
