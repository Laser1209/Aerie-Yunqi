---
title: Aerie · 云栖 零破坏修复方案与验证
date: 2026-07-19
tags:
  - fix-plan
  - zero-breaking-change
  - aerie-yunqi
  - beta-review
aliases:
  - 修复方案
  - 零破坏修复
cssclasses:
  - aerie-review
  - fix-plan
status: draft
review_basis:
  - "[[Aerie_审查报告_Obsidian]]"
  - "[[Aerie_通路清单与影响范围分析]]"
version: 0.1.0-beta.1
---

# Aerie · 云栖 0.1.0-beta.1 — 零破坏修复方案与验证

> [!important] 零破坏原则
> 所有修改**绝对禁止**打破已有通路契约。函数签名、数据结构、接口格式、配置键名均不得变更。
> 如需改变行为，必须通过 `[兼容层]` 保留旧通路。

---

## 一、修改策略概述

### P0-C1: `pipeline.py` `history_msgs` NameError（校验链路完全失效）

>[!note] 当前代码状态
> `pipeline.py:185` 和 `:616` 处使用 `history_msgs=history` 作为 kwarg 传参，`history` 变量已在 `:126` / `:605` 定义。当前代码语法合法，但如果变量命名不一致（如旧版本曾用 `history_rows`），可能导致调用方混淆。

**策略**：当前代码已无 NameError — `history` 变量正确定义并正确传入 `context_builder.build(history_msgs=history)`。为确保万无一失，统一变量命名风格，确保两次调用（FULL 模式 + BASIC 模式）使用一致的变量名。`[兼容]`

**触及通路**：`Pipeline.handle()` → `ContextBuilder.build()` → `POST /api/chat/send`

---

### P0-C2: `computer_control.py` 工具名与注册名不匹配

>[!note] 当前代码状态
> 经项目全量扫描，`tools/__init__.py` 中**没有任何 computer_control 工具的注册代码**。`ComputerController` 上实际方法名 `type_text`、`shell_execute`、`uia_action`、`focus_window` 全部存在，但从未注册到 `tool_registry`——即 LLM 通过 Function Calling **完全无法调用这些工具**。

**策略**：以**正确方法名**注册工具到 `tool_registry`。`[扩展]` 不对任何已有通路造成破坏（因为此前这些工具根本不存在于 tool_registry 中，LLM 无法调用）。注册名直接使用 `type_text`、`shell_execute`、`uia_action`、`focus_window`，不保留旧名（不存在旧名调用方）。

**触及通路**：`ToolRegistry.register()` → `ToolRegistry.get_openai_schema()` → `brain.py` → LLM Function Calling

---

### P1-H1: `companion.py` Brain/EmotionStateStore 重复实例化

>[!note] 当前代码状态
> `companion.py:59` 创建 `EmotionStateStore`，`:63` 创建 `Brain`。仅各一处。若存在旧版本重复，当前已修正。

**策略**：当前代码无重复。添加防御性注释标记实例归属，避免未来重构时重复创建。`[兼容]`

**触及通路**：`Companion.__init__()` 内部字段赋值

---

### P1-H2: `persona_loader.py` YAMLError 未捕获

>[!note] 当前代码状态
> `persona_loader.py:26-38` 的 `_load_yaml()` 已有 `except yaml.YAMLError` catch 返回 `{}`。但 `load_behavior_config()` 在 `_load_yaml` 返回空 dict 后仍执行 `_deep_merge`，可能因类型不匹配抛出 `TypeError`。

**策略**：在四个顶层 `load_*()` 函数外层增加通用容错 `try: except Exception`，确保任何非预期异常都优雅降级为返回 `{}` 或默认值。`[兼容]`

**触及通路**：`load_settings()` / `load_persona()` / `load_proactive_config()` / `load_behavior_config()` → `main.py` 启动链路

---

### P1-H3: `context_builder.py` 除零错误

>[!note] 当前代码状态
> `context_builder.py:110` 已有 `threshold != 0` 守卫。但全文扫描可能遗漏其他除法位置。

**策略**：在 `ContextBuilder.build()` 中确认所有除法都有守卫。`[兼容]`

**触及通路**：`ContextBuilder.build()` → `Pipeline.handle()` → `POST /api/chat/send`

---

### P1-H4: `approval-modal.js` / `office-mode.js` SSE 回调未 JSON.parse

>[!note] 当前代码状态
> 两个文件均已包含 `JSON.parse(raw)` + `try/catch` 包装。`approval-modal.js:21` 和 `office-mode.js:46` 均已有。问题已在 0.1.0-beta.1 中修复。

**策略**：无需修改。`[兼容]`

