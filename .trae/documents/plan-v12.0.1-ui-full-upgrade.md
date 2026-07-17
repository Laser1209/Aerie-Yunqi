# Aerie v12.0.1 UI 全面升级 + 全链路质量保障方案

> 9项问题一站式修复 + 日历全新重做 + 纯对话能力下放 + 权限全链路审查 + 数据连通性保障

---

## 一、方案总览

| 模块 | 改动内容 | 工作量 | 优先级 |
|------|----------|--------|--------|
| M1 | 大脑4个能力标签页数据打通（自进化/电脑操控/文件整理/文档写作） | 高 | 🔴 P0 |
| M2 | 电脑操控权限档位交互 + 全链路权限审查 | 高 | 🔴 P0 |
| M3 | QQ页面合并到状态页 + 数据源统一 | 中 | 🟠 P1 |
| M4 | 设置页头像显示修复 | 低 | 🟠 P1 |
| M5 | 全项目版本号统一为 12.0.1 | 低 | 🟡 P2 |
| M6 | 关于页面补充免责声明与应用详情 | 低 | 🟡 P2 |
| M7 | 纪念日重做 → 日历（FullCalendar + 对话联动） | 高 | 🔴 P0 |
| M8 | 全量 emoji → SVG 图标库替换 | 中 | 🟠 P1 |
| M9 | 纯对话操作能力下放（Agent 可调用全部功能） | 高 | 🔴 P0 |
| M10 | 全链路数据连通性审查 + 测试验证 | 中 | 🔴 P0 |

---

## 二、M1：大脑4个能力标签页数据打通

### 现状问题
- `cognition-panel.js` 中 `_loadSelfEvolveData()`、`_loadComputerControlData()`、`_loadFileOrganizerData()`、`_loadDocWriterData()` 四个函数全部为硬编码的 demo 数据
- 刷新按钮点击后也只是重新渲染 demo 数据

### 后端 API 设计

#### 1. 自进化（Self Evolve）
已有基础 API，新增统计和历史：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/self_evolve/stats` | GET | 统计数据：总数/已应用/已回滚/待审核 |
| `/api/self_evolve/history` | GET | 历史列表（含状态、时间、描述） |
| `/api/self_evolve/list?status=pending` | GET | （已有）待审核列表 |
| `/api/self_evolve/:id/preview` | POST | （已有）预演 |
| `/api/self_evolve/:id/approve` | POST | （已有）批准 |
| `/api/self_evolve/:id/reject` | POST | （已有）拒绝 |

#### 2. 电脑操控（Computer Control）
基于 `core/computer_control.py` 新增 API：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/computer_control/status` | GET | 当前状态：权限等级/今日操作数/拦截数 |
| `/api/computer_control/level` | PUT | 设置权限等级（VIEW_ONLY / STANDARD / FULL） |
| `/api/computer_control/logs` | GET | 操作审计日志列表（分页） |
| `/api/computer_control/stats` | GET | 统计数据 |
| `/api/computer_control/blacklist` | GET | 危险命令黑名单列表 |

#### 3. 文件整理（File Organizer）
基于 `core/file_organizer.py` 新增 API：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/file_organizer/stats` | GET | 统计数据：已整理文件数/可撤销数/节省空间 |
| `/api/file_organizer/history` | GET | 整理历史列表 |
| `/api/file_organizer/undo/:id` | POST | 撤销某次整理 |
| `/api/file_organizer/run` | POST | 执行一次整理（指定目录+类型） |

#### 4. 文档写作（Doc Writer）
基于 `core/doc_writer.py` 新增 API：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/doc_writer/stats` | GET | 统计数据：文档总数 |
| `/api/doc_writer/list` | GET | 文档列表（标题/时间/格式/模板） |
| `/api/doc_writer/templates` | GET | 可用模板列表 |

### 前端改动
- `electron/src/renderer/js/cognition-panel.js`
  - 重写 `_loadSelfEvolveData()` → 从 API 加载
  - 重写 `_loadComputerControlData()` → 从 API 加载
  - 重写 `_loadFileOrganizerData()` → 从 API 加载
  - 重写 `_loadDocWriterData()` → 从 API 加载
  - 新增各标签页操作按钮的事件绑定

