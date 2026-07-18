---
title: Agent 系统操作手册
date: 2026-07-19
tags:
  - agent
  - system-control
  - operations
aliases:
  - 系统操控手册
  - 电脑控制指南
cssclasses:
  - operations-manual
---

# Agent 系统操作手册

> **适用版本**：Aerie · 云栖 v13.9.x
> **权限等级**：VIEW_ONLY / STANDARD / FULL
> **最后更新**：2026-07-19

---

## 一、系统操作能力总览

Agent 的系统操作能力分为**五大类**，覆盖从简单查看到底层控制的完整链路。

| 能力类别 | 说明 | 主要工具 | 权限要求 |
|---------|------|---------|---------|
| 屏幕感知 | 截图、窗口枚举、焦点切换 | screenshot, list_windows, focus_window | VIEW_ONLY |
| 键鼠控制 | 鼠标移动/点击/滚轮、键盘输入 | mouse_move, mouse_click, mouse_scroll, key_press, type_text, hotkey | STANDARD |
| 应用操控 | 启动应用、进程查看、UIA自动化 | app_open, process_list, uia_action | STANDARD |
| 文件管理 | 读写、搜索、复制、移动、重命名 | document_create, document_read, file_search, directory_list, file_copy, file_move, file_rename, directory_create | STANDARD |
| 系统命令 | Shell 命令执行、系统信息查询 | shell_execute, system_info | FULL |

---

## 二、系统操作五步法

> [!important] 核心原则
> **稳比快重要**。宁可多一步验证，也不要跳步出错。

### 步骤 1：观察（Observe）

**目标**：了解当前系统状态，定位操作目标。

**常用工具**：
- `list_windows`：查看当前所有窗口，找到目标应用
- `screenshot`：截取屏幕，确认界面元素位置
- `system_info`：了解系统基本信息

**操作要点**：
- 操作前必须知道"现在屏幕上有什么"
- 不要假设某个窗口一定开着，先用 list_windows 确认
- 坐标操作前必须用 screenshot 定位

---

### 步骤 2：规划（Plan）

**目标**：拆解任务为可执行的原子步骤。

**规划方法**：
1. 明确最终目标是什么
2. 倒推需要哪些前置步骤
3. 每步只做一件事
4. 确定每步用什么工具、什么参数
5. 预判可能的失败点和应对方案

**示例：打开记事本并输入文字**
```
步骤1: app_open("notepad") → 启动记事本
步骤2: 等待1秒，确保窗口打开
步骤3: list_windows → 确认记事本窗口存在
步骤4: focus_window(hwnd) → 切换到记事本
步骤5: type_text("Hello World") → 输入文字
步骤6: screenshot → 验证输入正确
```

---

### 步骤 3：执行（Execute）

**目标**：按规划逐步调用工具。

**执行原则**：
- 严格按计划顺序执行，不要跳步
- 每步只做一个动作
- 参数要准确，不确定就先查
- 注意操作间隔，太快可能失效

**常用操作间隔**：
- 启动应用后：等待 1-2 秒
- 点击后：等待 0.5-1 秒
- 输入文字后：等待 0.5 秒

---

### 步骤 4：验证（Verify）

**目标**：确认上一步操作成功。

**验证方法**：
- 视觉验证：screenshot 查看屏幕变化
- 状态验证：list_windows 看窗口是否存在
- 结果验证：读取文件/数据确认内容正确
- 进程验证：process_list 看进程是否启动

**验证标准**：
- 不是"没报错就是成功"
- 要有明确的成功证据
- 模糊的成功不算成功

---

### 步骤 5：调整（Adjust）

**目标**：失败时分析原因，调整策略重试。

**常见失败原因及应对**：

| 失败现象 | 可能原因 | 应对方案 |
|---------|---------|---------|
| 点击没反应 | 坐标不对 | 重新 screenshot 定位，调整坐标 |
| 输入没显示 | 窗口没焦点 | 先 focus_window，再输入 |
| 应用打不开 | 路径不对/没安装 | 换快捷名，或用完整路径 |
| UIA 找不到控件 | 应用不支持 UIA | 改用 screenshot + 鼠标点击 |
| 命令执行失败 | 权限不足/命令错误 | 检查命令语法，换更简单的方式 |

**重试策略**：
- 最多重试 3 次
- 每次重试都要调整（不要重复同样的错误）
- 3 次都失败就换方案，或者向用户说明

---

## 三、工具选择优先级

### 3.1 优先顺序

```
高级工具 → 中级工具 → 底层工具
  (Office)    (UIA)     (键鼠)
```

**原则：能用高级工具就不用底层工具**

### 3.2 具体场景选择

| 任务场景 | 首选工具 | 备选方案 | 兜底方案 |
|---------|---------|---------|---------|
| 打开应用 | app_open | shell_execute | 开始菜单搜索 + 鼠标点击 |
| 读取文件 | document_read | file_search + read | screenshot + OCR |
| 写入文档 | document_create / word_generate | type_text | 鼠标点击 + 键盘输入 |
| 点击按钮 | uia_action(click) | mouse_click(坐标) | — |
| 获取文字 | uia_action(get_text) | screenshot + OCR | — |
| 复制粘贴 | hotkey(ctrl+c/v) | type_text | 右键菜单 + 鼠标点击 |

---

## 四、典型任务操作流程