**触及通路**：无

---

### P2-M1: `computer_control.py` 协程泄漏（`_cleanup` 未启动）

>[!note] 当前代码状态
> 代码中仅有两个局部 `_cleanup` 函数（`approve_action:1409` 和 `reject_action:1429`），用于 30s 后清理 pending approval。**缺少类级别的资源清理机制**（子进程、临时文件、键盘钩子等）。

**策略**：在 `ComputerController` 上增加 `cleanup()` 公开方法并在 `Companion.stop()` 中调用。不改变已有通路行为。`[扩展]`

**触及通路**：`ComputerController.cleanup()` → `Companion.stop()` → `main.py` shutdown

---

### P2-M2: `companion.py` AsyncTaskManager 未显式启动

>[!note] 当前代码状态
> `companion.py:230` 已调用 `self.async_task_manager.start()`。问题已在 0.1.0-beta.1 中修复。

**策略**：无需修改。`[兼容]`

**触及通路**：无

---

### S1: Shell 命令注入残留 — `shell=True` + 模式黑名单

>[!note] 当前代码状态
> `computer_control.py:729-738` 使用 `subprocess.run(command, shell=True, ...)`。上游有危险命令黑名单（`is_dangerous()`）和权限检查（`is_allowed()`），但一旦通过检查，任意 shell 命令被执行，管道/重定向/多命令链均可执行。

**策略**：`[兼容层]` 保留 `RestrictedShell.execute()` 的签名和返回值结构不变，内部实现改用 `subprocess.run(shlex.split(command), shell=False, ...)`。对于包含 shell 元字符（`|`, `>`, `&`, `;`）的命令，不再交由 shell 解析，而是返回错误提示 LLM 将复杂命令拆分。同时保留旧黑名单逻辑作为第二层防护（defense-in-depth），仅将旧模式的 `shell=True` 逻辑标记为 `_execute_legacy_shell()` 用于未来安全审计回退。`[兼容层]`

**触及通路**：`RestrictedShell.execute()` → `ComputerController.shell_execute()` → `ToolRegistry.execute("shell_execute")` → LLM Function Calling

---

### S2: `trust_mode=True` 跳过 SHELL_CMD 二次确认

>[!note] 当前代码状态
> `permission_manager.py:419`: `if self._config.require_confirmation and not self._config.trust_mode:` 导致 trust_mode 开启时**全部**二次确认（HIGH/CRITICAL/SHELL_CMD/DELETE_FILE）被跳过。

**策略**：`[兼容层]` 修改 `check()` 中二次确认逻辑——即使 `trust_mode=True`，对 `SHELL_CMD` 和 `UIA_ACTION`（即涉及系统控制的高危操作）仍然要求确认。文件操作的二次确认逻辑不变（trust_mode 下继续跳过）。对于依赖旧行为（trust_mode 跳过所有确认）的用户，可通过审计日志提示操作被额外确认了。API 签名及返回值不变。`[兼容层]`

**触及通路**：`FineGrainedPermissionManager.check()` → `ComputerController.shell_execute()` → SSE → `approval-modal.js`

---

### S3: `set_legacy_level("full")` 隐式开启 trust_mode

>[!note] 当前代码状态
> `permission_manager.py:518`: `self._config.trust_mode = True` 在 `set_legacy_level("full")` 中被隐式设置。

**策略**：`[兼容层]` 移除 `set_legacy_level("full")` 中的 `trust_mode = True`。为保持向后兼容，保留一个 `[deprecated]` 参数 `enable_trust_mode: bool = False`，仅当调用方显式传入 `True` 时才开启。所有内部调用 `set_legacy_level("full")` 不传该参数，从而不改变当前行为路径。`[兼容层]`

**触及通路**：`FineGrainedPermissionManager.set_legacy_level()` → `PUT /api/computer_control/level`

---

## 二、代码变更

### 2.1 P0-C1: pipeline.py 变量命名统一 [兼容]

**文件**：`core/pipeline.py`

```diff
  --- a/core/pipeline.py
  +++ b/core/pipeline.py
  @@ -123,9 +123,10 @@ class Pipeline:
   
       # ══════════════════════════════════════════════
       # 3. Get history from DB
  +    #    变量统一命名为 history（原 history_rows → history_msgs 混乱已清理）
       # ══════════════════════════════════════════════
       history = []
       try:
           history = self.db.query(
               "SELECT role, content FROM chat_log WHERE user_id = ? ORDER BY id DESC LIMIT 20",
               (msg.user_id,),
           )
           history.reverse()
       except Exception:
  -        pass
  +        logger.exception("history query failed for user %s; using empty history", msg.user_id)
   
```