---

## 三、M2：电脑操控权限 + 全链路权限审查

### 3.1 前端交互层
- 新增 `.cog-cc-level--active` 选中状态样式（边框高亮 + 渐变背景 + 勾选图标）
- Hover 状态 + 点击过渡动画
- FULL 档切换时二次确认弹窗
- 权限变更后实时刷新状态显示

### 3.2 API 层校验
- 参数合法性校验（只允许 VIEW_ONLY / STANDARD / FULL）
- 权限提升需要额外验证（如 FULL 档需要确认当前用户身份）
- 所有权限变更记录审计日志

### 3.3 业务逻辑层
- `core/computer_control.py` 中每个操作前校验权限等级
- 低权限调用高权限操作 → 拒绝 + 记录 + 返回友好错误
- 危险命令黑名单校验与权限等级联动

### 3.4 数据存储层
- 权限等级持久化到 `settings.yaml`
- 操作审计日志 JSONL 格式
- 日志不可篡改（追加写入）

### 3.5 Agent 调用层
- Agent 通过 tool 调用电脑操控时，必须传入权限等级校验
- 高权限操作（FULL档）需要用户确认机制
- 所有 tool 调用记录到审计日志

---

## 四、M3：QQ页面合并到状态页

### 合并后结构
```
状态页
  ├─ 系统状态卡片组（4个）
  │   ├─ 后端状态
  │   ├─ QQ 连接（使用 napcat/status 数据源）
  │   ├─ Token 消耗
  │   └─ API 调用次数
  │
  └─ QQ 运维区块（可折叠展开）
      ├─ 连接状态指示器（详细phase）
      ├─ 操作按钮组（启动/停止/刷新）
      ├─ 二维码区域（扫码登录时显示）
      └─ 运行日志（可展开/收起）
```

### 改动文件
- `electron/src/renderer/index.html` - 状态页扩展，移除独立 QQ 面板和侧栏按钮
- `electron/src/renderer/js/app.js` - QQ 状态数据源切换
- `electron/src/renderer/js/napcat-panel.js` - 重构为状态页内模块
- `electron/src/renderer/styles/main.css` - 新增状态页 QQ 区块样式

---

## 五、M4：设置页头像显示修复

### 修复方案
1. 检查并补充默认头像文件（SVG 矢量图，file:// 协议下稳定加载）
2. 头像加载失败时降级：显示名字首字母 + 渐变圆形背景
3. dataURL 优先，HTTP URL 作为 fallback
4. 错误事件监听，加载失败自动切换降级方案

### 改动文件
- `electron/src/renderer/assets/` - 补充默认头像 SVG
- `electron/src/renderer/js/settings.js` - 优化加载逻辑 + 降级处理

---

## 六、M5：全项目版本号统一为 12.0.1

| 文件 | 当前 | 目标 |
|------|------|------|
| `electron/package.json` | 12.0.1 | ✓ |
| `electron/src/renderer/index.html` 关于页 | v10.1.1 | → v12.0.1 |
| `core/api_server.py` FastAPI `version` | 9.0.0 | → "12.0.1" |
| `core/api_server.py` `/api/health` version | 9.0.0 | → "12.0.1" |
| `README.md` | - | 检查更新 |
| `CHANGELOG.md` | - | 检查更新 |

---

## 七、M6：关于页面补充

### 新增内容区块
1. **应用介绍** — Aerie · 云栖是什么
2. **核心特性** — 本地优先 / 私人专属 / 全栈 AI 伴侣
3. **技术栈** — Electron + Python + FastAPI + SQLite
4. **免责声明**
   - 本软件仅供学习交流使用
   - 使用者需遵守当地法律法规
   - AI 生成内容不代表开发者立场
   - 使用风险由用户自行承担
5. **开源依赖致谢**
6. **版本信息** — v12.0.1

---

## 八、M7：纪念日重做 → 日历

### 8.1 核心功能

#### 日历视图（FullCalendar v6）
- 月视图（默认，挂历形式）
- 周视图 / 日视图（可切换）
- 今日高亮、选中日期高亮
- 事件颜色标签（按类型区分）
- 农历/节日可选显示