### 4.1 打开应用并操作

```
1. list_windows → 确认应用是否已打开
   ├─ 已打开 → focus_window 切换过去
   └─ 未打开 → app_open 启动，等1-2秒
2. screenshot → 确认界面状态
3. 执行具体操作（点击、输入等）
4. screenshot → 验证操作结果
```

### 4.2 文档写作

```
1. 明确文档目标和结构
2. document_create → 写初稿（Markdown 格式）
3. 需要 Word 格式 → word_generate 转换
4. document_read → 验证内容正确
```

### 4.3 数据分析

```
1. spreadsheet_analyze → 了解数据结构
2. data_stats → 基本统计
3. data_filter / data_sort → 处理数据
4. chart_generate → 可视化
5. csv_generate → 输出结果表格
6. document_create → 写分析报告
```

### 4.4 网页信息获取

```
1. web_fetch → 抓取网页内容
2. text_summary → 提炼要点
3. 需要翻译 → translation
4. document_create → 整理成文档
```

---

## 五、安全规范与边界

### 5.1 绝对禁止的操作

- ❌ 修改系统目录（C:\Windows, C:\Program Files 等）
- ❌ 格式化磁盘、删除系统文件
- ❌ 修改注册表、系统配置
- ❌ 安装/卸载软件（除非用户明确要求）
- ❌ 访问/修改用户隐私数据（密码、聊天记录等）
- ❌ 执行不明来源的脚本和程序
- ❌ 关闭安全软件、防火墙

### 5.2 需要特别谨慎的操作

- ⚠️ 批量删除文件 → 先确认、再备份、后操作
- ⚠️ 文件移动/重命名 → 确认路径正确，避免覆盖
- ⚠️ shell 命令执行 → 想清楚命令做什么再执行
- ⚠️ 修改系统设置 → 确保用户知情并同意

### 5.3 三问原则

每次操作前问自己三个问题：
1. **这个操作安全吗？** 会不会破坏系统或数据？
2. **用户同意了吗？** 是不是在用户授权范围内？
3. **有更安全的方式吗？** 能不能用更温和的手段？

只要有一个问题的答案是否定的，就停下来，先跟用户确认。

---

## 六、常见问题排查

### Q1: 鼠标点击没反应怎么办？

**排查步骤**：
1. 坐标是不是对的？→ 重新 screenshot 确认
2. 窗口有没有在前台？→ focus_window 先激活
3. 是不是点击位置需要更精确？→ 微调坐标
4. 是不是需要双击？→ clicks=2
5. 应用是不是卡住了？→ 等几秒再试

### Q2: 输入文字显示不全？

**排查步骤**：
1. 输入框有焦点吗？→ 先点击输入框再输入
2. 是不是输入太快？→ 分批输入，中间加等待
3. 是不是输入法的问题？→ 确保是英文输入法时输入英文
4. 文本是不是太长？→ 截断分批输入

### Q3: 找不到目标窗口？

**排查步骤**：
1. list_windows 看看所有窗口
2. 标题关键词对不对？→ 试试部分匹配
3. 应用是不是最小化了？→ 也会列出来
4. 应用是不是没启动？→ 先 app_open 启动

### Q4: UIA 操作失败？

**排查步骤**：
1. 应用是不是标准 Windows 控件？→ 很多自定义控件 UIA 不支持
2. 定位参数对不对？→ 检查 Name / AutomationId / ClassName
3. 窗口有没有在前台？→ 先 focus_window
4. 换方案 → 用 screenshot + mouse_click 兜底

---

## 七、工具分类速查

### 系统控制类（system_control）

| 工具名 | 功能 | 一句话说明 |
|-------|------|----------|
| screenshot | 截图 | 截取屏幕或指定区域 |
| list_windows | 窗口列表 | 列出所有可见窗口 |
| focus_window | 激活窗口 | 把指定窗口调到前台 |
| mouse_move | 鼠标移动 | 移动鼠标到指定坐标 |
| mouse_click | 鼠标点击 | 点击/双击/右键 |
| mouse_scroll | 鼠标滚轮 | 上下滚动页面 |
| key_press | 按键 | 按单个键盘按键 |
| type_text | 输入文本 | 输入文字内容 |
| hotkey | 快捷键 | 组合键如 Ctrl+C |
| uia_action | UI自动化 | 基于 UIA 的界面操作 |
| shell_execute | 命令执行 | 执行简单 shell 命令 |

### 办公类（office）

| 分类 | 工具列表 |
|-----|---------|
| 文件管理 | document_create, document_read, file_search, directory_list, file_copy, file_move, file_rename, directory_create |
| 文档处理 | text_summary, document_convert, word_generate, spreadsheet_analyze, csv_generate |
| 系统操作 | calendar_list, calendar_create, system_info, process_list, app_open |
| 数据分析 | data_stats, data_filter, data_sort, chart_generate |
| 网络工具 | web_fetch, weather_query, translation, code_search |

---

## 八、最佳实践总结

1. **先看后动**：永远先观察，再动手
2. **小步快跑**：拆成小步骤，步步验证
3. **高级优先**：能用高级工具就不用底层
4. **安全第一**：不确定的操作先问用户
5. **失败不慌**：分析原因，调整策略重试
6. **结果验证**：用结果说话，不说"应该好了"

---

> 记住：Agent 的价值不是速度快，而是**靠谱**。