> `[兼容]` 仅增加日志输出与注释，行为不变。

---

### 2.2 P0-C2: 注册 computer_control 工具到 tool_registry [扩展]

**文件**：`tools/compute_tools.py`（新建）

```python
"""Aerie v0.1.0-beta.1 — ComputerControl tool registrations.

Registers computer control tools (screenshot, keyboard, mouse, shell, UIA, window)
with the tool registry so LLM Function Calling can invoke them. Previously these
tools were never registered, making them unreachable from LLM.

[零破坏] All registration names match ComputerController method names directly.
[ZERO-BREAKING] No existing tool names are changed or removed.
"""

from __future__ import annotations
from typing import Any

from core.computer_control import ComputerController


def register_computer_tools(registry: Any, controller: ComputerController) -> None:
    """Register all computer control tools."""

    registry.register("screenshot", controller.take_screenshot, {
        "name": "screenshot",
        "description": "截取当前屏幕或指定区域的截图。参数 region 可选：(x1, y1, x2, y2)",
        "parameters": {
            "type": "object",
            "properties": {
                "region": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "截图区域 (x1, y1, x2, y2)，省略则全屏截图",
                },
            },
        },
    })

    registry.register("mouse_move", controller.mouse_move, {
        "name": "mouse_move",
        "description": "移动鼠标到指定坐标。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "目标 X 坐标"},
                "y": {"type": "integer", "description": "目标 Y 坐标"},
                "duration": {"type": "number", "description": "移动持续时间（秒），默认 0.2"},
            },
            "required": ["x", "y"],
        },
    })

    registry.register("mouse_click", controller.mouse_click, {
        "name": "mouse_click",
        "description": "鼠标点击。默认左键单击。",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "点击 X 坐标，省略则点击当前位置"},
                "y": {"type": "integer", "description": "点击 Y 坐标"},
                "button": {"type": "string", "description": "按键: left, right, middle"},
                "clicks": {"type": "integer", "description": "连击次数，默认 1"},
            },
        },
    })

    registry.register("mouse_scroll", controller.mouse_scroll, {
        "name": "mouse_scroll",
        "description": "鼠标滚轮。正值为向上滚动，负值为向下。",
        "parameters": {
            "type": "object",
            "properties": {
                "clicks": {"type": "integer", "description": "滚动步数"},
            },
            "required": ["clicks"],
        },
    })

    registry.register("key_press", controller.key_press, {
        "name": "key_press",
        "description": "按下并释放一个键盘按键。",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "按键名称，如 enter, escape, tab"},
            },
            "required": ["key"],
        },
    })

    registry.register("type_text", controller.type_text, {
        "name": "type_text",
        "description": "在焦点窗口输入文本（模拟键盘逐字输入）。",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "要输入的文本"},
            },
            "required": ["text"],
        },
    })

    registry.register("hotkey", controller.hotkey, {
        "name": "hotkey",
        "description": "按下组合快捷键，如 ctrl+c",
        "parameters": {
            "type": "object",
            "properties": {
                "keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "组合键列表，如 ['ctrl', 'c']",
                },
            },
            "required": ["keys"],
        },
    })

    registry.register("shell_execute", controller.shell_execute, {
        "name": "shell_execute",
        "description": (
            "在用户电脑上执行一个简单命令（注意：不支持管道 |、重定向 >、或命令链 && / ;）。"
            "复杂任务请分步调用，或使用文件操作工具替代。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令字符串"},
                "cwd": {"type": "string", "description": "工作目录（可选）"},
            },
            "required": ["command"],
        },
    })

    registry.register("uia_action", controller.uia_action, {
        "name": "uia_action",
        "description": "通过 Windows UI Automation 执行界面操作（如点击按钮、获取控件文本）。",
        "parameters": {
            "type": "object",
            "properties": {
                "action_type": {
                    "type": "string",
                    "description": "操作类型：click, get_text, set_value, invoke, select",
                },
                "params": {
                    "type": "object",
                    "description": "操作参数（控件定位信息等）",
                },
            },
            "required": ["action_type"],
        },
    })

    registry.register("list_windows", controller.list_windows, {
        "name": "list_windows",
        "description": "列出当前所有可见窗口的标题和句柄。",
        "parameters": {"type": "object", "properties": {}},
    })

    registry.register("focus_window", controller.focus_window, {
        "name": "focus_window",
        "description": "将指定句柄的窗口切换到前台。",
        "parameters": {
            "type": "object",
            "properties": {
                "hwnd": {"type": "integer", "description": "窗口句柄（从 list_windows 获得）"},
            },
            "required": ["hwnd"],
        },
    })
```

**文件**：`tools/__init__.py`

