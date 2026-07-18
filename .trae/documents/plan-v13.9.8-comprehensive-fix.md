# Aerie v0.1.0-beta.1 全项目综合修复方案

> 状态: 待执行 | 日期: 2026-07-18 | 基于全项目源码审查 + 4 个维度并行探索

---

## 一、审查总结

经过对项目 7 大维度（启动入口、LLM调用链、前后端连通性、Shell工具系统、模块初始化、配置文件加载、前端交互组件）的全面静态分析，共发现 **15 个确认 Bug**，按严重度分为三类：

| 严重度                          | 数量 | 影响                                                |
| ------------------------------- | ---- | --------------------------------------------------- |
| **Critical** (运行时崩溃) | 5    | 直接导致 NameError / AttributeError，功能完全不可用 |
| **High** (功能失效)       | 6    | 功能静默失效、资源配置浪费、启动潜在崩溃            |
| **Medium** (技术债务)     | 4    | 协程泄漏、死代码、审批绕过等安全隐患                |

---

## 二、已完成的修复（历史会话）

| # | 文件                         | 修改内容                                                                                         | 状态      |
| - | ---------------------------- | ------------------------------------------------------------------------------------------------ | --------- |
| 1 | `start-dev.bat:3`          | em dash`—` → ASCII hyphen `-`，解决编码乱码 `'ho' 不是内部或外部命令`                    | ✅ 已完成 |
| 2 | `electron/src/main.js:142` | `j.status === "ok"` → `j.status === "healthy" \|\| j.status === "degraded"`，解决后端离线误判 | ✅ 已完成 |

---

## 三、待修复 Bug 清单与方案

### Category A: Critical — 运行时必定崩溃

#### A1. pipeline.py:338 — `history_msgs` NameError

* **文件**: `core/pipeline.py`
* **位置**: 第 338 行
* **问题**: `context_history=history_msgs` 中 `history_msgs` 从未被定义为局部变量。`history_msgs` 仅在 185 行作为 `ctx_builder.build()` 的关键字形参名出现，Python 不会将其创建为变量。
* **后果**: FULL 路由模式下，每次走到 ResponseValidator 校验（第 8.5 步）必然 `NameError`，校验链路完全失效。
* **修复**:

```diff
-                        context_history=history_msgs,
+                        context_history=history,
```

#### A2. computer\_control.py:1425 — `self.key_type()` 方法不存在

* **文件**: `core/computer_control.py`
* **位置**: 第 1425 行
* **问题**: `_execute_action` 中调用 `self.key_type(params.get("text", ""))`，但 `ComputerController` 中该方法名为 `type_text`（定义在第 1163 行）。
* **后果**: 任何 KEY\_TYPE 操作必然 `AttributeError`。
* **修复**:

```diff
-            return self.key_type(params.get("text", ""))
+            return self.type_text(params.get("text", ""))
```

#### A3. computer\_control.py:1427 — `self.run_shell()` 方法不存在

* **文件**: `core/computer_control.py`
* **位置**: 第 1427 行
* **问题**: `_execute_action` 中调用 `self.run_shell(params.get("command", ""))`，正确方法名为 `shell_execute`（定义在第 1193 行）。
* **后果**: 任何 SHELL\_CMD 操作必然 `AttributeError`。
* **修复**:

```diff
-            return self.run_shell(params.get("command", ""))
+            return self.shell_execute(params.get("command", ""))
```

#### A4. computer\_control.py:1433 — `self.uia_action()` 方法不存在

* **文件**: `core/computer_control.py`
* **位置**: 第 1433-1436 行
* **问题**: `ComputerController` 类中没有任何 `uia_action` 方法。`UIAController` 类在第 873 行有 `execute()` 静态方法，但 `ComputerController` 未封装对其的调用。
* **后果**: 任何 UIA\_ACTION 操作必然 `AttributeError`。
* **修复**: 在 `ComputerController` 中添加 `uia_action` wrapper 方法：

```python
# 在 ComputerController 类中新增方法（放在 shell_execute 附近）
def uia_action(self, action_type: str, params: dict | None = None) -> ControlResult:
    """Execute a UIA action via UIAController."""
    if not self._pre_check(ControlAction.UIA_ACTION):
        return ControlResult(success=False, error="Permission denied: UIA_ACTION not allowed",
                             action=ControlAction.UIA_ACTION)
    try:
        result = UIAController.execute(action_type, params or {})
        self._audit(ControlAction.UIA_ACTION, params, result)
        return ControlResult(success=True, action=ControlAction.UIA_ACTION, data=result)
    except Exception as e:
        err = ControlResult(success=False, error=str(e), action=ControlAction.UIA_ACTION)
        self._audit(ControlAction.UIA_ACTION, params, err)
        return err
```

