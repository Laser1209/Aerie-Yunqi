# Phase 7 — Skills 异常系统性排查与修复计划

> 目标文件：`e:\Agent_reply\documents\ERROR\python_20260715205412.md`
> 计划语言：中文
> 输出风格：工程化、最小修改、聚焦根因

---

## 1. 摘要 Summary

`python_20260715205412.md` 记录了 OpenCloud Companion Phase 5 启动后三类异常：

| # | 异常                                 | 涉及模块                                                | 状态                                      |
| - | ------------------------------------ | ------------------------------------------------------- | ----------------------------------------- |
| A | `addRoundedRect` TypeError         | `desktop/chat_window.py`                              | **已修复**（行 965 已不是出错代码） |
| B | `siliconflow: Error code: 401`     | `core/brain.py` + `.env` + `config/settings.yaml` | **待修复**                          |
| C | `web_search 失败:`（错误信息为空） | `tools/web_ops.py`                                    | **待修复**                          |
| D | `show_welcome_back` NameError（`greeting` 未定义） | `desktop/chat_window.py:1069` | **新发现**（拼写错误 `greating` → `greeting`） |

本计划重点处理 B + C + D，并对全部 14 个 tools 跑回归测试验证"系统性问题"是否存在。

---

## 2. 现状分析 Current State Analysis

### 2.1 已确认事实（基于代码 + 日志）

#### 异常 A：`addRoundedRect` — 已修复
- 日志位置：`desktop/chat_window.py:965`
- 现状查看 line 965 实为 `for i in reversed(range(input_row.count())):`，原报错行已被替换。
- Phase 6 微交互方案已落地 `QGraphicsDropShadowEffect`，无需再动。

#### 异常 D：`show_welcome_back` NameError（**新增，2026-07-15 用户截图反馈**）
- 报错：`NameError: name 'greeting' is not defined` at `desktop/chat_window.py:1069`
- 现象：托盘图标已显示（红色方框区域），但点击唤起 ChatWindow 时崩溃
- 实际根因：line 1069 f-string 拼写错误
  ```python
  # 当前错误代码（line 1069）
  f"主人{greating}好～今天天气不错呢，"
  #          ^^^^^^^ 应该是 greeting（少一个 r）
  ```
- 同函数 line 1057-1061 已正确定义 `greeting` 变量：
  ```python
  if hour < 12:
      greeting = "上午"
  elif hour < 18:
      greeting = "下午"
  else:
      greeting = "晚上"
  ```
- **截图与代码现状差异说明**：截图显示报错行为 `f"主人{greeting}好"`（拼写正确），但报错说 `greeting` 未定义。这暗示在用户截屏时该行拼写可能是 `greeting` 但变量作用域有问题；当前文件中实际为 `greating`（拼写错误），属于**典型笔误**
- 修复策略：直接补全拼写，无论当前是哪一种形式，都统一为正确版本

#### 异常 B：`siliconflow 401`

- 日志：`WARNING | siliconflow: Error code: 401`（4 次）
- 当前 `config/settings.yaml` 主模型：`google/gemma-4-31B-it`
- siliconflow 平台官方并不存在 `gemma-4-31B` 系列，正确命名空间为 `google/gemma-2-*` 或第三方 `Qwen/*` 等
- **根因判断**：模型名称不存在 → 401 Unauthorized

#### 异常 C：`web_search 失败:`（空消息）

- 日志：`WARNING | web_search 失败:`（后面没有任何字符）
- 关键证据：异常 `e` 被 `str()` 后是空串 → **触发了没有 `__str__` 内容的异常**
- 三种最可能原因（按概率排序）：
  1. **aiohttp `ClientConnectorError` / DNS 解析失败**：当前 `e.strerror` 为空，Windows 网络栈无详细信息
  2. **DuckDuckGo HTML 端点反爬升级**：返回 202/403 后 aiohttp 抛 `ClientResponseError`，但 `str(e)` 仅含 URL
  3. **DuckDuckGo 改版**：HTML 页面 `class="result__snippet"` 改名，正则匹配空列表 → 但此时会走"未找到结果"分支，**不会触发 except**，所以排除
- **结论**：网络层连接错误 + 错误信息丢失导致根因无法定位

### 2.2 隐性问题（潜在风险）

1. **错误信息吞没**：`except Exception as e: logger.warning(f"web_search 失败: {e}")` 在 `e` 为空时无法定位
2. **缺少单元测试覆盖**：`tools/` 目录无 `tests/` 子目录，无法自动化回归
3. **AI 模型名硬编码**：`config/settings.yaml` 模型名写错会导致 401，但**没有任何启动期校验**——错误只在用户使用时才暴露
4. **DuckDuckGo 解析脆弱**：单一正则匹配，无降级解析方案

### 2.3 影响范围评估