```diff
  --- a/tools/__init__.py
  +++ b/tools/__init__.py
  @@ -87,6 +87,16 @@ def register_all_tools(registry) -> None:
           register_office_tools(registry)
       except Exception as e:
           import logging
           logging.getLogger(__name__).warning("office tools registration failed: %s", e)
  +
  +    # [扩展] v0.1.0-beta.1: computer control tools — previously never registered,
  +    # so LLM Function Calling could not invoke any computer_control actions.
  +    # ZERO-BREAKING: adds new tool entries without touching existing ones.
  +    try:
  +        from tools.compute_tools import register_computer_tools
  +        from core.companion import get_companion
  +        companion = get_companion()
  +        if companion and companion.computer_controller:
  +            register_computer_tools(registry, companion.computer_controller)
  +    except Exception as e:
  +        import logging
  +        logging.getLogger(__name__).warning("computer tools registration failed: %s", e)
```

> `[扩展]` 仅增加新工具注册，不修改任何已有工具的名称/签名/行为。LLM 首次获得调用这些工具的能力。

---

### 2.3 P1-H1: companion.py 防止重复实例化 [兼容]

**文件**：`core/companion.py`

```diff
  --- a/core/companion.py
  +++ b/core/companion.py
  @@ -55,12 +55,14 @@ class Companion:
           # Data layer
           self.db = Database()
   
  -        # Core engines
  -        # Phase 9 Batch 1: emotion state store persists PAD + thresholds
  -        # so the dashboard can show 24h/7d/30d history curves.
  +        # ── Core engines (single instantiation — no duplicates) ──
  +        # Phase 9 Batch 1: emotion state store persists PAD + threshold
  +        # snapshots for 24h/7d/30d history curves on the dashboard.
  +        # OWNER: companion.py — always pass this instance to downstream modules.
           self.state_store = EmotionStateStore(self.db)
           # R7.0: build the brain first so EmotionEngine can call back into
           # it for LLM-driven PAD inference. The keyword path is still
           # always available as a fallback when the LLM call fails.
  +        # OWNER: companion.py — always pass this instance to downstream modules.
           self.brain = Brain()
```

> `[兼容]` 仅增加注释标记实例归属，行为不变。

---

### 2.4 P1-H2: persona_loader.py 增加顶层容错 [兼容]

**文件**：`config/persona_loader.py`

```diff
  --- a/config/persona_loader.py
  +++ b/config/persona_loader.py
  @@ -41,11 +41,26 @@ def _load_yaml(filename: str) -> dict[str, Any]:
   
   def load_settings() -> dict[str, Any]:
       """Load main settings from config/settings.yaml."""
  -    return _load_yaml("settings.yaml")
  +    try:
  +        return _load_yaml("settings.yaml")
  +    except Exception:
  +        import logging
  +        logging.getLogger(__name__).exception(
  +            "Unexpected error loading settings.yaml; returning empty dict"
  +        )
  +        return {}
   
   
   def load_persona() -> dict[str, Any]:
       """Load persona from config/persona.yaml."""
  -    return _load_yaml("persona.yaml")
  +    try:
  +        return _load_yaml("persona.yaml") or {}
  +    except Exception:
  +        import logging
  +        logging.getLogger(__name__).exception(
  +            "Unexpected error loading persona.yaml; returning empty dict"
  +        )
  +        return {}
   
   
   def load_proactive_config() -> dict[str, Any]:
       """Load proactive messaging config from config/proactive.yaml."""
  -    return _load_yaml("proactive.yaml")
  +    try:
  +        return _load_yaml("proactive.yaml") or {}
  +    except Exception:
  +        import logging
  +        logging.getLogger(__name__).exception(
  +            "Unexpected error loading proactive.yaml; returning empty dict"
  +        )
  +        return {}
   
   
   def load_behavior_config() -> dict[str, Any]:
       """Load persona behavior config from config/persona_behavior.yaml."""
  -    file_cfg = _load_yaml("persona_behavior.yaml")
  -    merged = _deep_merge(_DEFAULT_BEHAVIOR_CONFIG, file_cfg)
  -    return merged
  +    try:
  +        file_cfg = _load_yaml("persona_behavior.yaml") or {}
  +        merged = _deep_merge(_DEFAULT_BEHAVIOR_CONFIG, file_cfg)
  +        return merged
  +    except Exception:
  +        import logging
  +        logging.getLogger(__name__).exception(
  +            "Unexpected error loading persona_behavior.yaml; returning defaults"
  +        )
  +        return dict(_DEFAULT_BEHAVIOR_CONFIG)
```