#### A5. computer\_control.py:1431 — `focus_window()` 参数类型错误

* **文件**: `core/computer_control.py`
* **位置**: 第 1431 行
* **问题**: `focus_window()` 签名是 `focus_window(self, hwnd: int)`，接受窗口句柄整数，但 `_execute_action` 传入了 `params.get("title", "")`（字符串）。
* **后果**: 类型不匹配，窗口聚焦逻辑不工作。
* **修复**: 先用 title 查找窗口句柄，再调用 focus\_window：

```diff
+            title = params.get("title", "")
+            hwnd = self._find_window_by_title(title) if title else 0
+            return self.focus_window(hwnd)
-            return self.focus_window(params.get("title", ""))
```

并在 `ComputerController` 中添加辅助方法：

```python
def _find_window_by_title(self, title: str) -> int:
    """Find a window handle by partial title match."""
    try:
        wins = WindowManager.list_windows()
        for w in wins:
            if title.lower() in w.get("title", "").lower():
                return w.get("hwnd", 0)
    except Exception:
        pass
    return 0
```

---

### Category B: High — 功能静默失效 / 资源浪费

#### B1. companion.py:501 — Brain 重复实例化

* **文件**: `core/companion.py`
* **位置**: 第 501 行
* **问题**: `_boot_brief()` 中 `await Brain().compose_brief(sections)` 创建了全新的 `Brain` 实例，不共享 `self.brain` 已初始化的 `_providers`、`_temperature` 等状态。
* **修复**:

```diff
-                md = await Brain().compose_brief(sections)
+                md = await self.brain.compose_brief(sections)
```

#### B2. companion.py:759 — EmotionStateStore 重复实例化

* **文件**: `core/companion.py`
* **位置**: 第 759 行
* **问题**: `_emotion_tick_loop()` 中每 60 秒创建新的 `EmotionStateStore(self.db)` 来调 snapshot，浪费资源且无法利用已有状态缓存。
* **修复**:

```diff
-                        EmotionStateStore(self.db).snapshot(
+                        self.state_store.snapshot(
```

并移除不再需要的 import：

```diff
-                        from core.emotion_state_store import EmotionStateStore
```

#### B3. persona\_loader.py:30-31 — YAMLError 未捕获

* **文件**: `config/persona_loader.py`
* **位置**: 第 30-31 行
* **问题**: `_load_yaml` 函数直接 `yaml.safe_load(f)` 无 try/except。如果 YAML 文件损坏（语法错误），将抛出 `yaml.YAMLError` 导致整个应用启动崩溃。该函数被 `load_settings()`、`load_persona()`、`load_proactive_config()`、`load_behavior_config()` 共用。
* **修复**:

```python
def _load_yaml(filename: str) -> dict[str, Any]:
    path = _CONFIG_DIR / filename
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError:
        import logging
        logging.getLogger(__name__).exception(
            "YAML parse error in %s; returning empty config", filename
        )
        return {}
```

#### B4. context\_builder.py:108 — 除零错误

* **文件**: `core/context_builder.py`
* **位置**: 第 108 行
* **问题**: `pc = info["value"] / info["threshold"] * 100` 中 `threshold` 可能为 0，且 `info` 的键可能缺失。
* **修复**:

```python
threshold = info.get("threshold", 1)
value = info.get("value", 0)
if threshold != 0 and isinstance(threshold, (int, float)) and isinstance(value, (int, float)):
    pc = value / threshold * 100
else:
    pc = 0
```

#### B5. approval-modal.js:19-21 — SSE 回调未 JSON.parse

* **文件**: `electron/src/renderer/js/approval-modal.js`
* **位置**: 第 19-21 行
* **问题**: `window.aerie.sse.subscribe` 回调接收的是**原始 JSON 字符串**，但代码中直接以对象方式访问 `ev.event` 和 `ev.data`，永远为 `undefined`。电脑控制审批实时弹窗完全失效。
* **修复**:

```javascript
this._sseUnsub = window.aerie.sse.subscribe((raw) => {
  let payload;
  try { payload = JSON.parse(raw); } catch (_) { return; }
  if (payload && payload.type === "computer_control_approval_requested") {
    this._onNewApproval(payload);
  }
});
```

#### B6. office-mode.js:43-49 — SSE 回调未 JSON.parse

* **文件**: `electron/src/renderer/js/office-mode.js`
* **位置**: 第 43-49 行
* **问题**: 与 B5 相同，`ev.event` / `ev.data` 永远为 `undefined`。办公模式实时切换 SSE 推送完全失效。
* **修复**:

