---
title: Phase 9 续批 · E2E 阶段 + 后续整改（一）托盘右键 + 头像/名字 + 角色设置
date: 2026-07-17
version: v4.0
tags:
  - phase9
  - e2e
  - verify
  - tray-menu
  - avatar
  - persona-settings
  - ita-persona
  - three-principles
cssclasses:
  - wide-page
aliases:
  - E2E + 托盘与头像整改
---

# Phase 9 续批 · E2E + 后续整改（一）

> [!quote] 文档定位
> B7 已于 2026-07-17 落地，4 套 verify 脚本 113/113 全过。
> 本计划分两步：
>   1. E2E 阶段：建 e2e_pacing.py + e2e_self_evolve.py + 18 项 checklist 文档
>   2. E2E 完成后 问 1 个澄清问题 → 主人说"是" → 启动 Block-2（tray 右键 + 头像/名字 + 角色设置）
>
> 3 轮提问（2026-07-17）已锁 3 项关键决策（E2E 全 3 项 / 托盘=Aerie 自己 / 头像两边都加）。

---

## 一、3 项决策汇总（已锁）

| # | 决策点 | 决策结果 | 落地要点 |
| --- | --- | --- | --- |
| 1 | E2E 范围 | **全 3 项** | e2e_pacing.py + e2e_self_evolve.py + 18 项 checklist 文档 |
| 2 | 第一张图对象 | **Aerie 自己的托盘** | electron tray 缺 setContextMenu，新增 4 项菜单（显示/隐藏/设置/退出） |
| 3 | 头像范围 | **伊塔 + 用户两边都加** | chat-bubble 旁挂 avatar + name；用户头像用 NapCat 头像或默认占位 |

---

## 二、三原则铁律（主人反复强调）

> [!danger] 整改过程中必须严守
> 1. **不破坏现有功能** — Phase 1-9 已验证模块继续工作，零回归（9 张老表 + 4 张新表 + cognition/decision/emotion_state_store + B3-B7）
> 2. **不破坏伊塔人格** — v9.0 Hybrid（26岁/184cm/四爱/温柔大姐姐+病娇）；禁词"主人/您"；UI 文案温柔克制
> 3. **设计美学统一** — 主面板伊塔粉紫主题；新增 UI（tray 菜单/聊天头像）必须遵循现有 5 主题

---

## 三、Current State 盘点（已基于实际代码探索）

### 3.1 已落地（不动）