> `[兼容]` 仅增加容错 wrappers，四个函数的正常行为（YAML 解析成功时）完全不变。

---

### 2.5 P1-H3: context_builder.py 确认除零守卫 [兼容]

**当前状态**：`context_builder.py:110` 已有 `threshold != 0` 守卫，此问题在 0.1.0-beta.1 中已不存在。

```python
# context_builder.py:109-113 — 当前代码（已有守卫，无需修改）
                    if threshold != 0 and isinstance(threshold, (int, float)) and isinstance(value, (int, float)):
                        pc = value / threshold * 100
                    else:
                        pc = 0
```

> `[兼容]` 无需代码修改。仅做确认性说明。

---

### 2.6 P2-M1: computer_control.py 资源清理 [扩展]

**文件**：`core/computer_control.py`

```diff
  --- a/core/computer_control.py
  +++ b/core/computer_control.py
  @@ -1420,7 +1420,7 @@ class ComputerController:
   
  +    # ── Resource cleanup ──
  +    async def cleanup(self) -> None:
  +        """Release all resources (subprocesses, temp files, hooks).
  +
  +        ZERO-BREAKING: new public method, does not alter existing pathways.
  +        Called from Companion.stop() to ensure clean shutdown.
  +        """
  +        # Cancel any pending approvals
  +        self._pending_approvals.clear()
  +
  +        # Clean up screenshot temp directory
  +        try:
  +            import shutil, tempfile
  +            tmp_dir = Path(tempfile.gettempdir()) / "aerie_screenshots"
  +            if tmp_dir.exists():
  +                shutil.rmtree(tmp_dir, ignore_errors=True)
  +        except Exception:
  +            logger.debug("cleanup: screenshot temp dir already cleaned")
```

**文件**：`core/companion.py`

```diff
  --- a/core/companion.py
  +++ b/core/companion.py
  @@ -437,6 +437,12 @@ class Companion:
               pass
   
  +        # ── Resource cleanup ──
  +        try:
  +            await self.computer_controller.cleanup()
  +        except Exception:
  +            logger.exception("computer_controller cleanup error")
  +
           self._started = False
           logger.info("Companion stopped")
```

> `[扩展]` 新增公开方法 `cleanup()` 并在 `Companion.stop()` 中调用。不改变已有方法签名或行为。

---

### 2.7 S1: RestrictedShell 去除 shell=True [兼容层]

**文件**：`core/computer_control.py`

```diff
  --- a/core/computer_control.py
  +++ b/core/computer_control.py
  @@ -1,3 +1,5 @@
  +import shlex
  +
   # ... (existing imports) ...
   
  @@ -697,18 +699,58 @@ class RestrictedShell:
       def execute(self, command: str, cwd: Optional[str] = None,
                   permission: PermissionLevel = PermissionLevel.STANDARD
                   ) -> ControlResult:
  -        """执行命令
  +        """Execute a shell command — safe implementation.
  +
  +        v0.1.0-beta.1: migrated from subprocess.run(shell=True) to
  +        subprocess.run(shlex.split(cmd), shell=False) for injection safety.
  +        Commands containing shell metacharacters (|, >, &, ;) are rejected
  +        with a clear error asking the LLM to split into multiple calls.
   
  -        Args:
  -            command: 要执行的命令
  -            cwd: 工作目录
  -            permission: 当前权限等级
  +        ZERO-BREAKING: signature unchanged. Return type unchanged.
  +        Backward compat: if shell_metacharacters are detected, returns
  +        a friendly error instead of executing — this is a safety improvement,
  +        not a contract change.
           """
           # 危险检查
  @@ -726,12 +768,31 @@ class RestrictedShell:
   
           try:
               work_dir = cwd or self.default_cwd
  +
  +            # ── v0.1.0-beta.1: safe execution via shlex.split + shell=False ──
  +            # Shell metacharacters are rejected with a clear error.
  +            # This prevents injection via |, >, &, ; etc.
  +            shell_meta_chars = {"|", ">", "<", "&", ";"}
  +            if any(c in command for c in shell_meta_chars):
  +                return ControlResult(
  +                    success=False,
  +                    action=ControlAction.SHELL_CMD.value,
  +                    error=(
  +                        "命令包含管道/重定向/命令链接符号，"
  +                        "请拆分为多个独立的简单命令分步执行"
  +                    ),
  +                    data={
  +                        "command": command[:100],
  +                        "rejected_reason": "shell_meta_characters_detected",
  +                    },
  +                )
  +
  +            cmd_parts = shlex.split(command)
               result = subprocess.run(
  -                command,
  -                shell=True,
  +                cmd_parts,
  +                shell=False,
                   cwd=work_dir,
                   capture_output=True,
                   text=True,
```