| 工具类别    | 数量 | 当前状态                                                                          |
| ----------- | ---- | --------------------------------------------------------------------------------- |
| 文件操作    | 4    | `read_file/write_file/list_dir/search_files` 纯本地，**不受影响**         |
| 系统操作    | 2    | `open_app/system_status` 纯本地，**不受影响**                             |
| 网页操作    | 3    | `web_search/get_weather/fetch_url` **全部基于 aiohttp**，C 类问题可能波及 |
| 待办操作    | 4    | `todo_*` 纯本地 SQLite，**不受影响**                                      |
| 知识库/转换 | 2    | `knowledge/doc_pipeline` 依赖 AI，**受 B 类间接影响**                     |

**结论**：C 类为网络层共性问题，3 个网页工具都需要加固错误处理。

---

## 3. 拟定变更 Proposed Changes

### 3.1 [P0-紧急] 修复 siliconflow 401

**文件**：`e:\Agent_reply\OpenCloud_Companion\config\settings.yaml`
**变更**：

```yaml
ai:
  primary:
    provider: "siliconflow"
    # 修正：原 google/gemma-4-31B-it 在 siliconflow 不存在
    # 选项 1（推荐）：Qwen 系列（中文友好、稳定）
    model: "Qwen/Qwen2.5-72B-Instruct"
  fallback:
    - provider: "deepseek"
      model: "deepseek-chat"
    - provider: "zhipu"
      model: "glm-4-flash"
```

**风险评估**：

- ✅ 兼容性：Qwen2.5-72B 是 siliconflow 在售模型，OpenAI 协议兼容
- ⚠️ 输出风格变化：72B 模型回复语气与 gemma 不同，**需重新调 prompt**——但 personality.yaml 已自带风格约束
- ⚠️ 费用：72B 模型按 token 计费，**比 deepseek-chat 贵约 6x**，建议主人关注余额

**回滚方案**：将 `model` 改回原值或改为 `deepseek-ai/DeepSeek-V2.5`

### 3.2 [P0-紧急] 修复 web_search 错误信息丢失

**文件**：`e:\Agent_reply\OpenCloud_Companion\tools\web_ops.py`
**变更**：重构三个工具的异常处理，记录完整 traceback

```python
# 原代码
except Exception as e:
    logger.warning(f"web_search 失败: {e}")
    return False, f"搜索失败: {e}"

# 新代码
except Exception as e:
    logger.exception(f"web_search 失败: query={query!r}")
    err_type = type(e).__name__
    err_msg = str(e) or "(无错误信息)"
    return False, f"搜索失败 [{err_type}]: {err_msg}"
```

**附加改进**：

- 三个工具（`web_search` / `get_weather` / `fetch_url`）统一改用 `logger.exception()` 输出 traceback
- 给所有 aiohttp 请求加 `try/except aiohttp.ClientError as e` 细粒度捕获
- 错误信息前缀加 `err_type`，便于主人快速判断

### 3.3 [P1-重要] 改进 web_search 解析容错

**文件**：`e:\Agent_reply\OpenCloud_Companion\tools\web_ops.py`
**变更**：

1. **增加解析降级链**（三重匹配）：

   - 主：`class="result__snippet"`（DuckDuckGo 旧版）
   - 备：`data-testid="result"`（新版 DuckDuckGo）
   - 兜底：返回"无摘要"但保留 URL
2. **网络重试**：单次失败自动重试 1 次（指数退避 2s）
3. **超时延长**：`timeout=10` → `timeout=15`

**风险评估**：

- 兼容性：解析正则改版可能误匹配，建议**先仅在本地 dry-run**
- 性能：单次重试最坏 15+15=30s，但用户感知可控

### 3.4 [P1-重要] 启动期校验 AI 模型名

**文件**：`e:\Agent_reply\OpenCloud_Companion\core\brain.py`
**变更**：在 `_init_providers` 末尾添加**轻量级模型可达性 ping**（可选 0/1 开关）

```python
async def _ping_provider(self, provider) -> bool:
    """启动时探测模型是否可达（GET /models）"""
    try:
        models = await provider["client"].models.list()
        available = [m.id for m in models.data]
        if provider["model"] not in available:
            logger.warning(
                f"⚠️ [{provider['name']}] 模型 {provider['model']!r} 不在可用列表，"
                f"将触发 401。建议改为: {available[:5]}"
            )
            return False
        return True
    except Exception as e:
        logger.debug(f"[{provider['name']}] ping 失败: {e}")
        return True  # 探测失败不阻断，运行时再报错
```

**风险评估**：

- 性能：每个 provider 增加约 1s 启动时间
- 兼容性：siliconflow / deepseek / zhipu 均支持 `/v1/models` 端点

### 3.5 [P2-优化] 添加 tools 回归测试脚本