| 模块 | 文件 | 状态 |
| --- | --- | --- |
| 4 套 verify 脚本 113/113 全过 | `verify_*.py` × 4 | ✓ |
| Tray 创建逻辑 | [electron/src/main.js:197-211](file:///e:/Agent_reply/electron/src/main.js#L197-L211) | ✓ 但**无右键菜单** |
| 聊天气泡渲染 | [electron/src/renderer/js/chat.js:295-385](file:///e:/Agent_reply/electron/src/renderer/js/chat.js#L295-L385) | ✓ 但**无头像/名字** |
| Settings 表单视图 | [electron/src/renderer/index.html:379-405](file:///e:/Agent_reply/electron/src/renderer/index.html#L379-L405) | ✓ 但**无 persona 头像/名字设置** |
| persona.yaml 含 name/english_name | [config/persona.yaml:7-9](file:///e:/Agent_reply/config/persona.yaml#L7-L9) | ✓ 但 UI 未读取展示 |

### 3.2 关键缺失（待整改）

| 缺口 | 影响 | Block |
| --- | --- | --- |
| `e2e_pacing.py` 缺失 | 综合节奏演示脚本无 | E2E.2 |
| `e2e_self_evolve.py` 缺失 | 自进化全链路 e2e 入口无 | E2E.3 |
| 18 项 checklist 文档缺失 | 验收无依据 | E2E.4 |
| `tray.setContextMenu` 缺失 | 右键无快捷操作 | Block-2 / T1 |
| 聊天 avatar DOM 节点缺失 | 气泡只有文字 | Block-2 / A1 |
| settings 缺 persona 头像/名字设置 | 用户无法自定义 | Block-2 / A2 |

### 3.3 现有隐患

- `chat.js:295-385` 渲染时未读 `msg.role` 来决定头像来源，需要扩展
- `main.js:204` Tray 创建后只 `setToolTip` + `on("click")`，需补 `setContextMenu`
- persona.yaml 已含 `name/english_name`，UI 读取入口缺失

---

## 四、E2E 阶段实施（1.5h · 全部 3 项）

### E2E.1 新建 `e2e_pacing.py`（综合节奏演示）

- 文件位置：`e:\Agent_reply\e2e_pacing.py`
- 内容（参考 plan-phase9-batch4-7-combined-execution.md §E2E.2）：
  - 5 段 × 6 情绪/喷发组合（neutral / joy / sad / fear / anxiety 喷发 / tenderness 喷发）
  - 每次输出 `seg {i}: {iv:.2f}s [{style}]`
  - assert：首段 `interval == 0.0`；后续段 `interval <= 5.0`
  - 终打印 `✓ e2e_pacing 全部通过`
- 不依赖 LLM / DB，纯本地 asyncio + persona_pacing
- 复用 `core/persona_pacing.py` 已有的 11 风格决策树

### E2E.2 新建 `e2e_self_evolve.py`（自进化全链路入口）

- 文件位置：`e:\Agent_reply\e2e_self_evolve.py`
- 与 `verify_self_evolve.py` 的关系：后者是 3 段单元/集成/HTTP 测试；前者是 **blocker 友好的"全链路冒烟"**
- 内容：
  - 构造 react_trace 含"无法读取本地文件"
  - 构造失败 tool_result（success=False, error="no_such_tool"）
  - 调 `SelfEvolver.maybe_propose(...)` → 期望返回非 None row id
  - 查 `self_evolve_log` → 期望 `user_decision='pending'`
  - 调 `SelfEvolver.approve(row_id)` → 期望 `user_decision='approved'`
  - 查 `tool_registry` → 期望多了一个工具
  - 终打印 `✓ e2e_self_evolve 全部通过`

### E2E.3 新建 `.trae/documents/phase9-e2e-checklist.md`（18 项 checklist）

- 标题：Phase 9 续批 · E2E 验收清单
- 18 项分 6 组：
  - 表与 schema（4 项）：9 张老表 + 4 张新表 + 3 索引 + PRAGMA integrity_check
  - API 健康（3 项）：/api/health ok / cognition / emotion 端点
  - UI 渲染（4 项）：聊天正常 / 主题切换 / 大脑中枢 tab 可见 / 自进化卡片可见
  - pacing 落库（2 项）：pacing_decisions 数组非空 / 首段 interval=0
  - 自进化闭环（3 项）：提案可生成 / 沙箱试运行 / 批准后工具注册
  - 文档与规范（2 项）：persona 文案无禁词 / 代码层全英文
- 每项 `- [ ]` 形式，附"如何验证"小字

### E2E.4 自我怀疑 review + 验证

- review 1: e2e_pacing.py 6 个组合全过且 assert 不破
- review 2: e2e_self_evolve.py approve 后 tool_registry 真的多出工具
- review 3: 18 项 checklist 每一项都可被前 4 个 verify 脚本 + e2e_*.py 覆盖
- 跑 `verify_zero_regression.py` + `verify_emotion_history.py` + `verify_self_evolve.py` + `verify_pacing_persistence.py` + `e2e_pacing.py` + `e2e_self_evolve.py` 全部应过

**E2E 验收**：4 verify + 2 e2e 全绿；18 项 checklist 文件存在；可在 main 分支引用

---

## 五、Block-2 计划（待 E2E 完成后主人确认启动）

> [!info] 触发条件
> E2E 全绿后，我会问 1 个澄清问题，主人回答"是"才启动本 Block。
> 当前 plan 仅列方案概要，详细实施在主人确认后另写 plan。

### T1 托盘右键菜单（[electron/src/main.js:197-211](file:///e:/Agent_reply/electron/src/main.js#L197-L211)）

- 新增 `Menu.buildFromTemplate([...])` 4 项：
  1. 「显示 / 隐藏窗口」 → 切换 `mainWindow.show()/hide()`
  2. 「设置」 → `mainWindow.show()` + IPC 切到 settings tab
  3. 「关于」 → 弹 `dialog.showMessageBox` 显示 Aerie · 云栖 信息
  4. 「退出」 → `app.quit()`（同时 kill pythonProc）
- 接入：`tray.setContextMenu(menu)`
- 需新增 IPC handler：`settings:open-tab` 用于切到设置 tab

### A1 聊天头像 + 名字（[electron/src/renderer/js/chat.js:295-385](file:///e:/Agent_reply/electron/src/renderer/js/chat.js#L295-L385)）

- 在 chat-bubble 旁挂 `<div class="chat-msg__avatar">` + `<span class="chat-msg__name">`
- assistant 端：`<img src="...">` + "伊塔"
- user 端：`<img src="...">` + "你"
- 头像数据来源：
  - 伊塔：从 `config/persona.yaml` 读取（API 端点 `GET /api/persona` 待新增）
  - 用户：从 NapCat `get_stranger_info`/`get_friend_info` 拿 QQ 头像（API 端点 `GET /api/qq/avatar?user_id=` 待新增）
  - 失败回退：默认 SVG 头像
- 样式：圆形 36px，左/右对齐，5 主题色自适应

### A2 角色设置页面（[electron/src/renderer/index.html:379-405](file:///e:/Agent_reply/electron/src/renderer/index.html#L379-L405)）

- 在 settings form view 顶部新增「伊塔 persona」区块：
  - 头像上传（PNG/JPG，≤2MB）→ 保存到 `data/persona/avatar.png`
  - 名字输入框（默认"伊塔"）→ 写回 `config/persona.yaml`
  - 英文名输入框（默认"Ita"）→ 写回 `config/persona.yaml`
- 新增 API 端点：
  - `GET /api/persona` → 返回 name/english_name/avatar_url
  - `PUT /api/persona` body={name, english_name, avatar_base64?} → 写回
  - `POST /api/persona/avatar` multipart upload
- 文案（中英双语，符合伊塔人格）：
  - 区块标题：「她的样子 · Her Appearance」
  - 提示：「这是她在你眼中的样子。改完她就是这个人。/ This is who she is to you.」

### A2 自我怀疑 review

- review 1: avatar 上传后是否真写到 `data/persona/avatar.png`
- review 2: persona.yaml 写回是否走 B3 已有的 yaml 强校验
- review 3: 聊天刷新时是否真读新头像/名字（不缓存旧值）
- review 4: 上传超大文件是否拦截

---

## 六、E2E 阶段文件改动汇总

| 文件 | 类型 | 估行数 | 说明 |
| --- | --- | --- | --- |
| `e2e_pacing.py` | 新 | +60 | E2E：6 情绪/喷发综合节奏 |
| `e2e_self_evolve.py` | 新 | +80 | E2E：自进化全链路冒烟 |
| `.trae/documents/phase9-e2e-checklist.md` | 新 | +120 | E2E：18 项 checklist 文档 |

**总计**：3 个新文件 + 估约 **260 行新增**

---

## 七、E2E 阶段风险与回滚

| 风险 | 概率 | 影响 | 回滚方案 |
| --- | --- | --- | --- |
| e2e_pacing 频率触发慢 | 低 | 验证耗时 | 不影响主链路，纯脚本 |
| e2e_self_evolve 副作用污染 DB | 中 | 自进化 log 留痕 | 每个测试用独立 user_id 隔离；脚本结束前 DELETE 测试 row |
| 18 项 checklist 漏项 | 中 | 验收不全 | review 时与原 plan-phase9-batch4-7 §E2E.4 逐项对照 |

---

## 八、E2E 阶段不在本次范围

- Block-2（tray + 头像 + 角色设置）— 待主人确认后另写 plan
- cognition_log 7d 自动归档
- 跨平台 Linux/macOS 兼容
- 中等敏感自进化限流（5 条件）

---

## 九、E2E 阶段执行顺序（严格）

```
E2E.1 e2e_pacing.py          (0.25h)
   ↓
E2E.2 e2e_self_evolve.py     (0.5h)
   ↓
E2E.3 18 项 checklist 文档    (0.25h)
   ↓
E2E.4 自我怀疑 review + 跑全部 6 个脚本  (0.5h)
```

**总工时估约 1.5h**

**强约束**：
- 每子项完成后立即跑对应脚本
- 任何子项失败必须自我怀疑、回滚、再实施
- 严守"三原则"
- 代码层纯英文 + UI 层中英双语

---

## 十、与现有约束兼容性自检

| 约束 | 兼容性 |
| --- | --- |
| NapCat launcher-user.bat 启动 | ✓ E2E 不动 launcher / start-companion |
| 9 张老表零回归 | ✓ E2E 仅追加测试 row，不改 schema |
| 5 主题配色 | ✓ E2E 不渲染 UI |
| 伊塔 persona | ✓ e2e_pacing / e2e_self_evolve 文案符合 v9.0 Hybrid |
| `app_name` 用 Aerie | ✓ 脚本注释纯英文 |
| `parse_error` 不抛异常 | ✓ 脚本 try/except 包裹 |

---

## 十一、待主人确认事项

> [!question] 在 Phase 4 实施前，主人需确认：
> 1. 3 项决策（E2E 全 3 项 / 托盘=Aerie 自己 / 头像两边都加）是否全部接受？
> 2. E2E 阶段执行顺序 E2E.1 → E2E.2 → E2E.3 → E2E.4 是否同意？
> 3. E2E 完成后，我问 1 个澄清问题（关于 Block-2 启动条件），主人说"是"才进入 tray + 头像 + 角色设置，是否同意？
> 4. 是否同意每个 verify/e2e 脚本失败立即中断，不堆到下一子项？

确认后立即开干 E2E。