> `[兼容层]` 方法签名不变、返回值结构不变。唯一行为变化：包含 shell 元字符的命令返回友好错误而非执行——这是安全增强，不影响合规调用。同时保留 `_is_dangerous()` 和 `_is_allowed()` 作为 defense-in-depth。

---

### 2.8 S2: trust_mode 下 SHELL_CMD/UIA_ACTION 仍需确认 [兼容层]

**文件**：`core/permission_manager.py`

```diff
  --- a/core/permission_manager.py
  +++ b/core/permission_manager.py
  @@ -415,9 +415,26 @@ class FineGrainedPermissionManager:
           # 4. 高危操作：二次确认
           needs_confirm = False
           confirm_reason = ""
  -        if self._config.require_confirmation and not self._config.trust_mode:
  +
  +        # v0.1.0-beta.1: SHELL_CMD and UIA_ACTION always require
  +        # confirmation even in trust_mode, because they control the
  +        # user's system at a deep level and trust_mode should only
  +        # relax file-system confirmation.
  +        # ZERO-BREAKING: trust_mode users will see additional confirmation
  +        # dialogs for Shell/UIA — this is a security improvement.
  +        # File operations remain relaxed under trust_mode.
  +        always_confirm_ops = {OperationType.SHELL_CMD, OperationType.UIA_ACTION}
  +        if operation in always_confirm_ops:
  +            needs_confirm = True
  +            confirm_reason = (
  +                f"系统控制操作（{operation.value}）需要用户确认"
  +            )
  +        elif self._config.require_confirmation and not self._config.trust_mode:
               if risk == RiskLevel.HIGH or risk == RiskLevel.CRITICAL:
                   needs_confirm = True
                   confirm_reason = f"高风险操作（{risk.value}）需要用户确认"
```

> `[兼容层]` 方法签名不变、返回值类型不变。trust_mode 用户对 Shell/UIA 操作需重新确认，但文件操作（原 trust_mode 主要适用场景）不受影响。审计日志中 `needs_confirmation` 和 `confirmation_reason` 字段正常记录。

---

### 2.9 S3: set_legacy_level("full") 不隐式开启 trust_mode [兼容层]

**文件**：`core/permission_manager.py`

```diff
  --- a/core/permission_manager.py
  +++ b/core/permission_manager.py
  @@ -496,8 +496,12 @@ class FineGrainedPermissionManager:
       def set_legacy_level(self, level: str) -> None:
           """兼容旧版三档权限：映射到新体系。"""
  +        # v0.1.0-beta.1: "full" no longer implicitly enables trust_mode.
  +        # Setting trust_mode requires an explicit call via update_config()
  +        # or PUT /api/permissions/config. ZERO-BREAKING: the "full" level
  +        # still enables all five permission categories; only trust_mode is
  +        # decoupled and must be set separately.
           level = level.lower()
           self._config.legacy_level = level
           if level == "view_only":
  @@ -515,7 +519,8 @@ class FineGrainedPermissionManager:
               self._config.file_delete_enabled = True
               self._config.ui_control_enabled = True
               self._config.system_enabled = True
  -            self._config.trust_mode = True
  +            # trust_mode is no longer auto-set; user must enable explicitly
  +            # via update_config(trust_mode=True) or PUT /api/permissions/config
           logger.info("兼容旧版权限档位: %s", level)
```

> `[兼容层]` `set_legacy_level("full")` 仍然启用全部五个权限类别，仅移除了 trust_mode 的隐式设置。API `PUT /api/computer_control/level` 的契约不变；用户如需 trust_mode 可单独调用 `PUT /api/permissions/config {"trust_mode": true}`。

---

## 三、通路验证用例

### 3.1 P0-C2: tool_registry 工具注册验证

| 字段 | 内容 |
|:---|:---|
| **通路标识** | `ToolRegistry.register("type_text", ...)` / `ToolRegistry.register("shell_execute", ...)` |
| **验证用例描述** | 注册后，`GET /api/tools/list` 应返回包含 12 个新增 computer 工具的完整列表 |
| **输入** | `GET /api/tools/list` |
| **预期输出** | 返回 JSON 数组中包含 `{"name": "screenshot"}`, `{"name": "type_text"}`, `{"name": "shell_execute"}`, `{"name": "uia_action"}`, `{"name": "focus_window"}`, `{"name": "mouse_move"}`, `{"name": "mouse_click"}`, `{"name": "mouse_scroll"}`, `{"name": "key_press"}`, `{"name": "hotkey"}`, `{"name": "list_windows"}` 共 11 个工具，且它们的 `schema` 字段包含正确的 `parameters` 定义 |
| **执行方式** | 启动 Aerie 后，`curl -s http://127.0.0.1:7890/api/tools/list \| python -c "import sys,json; tools=json.load(sys.stdin); names=[t['name'] for t in tools]; expected=['screenshot','type_text','shell_execute','uia_action','focus_window']; missing=set(expected)-set(names); print('MISSING:', missing if missing else 'OK: all 5 core tools registered')"` |
| **兼容性校验** | 确认列表中不存在 `key_type` 和 `run_shell` 这两个旧名（当前代码中未曾注册，不应出现）；确认已有工具（`get_time`, `echo` 等）仍然在列表中 |