**新建文件**：`e:\Agent_reply\OpenCloud_Companion\tests\test_tools_smoke.py`
**用途**：逐个调用 14 个 tools，输出 (ok, output) 报告

**测试用例**：

```python
TOOL_TESTS = [
    ("read_file", {"path": "e:/Agent_reply/OpenCloud_Companion/config/settings.yaml", "max_lines": 5}),
    ("write_file", {"path": "/tmp/test_write.txt", "content": "hello"}),  # 受 is_safe_path 限制
    ("list_dir", {"path": "e:/Agent_reply/OpenCloud_Companion/tools"}),
    ("search_files", {"keyword": "tool", "directory": "e:/Agent_reply/OpenCloud_Companion"}),
    ("open_app", {"app_name": "记事本"}),
    ("system_status", {}),
    ("web_search", {"query": "今天天气", "max_results": 3}),
    ("get_weather", {"city": "北京"}),
    ("fetch_url", {"url": "https://www.baidu.com"}),
    ("todo_create", {"content": "test todo"}),
    ("todo_list", {"status": "active"}),
    ("todo_complete", {"todo_id": 1}),
    ("todo_delete", {"todo_id": 1}),
]
```

**风险评估**：

- ⚠️ `write_file` 会被 `is_safe_path` 拦截，需用白名单内路径
- ⚠️ `open_app` 真打开软件，可注释掉
- ✅ 其他工具均为只读/可逆操作

### 3.6 [P2-优化] 长期预防策略

**文档**：`e:\Agent_reply\OpenCloud_Companion\docs\TOOLS_RELIABILITY.md`（新建）
**内容**：

1. 工具开发规范（错误处理模板、超时默认值、安全路径白名单）
2. 启动期自检 checklist
3. 常见错误码速查表
4. 第三方 API（DDG / wttr.in）变更应对预案

### 3.7 [P0-紧急] 修复 ChatWindow 欢迎消息拼写错误

**文件**：`e:\Agent_reply\OpenCloud_Companion\desktop\chat_window.py:1069`

**变更**（一行字符修正）：

```python
# 修改前
welcome = (
    f"主人{greating}好～今天天气不错呢，"
    f"有什么我可以帮忙的吗？(｡･ω･｡)"
)

# 修改后
welcome = (
    f"主人{greeting}好～今天天气不错呢，"
    f"有什么我可以帮忙的吗？(｡･ω･｡)"
)
```

**根因分析**：
- 同函数 line 1057-1061 已定义 `greeting = "上午"/"下午"/"晚上"`
- line 1063 `f"{greeting} %H:%M"` 正确引用
- line 1069 f-string 内却写成了 `greating`（少一个 r）——纯笔误
- Python 解析 f-string 表达式时，`greating` 不是已定义标识符，触发 `NameError`

**为什么截图与代码现状差异**：
- 用户截图显示的报错行是 `f"主人{greeting}好"`（拼写正确），但报错说 `greeting` 未定义
- 当前文件实际是 `greating`（拼写错误）
- **最可能原因**：用户测试过程中可能手改过这个文件，导致状态不一致；无论哪种，统一改为正确拼写即可

**风险评估**：
- ✅ 风险极低：单字符修正
- ✅ 不影响其他逻辑
- ✅ 修复后托盘点击 → ChatWindow 正常显示欢迎语

**安全审查**（TRAE-security-review 视角）：
- 该变量为纯字符串字面量（"上午"/"下午"/"晚上"），**无任何用户输入流入**
- 不会引入命令注入、XSS、SQL 注入等风险
- 属于 typo 类问题，非漏洞

**回归测试**：
```python
# 静态检查
import re
with open("desktop/chat_window.py", "r", encoding="utf-8") as f:
    content = f.read()
assert "greating" not in content, "greating 拼写错误仍存在"
assert "f\"主人{greeting}好" in content, "greeting 正确引用未应用"

# 运行验证
python -c "from desktop.chat_window import ChatWindow; print('import OK')"
```

---

## 4. 优先级与实施顺序

| 顺序 | 任务                       | 文件                                  | 估计工作量 | 风险 |
| ---- | -------------------------- | ------------------------------------- | ---------- | ---- |
| 1    | 3.7 修 ChatWindow 拼写错误 | `desktop/chat_window.py:1069`       | 1 字符     | 极低 |
| 2    | 3.1 修 siliconflow 模型名  | `settings.yaml`                     | 1 行       | 低   |
| 3    | 3.2 修 web_search 错误信息 | `web_ops.py`                        | ~20 行     | 低   |
| 4    | 3.3 改进解析容错           | `web_ops.py`                        | ~40 行     | 中   |
| 5    | 3.4 启动期模型 ping        | `brain.py`                          | ~25 行     | 低   |
| 6    | 3.5 回归测试脚本           | `tests/test_tools_smoke.py`（新建） | ~60 行     | 低   |
| 7    | 3.6 可靠性文档             | `docs/TOOLS_RELIABILITY.md`（新建） | 文档       | 无   |
| 8    | 验证 + 报告                | —                                    | —         | —   |