```javascript
window.aerie.sse.subscribe((raw) => {
  let payload;
  try { payload = JSON.parse(raw); } catch (_) { return; }
  if (payload && payload.type === "office_mode_changed") {
    this._currentMode = (payload.mode) || "auto";
    this._updateButtonState();
  }
});
```

---

### Category C: Medium — 技术债务 / 安全隐患

#### C1. computer\_control.py:1376,1395 — 协程泄漏

* **文件**: `core/computer_control.py`
* **位置**: 第 1376、1395 行
* **问题**: `approve_action` 和 `reject_action` 中定义 `async def _cleanup()` 后从未执行（没有 `await` 或 `asyncio.create_task`），导致已处理审批条目永远不清理，内存泄漏。
* **修复**: 将 `_cleanup` 改为 `asyncio.create_task` 启动：

```diff
-            async def _cleanup():
+            async def _cleanup():
                 await asyncio.sleep(30)
                 self._pending_approvals.pop(call_id, None)
+            asyncio.create_task(_cleanup())
```

同样修复第 1395 行的另一处。

#### C2. companion.py — AsyncTaskManager 未显式启动

* **文件**: `core/companion.py`
* **位置**: `start()` 方法
* **问题**: `self.async_task_manager` 在 `__init__` 创建但 `start()` 方法中未调用 `self.async_task_manager.start()`。虽然 `api_server.py` 第 1507 行有按需延迟启动的守卫逻辑，但在 companion 层面不显式启动属于隐式依赖，不符合最佳实践。
* **修复**: 在 `companion.start()` 中添加启动：

```python
# 在 start() 方法的 "Phase 1: 基础设施启动" 段落末尾添加:
self.async_task_manager.start()
logger.info("Async task manager started")
```

#### C3-C4. computer\_control.py — 审批路径问题（非本次修复）

* `mouse_click`(1115行) 的审批分支在 STANDARD 模式下是死代码
* 高风险 SHELL\_CMD/UIA\_ACTION 不走审批流程
* **这些属于设计层面的功能增强，非 Bug 修复，不在本次范围内。留待后续专项处理。**

---

## 四、修复执行顺序

依赖关系：无循环依赖，可按文件独立并行修复。

### Phase 1: Critical 修复（必须优先）

1. `pipeline.py:338` — NameError 修复
2. `computer_control.py:1425-1436` — 4 个方法名/参数错误修复 + 新增 uia\_action wrapper + \_find\_window\_by\_title

### Phase 2: High 修复（功能保障）

1. `companion.py:501` + `companion.py:759` — 重复实例化修复
2. `persona_loader.py:30-31` — YAMLError 捕获
3. `context_builder.py:108` — 除零防护
4. `approval-modal.js:19-21` + `office-mode.js:43-49` — SSE JSON.parse 修复

### Phase 3: Medium 优化

1. `computer_control.py:1376,1395` — 协程启动
2. `companion.py:start()` — AsyncTaskManager 显式启动

---

## 五、验证步骤

修复完成后，按以下步骤验证：

1. **启动验证**: 双击 `start-dev.bat`，确认无编码乱码输出
2. **连接验证**: 主窗口正常显示，动态岛显示后端在线状态
3. **对话验证**: Web UI 发送消息，确认 AI 正常回复（FULL 模式校验链路恢复）
4. **配置验证**: 修改 `persona_behavior.yaml`，通过 `/api/system/reload-config` 热重载不掉
5. **工具验证**: 通过 API 调用 shell\_execute / type\_text / uia\_action，确认不报 AttributeError
6. **SSE 推送验证**: 修改办公模式，确认前端实时切换；触发审批请求，确认弹窗正常

---

## 六、假设与前置条件

* Python 环境 `.venv` 已正确安装所有依赖
* NapCat 可在端口 3001 正常运行
* `.env` 中 API Key 配置有效（main\_llm 至少有一个可用 Provider）
* 不引入新依赖，所有修复仅修改现有代码

---

## 七、参考

* 项目核心架构: Electron main → HTTP → Python FastAPI (127.0.0.1:7890)
* 消息通道: stderr `[CHAT_EVENT]` 管道 + SSE `/api/events/stream`（双层事件分发）
* SSE 数据格式: Python 端 `chat_events.emit()` → stderr + 内存总线 → FastAPI SSE endpoint → Electron `sse:subscribe` IPC → 前端 `window.aerie.sse.subscribe` 回调（接收原始 JSON 字符串）

<br />

## 八、版本更迭

当上述全部完成之后：以当前最新的功能状态 v0.1.0-beta.1为终点，重置为内测基准版本：


```
v0.1.0-beta.1
```

因为现在还属于内部开发阶段，所以说把此阶段作为beta版的第一个稳定版本，**后续严格按内测阶段的规范迭代**。