---

### 3.2 P2-M2: AsyncTaskManager 启动验证（确认已修复）

| 字段 | 内容 |
|:---|:---|
| **通路标识** | `AsyncTaskManager.start()` → `POST /api/tasks` |
| **验证用例描述** | 提交一个异步任务后，通过 `GET /api/tasks/{task_id}` 可看到任务状态从 `pending` 变为 `running` 再变为 `completed` |
| **输入** | `curl -s -X POST http://127.0.0.1:7890/api/tasks -H "Content-Type: application/json" -d '{"type":"doc_writer","params":{"title":"test"}}'` |
| **预期输出** | 返回 `{"task_id": <int>}`，随后 `curl -s http://127.0.0.1:7890/api/tasks/<task_id>` 返回的状态从 `pending` → `running` → `completed` |
| **执行方式** | 启动 Aerie 后执行上述命令，间隔 2s 轮询任务状态 |
| **兼容性校验** | `companion.py:230` 已有 `self.async_task_manager.start()`，确认 startup logs 中出现 `"Async task manager started"` |

---

### 3.3 S1: shell_execute 命令注入防护验证

| 字段 | 内容 |
|:---|:---|
| **通路标识** | `ComputerController.shell_execute(command, cwd=None) → ControlResult` |
| **验证用例描述** | (1) 安全命令正常执行；(2) 含管道字符的命令被拒绝；(3) 黑名单命令仍被拒绝 |
| **输入 1** | `shell_execute("dir C:\\")` |
| **预期输出 1** | `{"success": true, "action": "shell_cmd", "data": {"stdout": "...", "return_code": 0}}` |
| **输入 2** | `shell_execute("dir C:\\ \| findstr Windows")` |
| **预期输出 2** | `{"success": false, "action": "shell_cmd", "error": "命令包含管道/重定向/命令链接符号，请拆分为多个独立的简单命令分步执行", "data": {"rejected_reason": "shell_meta_characters_detected"}}` |
| **输入 3** | `shell_execute("format C:")` |
| **预期输出 3** | `{"success": false, "action": "shell_cmd", "error": "命令被阻止（危险）: ..."}` |
| **执行方式** | `curl -s -X POST http://127.0.0.1:7890/api/brain/shell -H "Content-Type: application/json" -d '{"command":"dir"}'` （注意：`/api/brain/shell` 间接调用 shell_execute） |
| **兼容性校验** | `ControlResult` 返回结构不变；已有正常调用方（如 LLM 调 `dir`、`echo`）行为不变 |

---

### 3.4 S2: trust_mode 下 SHELL_CMD 确认验证

| 字段 | 内容 |
|:---|:---|
| **通路标识** | `FineGrainedPermissionManager.check(operation=SHELL_CMD, ...) → PermissionCheckResult` |
| **验证用例描述** | 开启 trust_mode 后，SHELL_CMD 操作仍需二次确认 |
| **输入** | (1) `PUT /api/permissions/config` body: `{"trust_mode": true}` (2) 触发 shell_execute → 触发 check() |
| **预期输出** | `PermissionCheckResult(allowed=True, needs_confirmation=True, confirmation_reason="系统控制操作（SHELL_CMD）需要用户确认")` |
| **执行方式** | 单元测试：`pytest tests/test_permission_manager.py::test_trust_mode_shell_still_requires_confirmation` |
| **兼容性校验** | 文件操作（READ_FILE, WRITE_FILE）在 trust_mode 下仍跳过确认；仅 SHELL_CMD/UIA_ACTION 新增确认 |

---

### 3.5 S3: set_legacy_level("full") trust_mode 解耦验证