#### 顶部统计区
- 💕 **相识天数**：从首次启动开始计算
- 💬 **消息统计**：用户发送数 / AI 回复数
- 📅 **本月事件数**
- ⏰ **即将到来**：最近一个纪念日/倒计时

#### 事件类型
| 类型 | 颜色 | 说明 |
|------|------|------|
| 纪念日 | 粉红/红色系 | 每年重复的重要日子 |
| 日程 | 蓝色系 | 单次或重复的安排 |
| 倒计时 | 橙色系 | 倒数日（如考试、节日） |
| 日记 | 绿色系 | 当日记录/心情 |

#### 事件簿（时间线）
- 下方列表形式展示未来事件
- 按日期分组，类似钉钉/飞书
- 显示时间、类型图标、标题、操作按钮

#### 对话联动（M9 重点）
- Agent 可通过 tool 操作日历
- 「帮我记下周三下午3点开会」→ 自动解析创建日程
- 「明天有什么安排」→ 查询并回复
- 「还有多少天到我生日」→ 倒计时查询
- 创建成功后 SSE 实时推送到前端

### 8.2 数据模型
```sql
CREATE TABLE calendar_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  type TEXT NOT NULL,          -- anniversary / schedule / countdown / diary
  title TEXT NOT NULL,
  description TEXT,
  start_time DATETIME NOT NULL,
  end_time DATETIME,
  is_all_day INTEGER DEFAULT 1,
  repeat_rule TEXT,            -- none / yearly / monthly / weekly / daily
  color TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

### 8.3 API 设计
| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/calendar/events?start=&end=` | GET | 按时间范围查询事件 |
| `/api/calendar/events` | POST | 新增事件 |
| `/api/calendar/events/:id` | PUT | 更新事件 |
| `/api/calendar/events/:id` | DELETE | 删除事件 |
| `/api/calendar/stats` | GET | 统计：相识天数/消息数/本月事件数 |
| `/api/calendar/upcoming` | GET | 即将到来的事件（N条） |

### 8.4 改动文件
- `core/database.py` - 新增 calendar_events 表 + 迁移脚本
- `core/api_server.py` - 日历 CRUD + 统计 API
- `core/tool_registry.py` - 日历相关 tool 注册
- `electron/src/renderer/index.html` - 纪念日面板 → 日历面板
- `electron/src/renderer/js/calendar-panel.js` - 全新日历面板
- `electron/src/renderer/styles/calendar-panel.css` - 日历样式
- FullCalendar v6 静态资源本地化

---

## 九、M8：全量 emoji → SVG 图标替换

### 现状
大脑页面各标签页中大量使用 emoji 作为图标（👁️✋⚡📁📄🧬🔧🎨等），在不同系统/字体下显示不一致。

### 替换方案
1. 使用项目已有的 SVG Sprite 体系（`index.html` 中的 `<symbol>`）
2. 新增所需图标到 sprite 中
3. 所有 emoji 图标替换为 `<svg class="icon"><use href="#icon-xxx"/></svg>`
4. 保持与现有图标风格统一

### 新增图标清单
- 自进化：dna / sparkles / upgrade
- 电脑操控：desktop / mouse / keyboard / shield
- 文件整理：folder / file-image / file-text / file-video
- 文档写作：doc / book / file-spreadsheet
- 日历：calendar / clock / heart / star
- 其他页面中出现的 emoji

---

## 十、M9：纯对话操作能力下放

### 目标
用户仅通过聊天对话，就能操作全部功能，无需点击 UI。

### 已具备的能力
- 自进化提案的批准/拒绝（已有 tool）
- 文件整理调用（已有基础）

### 需要新增的 Agent Tool

