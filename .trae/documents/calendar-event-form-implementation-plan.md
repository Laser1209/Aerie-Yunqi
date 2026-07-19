# Calendar Event Form Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 美化添加事件表单，并让全天、起止时间、重复事件和提前提醒形成真实端到端闭环。

**Architecture:** 保留现有 Electron 原生 HTML/CSS/JS 与 FastAPI/SQLite 架构。后端负责字段校验、按查询范围展开重复实例和扫描提醒；前端负责一致的柔雾粉白表单、完整字段编辑和通知呈现。

**Tech Stack:** Electron 28、原生 JavaScript/CSS、Python、FastAPI、SQLite、pytest

---

### Task 1: 日历领域逻辑与测试

**Files:**
- Modify: `core/calendar_manager.py`
- Modify: `core/database.py`
- Test: `tests/test_calendar_manager.py`

- [ ] 编写失败测试，覆盖合法重复枚举、提醒分钟数、结束时间不得早于开始时间、日/周/月/年实例展开。
- [ ] 运行 `python -m pytest tests/test_calendar_manager.py -v`，确认新增测试失败。
- [ ] 在 `CalendarManager` 中集中规范化字段并实现限定范围的重复实例展开。
- [ ] 扩展 timeline 返回原始事件 ID、实例 ID、重复和提醒字段。
- [ ] 再次运行测试并确认通过。

### Task 2: 可靠提醒扫描与推送

**Files:**
- Modify: `core/database.py`
- Modify: `core/calendar_manager.py`
- Modify: `core/api_server.py`
- Test: `tests/test_calendar_manager.py`

- [ ] 新增 `calendar_reminder_log` 表及唯一索引。
- [ ] 编写到期提醒、重复实例提醒、防重复和过期窗口测试。
- [ ] 实现 `collect_due_reminders(now, lookback_minutes)`，事务性写入日志后返回待推送提醒。
- [ ] 在 API 生命周期中启动低频异步扫描任务，通过现有事件流发送 `calendar_reminder`。
- [ ] 运行相关 pytest，确认提醒只发一次。

### Task 3: 完整表单结构与视觉

**Files:**
- Modify: `electron/src/renderer/index.html`
- Modify: `electron/src/renderer/styles/calendar-panel.css`

- [ ] 将平铺 label/input 改为语义化字段容器和双列布局。
- [ ] 加入结束日期/时间、全天开关、重复规则、提前提醒。
- [ ] 将颜色点改为带 aria-label 的原生 radio/button 控件。
- [ ] 实现柔雾粉白表面、统一控件状态、错误提示、响应式布局和 reduced-motion。
- [ ] 使用键盘 Tab 检查焦点顺序和可见焦点环。

### Task 4: 前端数据与交互闭环

**Files:**
- Modify: `electron/src/renderer/js/calendar-panel.js`

- [ ] 编辑时通过单条详情接口加载完整字段。
- [ ] 实现全天开关联动、起止日期同步与表单校验。
- [ ] 创建和更新请求发送 `end_time`、`all_day`、`repeat_type`、`remind_before`。
- [ ] 检查 IPC 返回的 HTTP 状态；失败时显示行内错误并保留弹窗。
- [ ] 保存时禁用按钮并显示“保存中…”，完成后恢复。

### Task 5: Electron 通知接入

**Files:**
- Modify: `electron/src/renderer/js/dynamic-island.js`
- Modify: `electron/src/main.js`
- Modify: `electron/src/preload.js`

- [ ] 监听 `calendar_reminder` 事件并加入现有通知列表。
- [ ] 通过受控 IPC 调用 Electron `Notification`，展示事件标题和时间。
- [ ] 对不支持系统通知的环境保留应用内通知，不静默丢失。

### Task 6: 端到端验证

**Files:**
- Test: `tests/test_calendar_manager.py`

- [ ] 运行 `python -m pytest tests/test_calendar_manager.py tests/test_calendar_tools.py -v`。
- [ ] 运行 `npm run check:all` 与 `npm run lint`。
- [ ] 使用带 `--remote-debugging-port` 的 Electron 启动项目。
- [ ] 用 agent-browser 检查添加弹窗、所有输入控件、开关、选择框、颜色、错误状态和编辑回填。
- [ ] 创建短时提醒事件，验证数据库记录、timeline 展开、应用内通知与系统通知链路。