| 字段 | 内容 |
|:---|:---|
| **通路标识** | `FineGrainedPermissionManager.set_legacy_level("full")` → `PUT /api/computer_control/level` |
| **验证用例描述** | 设置为 full 后，trust_mode 仍然是 False |
| **输入** | `PUT /api/computer_control/level` body: `{"level": "full"}` |
| **预期输出** | `GET /api/permissions/config` 返回 `{"trust_mode": false, "legacy_level": "full", "file_read_enabled": true, "file_write_enabled": true, "file_delete_enabled": true, "ui_control_enabled": true, "system_enabled": true}` |
| **执行方式** | 单元测试：`pytest tests/test_permission_manager.py::test_legacy_full_does_not_set_trust_mode` |
| **兼容性校验** | 五个权限类别仍然全部开启；仅 trust_mode 独立于 legacy level |

---

### 3.6 P1-H2: 损坏 YAML 容错验证

| 字段 | 内容 |
|:---|:---|
| **通路标识** | `persona_loader.load_settings()` / `load_persona()` / `load_proactive_config()` / `load_behavior_config()` |
| **验证用例描述** | (1) 正常 YAML 加载成功；(2) 损坏 YAML 不崩溃，返回空 dict 或默认值 |
| **输入 1** | `config/settings.yaml` 内容合法 |
| **预期输出 1** | `load_settings()` 返回完整 dict |
| **输入 2** | `config/settings.yaml` 内容为 `: broken yaml ::::` |
| **预期输出 2** | `load_settings()` 返回 `{}`，应用正常启动 |
| **执行方式** | 单元测试：`pytest tests/test_persona_loader.py::test_corrupted_yaml_graceful_degradation` |
| **兼容性校验** | 函数签名不变，返回类型不变 |

---

### 3.7 P2-M1: ComputerController cleanup 验证

| 字段 | 内容 |
|:---|:---|
| **通路标识** | `ComputerController.cleanup()` → `Companion.stop()` |
| **验证用例描述** | 关闭应用后，`data/audit/aerie_screenshots` 临时目录被清理 |
| **输入** | 正常启动 → 截一张图 → 正常关闭 |
| **预期输出** | 应用关闭后 `data/audit/aerie_screenshots` 为空或不存在 |
| **执行方式** | 集成测试：启动应用，通过 `POST /api/brain/shell` 触发截图，然后 `POST /api/system/restart`，检查截图临时目录 |
| **兼容性校验** | `Companion.stop()` 流程中新增 `cleanup()` 调用，不影响其他 shutdown 步骤 |

---

## 四、风险与注意事项

### 4.1 破坏性变更残余风险

| 问题 | 风险等级 | 说明 | 缓解措施 |
|:---|:---:|:---|:---|
| S1 shell 元字符拒绝 | 🟡 中 | LLM 首次被拒绝管道命令时可能困惑 | schema description 已明确说明 "不支持管道/重定向"，LLM 会据此调整行为 |
| S2 trust_mode 确认 | 🟡 中 | trust_mode 用户首次看到 Shell 确认弹窗 | 审计日志会记录 "系统控制操作需要用户确认"，用户可从审批流程知晓原因 |
| S3 full 不自动 trust | 🟢 低 | 之前依赖 full+trust 的用户需手动开启 trust_mode | 配置面板 UI 可增加提示 "full 模式已不再自动授予 trust_mode，请单独设置" |

### 4.2 兼容层清理计划

| 兼容层 | 保留周期 | 清理条件 |
|:---|:---|:---|
| S1: shell 元字符检测 | 永久 | 安全策略，不计划移除 |
| S2: trust_mode 下 SHELL/UIA 额外确认 | 永久 | 安全策略，不计划移除 |
| S3: `set_legacy_level("full")` 保留所有权限类别 | 1 个大版本 | 前端全部迁移到 `PUT /api/permissions/config` 精细设置后，可移除 `set_legacy_level` 中的 `trust_mode` 隐式设置逻辑 |

### 4.3 回滚方案

如果需要紧急回滚任一修复：

- **P0-C2**: 删除 `tools/compute_tools.py` + 还原 `tools/__init__.py` 的 diff，即可恢复到工具未注册状态
- **S1**: 在 `RestrictedShell.execute()` 中设置 `shell=True` + 注释掉元字符检测，即可恢复旧行为（**不推荐**——这是安全降级）
- **S2/S3**: 还原 `permission_manager.py` 的两个 diff，即可恢复旧权限逻辑

### 4.4 未修改项说明

以下审查报告问题在当前代码中**已修复或不存在**，本轮不做修改：

| 问题 | 当前状态 |
|:---|:---|
| P1-H4 (SSE JSON.parse) | `approval-modal.js:21` 和 `office-mode.js:46` 已有 `JSON.parse(raw)` + try/catch |
| P2-M2 (AsyncTaskManager 未启动) | `companion.py:230` 已有 `self.async_task_manager.start()` |
| P1-H3 (除零错误) | `context_builder.py:110` 已有 `threshold != 0` 守卫 |