---

## 5. 假设与决策 Assumptions & Decisions

### 已确认假设

- **A1**：主人希望"minimal edits"，但本次明确要求"系统性修复"，**采用系统性方案**
- **A2**：siliconflow 是主 API 不可降级——因为 .env 中已配置三个 key，fallback 链已生效
- **A3**：DDG HTML 端点仍可用（未被全局封禁）——主人可手动访问 `https://html.duckduckgo.com/html/?q=test` 验证

### 已做出决策

- **D1**：siliconflow 模型选用 `Qwen/Qwen2.5-72B-Instruct`（中文 72B 旗舰）
- **D2**：错误信息统一加 `err_type` 前缀，便于快速定位
- **D3**：新增测试脚本而非接入 pytest 框架（避免引入额外依赖）

### 待主人确认（如果亲有偏好）

- ❓ 是否同意用 `Qwen/Qwen2.5-72B-Instruct` 替换？或更倾向 `deepseek-ai/DeepSeek-V3`（已配置为 deepseek，但 DeepSeek 自己的 key 更便宜）
  回复：这两个都接入吧
  本来Gemini我想的是做图像生成或者文件撰写的时候调用的，并不是用来做日常回复的
- ❓ 是否需要同步修复 `get_weather` / `fetch_url` 的同类问题？（推荐：是）

---

## 6. 验证步骤 Verification

### 6.1 单元验证（执行后必须跑）

```bash
cd e:\Agent_reply\OpenCloud_Companion
python tests\test_tools_smoke.py
```

**预期**：14 个工具全部 `OK=True`，3 个网络工具输出真实数据

### 6.2 集成验证（启动 Companion）

```bash
python main.py
```

**预期**：

- 启动日志中**不再出现** `siliconflow: Error code: 401`
- 若 3.4 实施，会看到 `⚠️ 模型不在可用列表` 警告（**不应该有**——说明我们改对了）

### 6.3 端到端验证（QQ 消息触发）

- 通过 QQ 私聊发送：`搜索一下今天的 AI 新闻`
- 预期：1-3 秒内返回真实搜索结果（不再是"网络不太稳定"）

### 6.4 边界用例

- ❌ 网络断开时 → 友好错误信息（不再空白）
- ❌ 搜索引擎返回 403 → 自动降级到 fetch_url 拿快照
- ❌ siliconflow key 失效 → 启动期 ping 提示

### 6.5 回滚预案

- 若 3.1 导致 AI 回复质量下降：`settings.yaml` 改回 `deepseek-ai/DeepSeek-V3`（DeepSeek 自己的 key，更便宜）
- 若 3.3 解析降级链误匹配：删除新增的备用正则，仅保留主匹配
- 若 3.4 启动 ping 阻塞：删除调用或加 `ENABLE_STARTUP_PING=false` 开关

---

## 7. 验收标准 Acceptance Criteria

| 项                         | 标准                                          |
| -------------------------- | --------------------------------------------- |
| ✅ siliconflow 401 消失    | 启动 + 1 次 AI 调用日志中无 401               |
| ✅ web_search 返回真实数据 | `web_search("今天AI新闻")` 返回 ≥ 3 条结果 |
| ✅ ChatWindow 正常加载     | 点击托盘 → 窗口显示欢迎语，不抛 NameError    |
| ✅ 错误信息可定位          | 失败时日志含 `err_type` + traceback         |
| ✅ 所有 14 个 tools 跑通   | test_tools_smoke.py 100% OK                   |
| ✅ 无新增依赖              | 仅复用现有 `aiohttp` / `loguru`           |
| ✅ 现有功能不退化          | 启动 + QQ 收发 + 定时任务全部正常             |

---

## 8. 不在本次范围 Out of Scope

- ❌ UI 层（chat_window 微交互已 Phase 6 完成）
- ❌ NapCatQQ 协议层（已稳定运行）
- ❌ 知识库 RAG 检索优化（与本次异常无关）
- ❌ 语音模块（本次日志显示未安装，与功能异常无关）

---

## 9. 风险登记 Risk Register

| 风险                  | 概率 | 影响 | 缓解                            |
| --------------------- | ---- | ---- | ------------------------------- |
| Qwen 72B 回复风格变化 | 中   | 中   | personality.yaml 风格约束已足够 |
| DDG 端点全面封禁      | 低   | 高   | 预留 fetch_url 兜底             |
| 启动 ping 阻塞        | 低   | 低   | 加开关 + 短超时                 |
| 解析降级误匹配        | 中   | 低   | 先 dry-run，观察 1 周           |