| Tool 名称 | 功能 | 权限要求 |
|-----------|------|----------|
| `calendar_add_event` | 添加日历事件 | 低 |
| `calendar_query_events` | 查询日程/纪念日 | 低 |
| `calendar_delete_event` | 删除日历事件 | 中（需确认） |
| `computer_control_set_level` | 调整电脑操控权限 | 高（需强确认） |
| `file_organizer_run` | 执行文件整理 | 中（需确认） |
| `file_organizer_undo` | 撤销文件整理 | 中 |
| `doc_writer_create` | 创建文档 | 中 |
| `self_evolve_list` | 查看自进化提案 | 低 |
| `self_evolve_decide` | 审批自进化提案 | 高（需确认） |

### 权限控制策略
- **低风险操作**（查询类）：直接执行
- **中风险操作**（修改数据）：执行前询问用户确认
- **高风险操作**（权限变更/系统级）：必须明确用户确认 + 记录审计
- 所有 tool 调用记录到操作日志

### 改动文件
- `core/tool_registry.py` - 新增工具注册
- `core/agent.py` - 工具调用权限校验
- Prompt 层：补充工具使用说明

---

## 十一、M10：全链路数据连通性审查

### 11.1 审查范围
每个页面对应的后端 API → 数据存储 → Agent 调用，全部链路验证。

### 11.2 页面连通性清单

| 页面 | 数据来源 | 验证点 |
|------|----------|--------|
| 聊天 | `/api/chat` + SSE | 消息发送/接收/流式输出 |
| 情绪 | `/api/emotion/state` + `/api/emotion/history` | 当前状态/历史数据/图表 |
| 大脑-中枢 | `/api/cognition/*` + SSE | 时间线/决策赛马/历史列表/统计 |
| 大脑-自进化 | `/api/self_evolve/*` | 列表/统计/审批操作 |
| 大脑-电脑操控 | `/api/computer_control/*` | 状态/档位/日志/黑名单 |
| 大脑-文件整理 | `/api/file_organizer/*` | 历史/统计/撤销/执行 |
| 大脑-文档写作 | `/api/doc_writer/*` | 列表/统计/模板 |
| 状态 | `/api/health` + `/api/napcat/status` + `/api/stats/tokens` | 全部4张卡片 + QQ运维 |
| 日历 | `/api/calendar/*` | 事件CRUD/统计/联动 |
| 数据 | `/api/data/*` | 数据查看/导出 |
| 设置 | `/api/settings` + `/api/persona/*` + `/api/config/*` | 表单/YAML/头像/重启 |
| 关于 | 静态数据 | 版本/免责/详情 |

### 11.3 验证方法
1. **静态审查**：代码走查，确保每个 UI 元素都有对应的数据来源
2. **运行时验证**：启动应用，逐页面检查数据加载
3. **边界测试**：网络异常、后端宕机、数据为空等场景降级处理
4. **一致性校验**：同一数据在不同页面显示一致（如 QQ 状态）

### 11.4 目标
- 99% 的 UI 数据元素有真实后端来源
- 错误场景有友好降级提示
- 数据刷新机制合理（定时 + 事件驱动）

---

## 十二、实施顺序

```
Phase 1: 快速修复
  ├─ M4 头像修复
  ├─ M5 版本号统一
  └─ M6 关于页补充

Phase 2: 数据打通 + 权限
  ├─ M1 大脑4标签页数据打通
  └─ M2 电脑操控档位交互 + 权限审查

Phase 3: 结构调整
  └─ M3 QQ合并到状态页

Phase 4: 日历重做
  └─ M7 日历（FullCalendar + CRUD + 统计）

Phase 5: 能力下放 + 质量
  ├─ M8 emoji → SVG 图标替换
  ├─ M9 纯对话操作能力下放
  └─ M10 全链路连通性审查 + 测试
```

---

## 十三、风险与注意事项

1. **FullCalendar 集成**：需本地打包，不依赖 CDN，确保离线可用
2. **数据库迁移**：anniversary → calendar_events 数据迁移脚本，保证不丢数据
3. **对话联动**：自然语言解析日程分两期（先做结构化 tool 调用，再优化自然语言理解）
4. **权限下放**：高风险操作必须有用户确认闭环，防止 Agent 误操作
5. **向后兼容**：旧 API 保留 deprecated 标记，下个大版本移除
6. **图标一致性**：新增 SVG 图标与现有风格统一（线性、24px、stroke-width=2）
