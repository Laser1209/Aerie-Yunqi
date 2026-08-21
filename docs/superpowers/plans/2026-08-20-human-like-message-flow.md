# 真人式消息流优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让伊塔的普通回复与主动消息从“动作/思考标签 + 机械定时 + 成品文案切段”变成“纯对话、有具体触发、有证据引用、有认知推进的真人式消息流”。

**Architecture:** 先从 Persona/Prompt 源头关闭 `<action>` / `<thought>` 产出协议，再在输出出口保留标签剥离兜底，随后用“聊天意图单元”替代动作标签驱动的分段。普通回复与主动消息共用同一套纯对话分段质量规则，但主动消息保留独立的触发、频控和落库路径。

**Tech Stack:** Python 3、pytest、现有 `communication.splitter`、`core.llm_caller`、`core.companion`、`core.push_scheduler`、`core.context_builder`，不新增第三方依赖。

---

## 问题总结

1. 标签协议污染真人感：`<action>` / `<thought>` 会诱导模型输出舞台提示、内心独白和屏幕动作，破坏纯聊天气泡质感。
2. 主动消息节奏机械：`22:30`、`23:30`、`12:30` 这类整点/半点触发过强，像 cron 定时任务，不像人突然想起。
3. 上下文引用不可靠：`你发来的两个字` 这类强引用如果没有真实历史证据，会像幻觉式共同记忆。
4. 分段动机不自然：真人记录里的碎片感来自“反应 → 修正 → 补充 → 追问”的认知推进；当前 Agent 更容易把完整文案按句子切成多条。

## 需要修改的文件

- **Modify** `core/llm_caller.py` — 主动消息 prompt、候选解析、主动消息质量门槛。
- **Modify** `communication/splitter.py` — 新增真人式消息单元重组，避免成品文案硬切分。
- **Modify** `core/pipeline.py` — 普通回复使用新的分段质量规则，流式与非流式保持一致。
- **Modify** `communication/send_queue.py` — QQ 出口复用分段质量规则，避免二次切分制造碎片。
- **Modify** `core/companion.py` — 主动消息派发前做质量校验、证据约束和可选多段落库。
- **Modify** `core/push_scheduler.py` — cron 触发时间增加自然化 jitter，避免整点/半点机械外观。
- **Modify** `core/context_builder.py` — 移除动作/心理标签产出协议，加入“纯对话 + 真人分段动机”规则。
- **Modify** `config/persona.yaml` — 移除旧 Persona 配置里的 `<action>` / `<thought>` 输出要求。
- **Modify** `data/personas/*.json` — 关闭 PersonaHub 中 `action_tags` / `thought_tags`，同步移除 prompt override 里的标签规则。
- **Modify** `config/proactive.yaml` — 将静态整点 cron 和模板改为更弱的锚点提示，减少模板引导。
- **Create** `tests/test_human_message_flow.py` — 覆盖分段、主动消息质量、引用证据、时间自然化。

---

### Task 0: 关闭动作与心理标签产出协议

**Files:**
- Modify: `core/context_builder.py`
- Modify: `config/persona.yaml`
- Modify: `data/personas/yita_default.json`
- Modify: `data/personas/custom.json`
- Test: `tests/test_human_message_flow.py`

- [ ] **Step 1: 写失败测试**

```python
from core.context_builder import ContextBuilder


def test_language_prompt_forbids_action_and_thought_tags():
    builder = ContextBuilder()
    text = builder._build_l4_language({
        "personality": {"speech_style": "直接、自然、像真人聊天"},
        "behavior": {"action_tags": False, "thought_tags": False, "screen_aware": True},
    })
    assert "<action>" not in text
    assert "<thought>" not in text
    assert "不要输出动作描写" in text
    assert "不要输出心理活动" in text
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/test_human_message_flow.py -q
```

Expected: 当前 prompt 仍可能包含动作标签规则或缺少纯对话禁令。

- [ ] **Step 3: 修改 `core/context_builder.py`**

把 `_build_l4_language` 中的消息结构约定从“允许 action/thought 标签”改为纯对话规则：

```python
        text += "\n**纯对话输出铁律**：\n"
        text += "- 只输出会真正发进聊天气泡里的话。\n"
        text += "- 不要输出动作描写，不要输出心理活动，不要输出舞台提示。\n"
        text += "- 绝不使用 <action>、</action>、<thought>、</thought> 标签。\n"
        text += "- 想表达状态时，把它变成一句自然聊天，例如：'我刚刚切青柠溅了一手汁，突然就想你了。'\n"
```

- [ ] **Step 4: 修改 Persona 配置**

在 `config/persona.yaml`、`data/personas/yita_default.json`、`data/personas/custom.json` 中将运行时人设的标签开关改为：

```yaml
action_tags: false
thought_tags: false
```

JSON 文件中对应改为：

```json
"action_tags": false,
"thought_tags": false
```

同时删除 `prompt_overrides.system_prompt` 或旧 `system_prompt` 中要求使用 `<action>` / `<thought>` 的句子。

- [ ] **Step 5: 保留出口兜底剥离**

不要删除 `qq_client.py`、`pipeline.py`、`content_validator.py` 里的标签剥离逻辑。它们从“正常协议”降级为“异常兜底”，用于防止模型偶发回显标签。

- [ ] **Step 6: 运行配置与 prompt 测试**

```powershell
python -m pytest tests/test_human_message_flow.py tests/test_context_builder.py tests/test_strip_thought_action.py -q
```

Expected: 新 prompt 不再鼓励标签，旧出口剥离测试仍通过。

---

### Task 1: 建立真人式分段契约

**Files:**
- Create: `tests/test_human_message_flow.py`
- Modify: `communication/splitter.py`

- [ ] **Step 1: 写失败测试**

```python
from communication.splitter import SemanticMessageSplitter


def test_keeps_cognitive_progression_segments():
    splitter = SemanticMessageSplitter(max_len=80)
    text = "那个\n职业大赛那个\n明天一定要去吗"
    assert splitter.split_chat_units(text) == ["那个", "职业大赛那个", "明天一定要去吗"]


def test_merges_fragments_without_independent_intent():
    splitter = SemanticMessageSplitter(max_len=80)
    text = "欧克欧克，或者你有空的时候\n告诉我也行"
    assert splitter.split_chat_units(text) == ["欧克欧克，或者你有空的时候告诉我也行"]


def test_drops_legacy_action_tags_when_model_leaks_them():
    splitter = SemanticMessageSplitter(max_len=120)
    text = "<action>把手机举到眼前，眯着眼笑</action>\n刚切开一颗青柠，汁水溅到手背上——你猜我下一句想说什么？"
    assert splitter.split_chat_units(text) == [
        "刚切开一颗青柠，汁水溅到手背上——你猜我下一句想说什么？"
    ]
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/test_human_message_flow.py -q
```

Expected: `AttributeError: 'SemanticMessageSplitter' object has no attribute 'split_chat_units'`。

- [ ] **Step 3: 实现 `split_chat_units`**

在 `communication/splitter.py` 的 `SemanticMessageSplitter` 中新增方法：

```python
    def split_chat_units(self, text: str) -> list[str]:
        cleaned = self._strip_legacy_tags(str(text or ""))
        parts = [p.strip() for p in cleaned.splitlines() if p.strip()]
        if not parts:
            return []
        units: list[str] = []
        for part in parts:
            if units and self._should_merge_chat_unit(units[-1], part):
                units[-1] = units[-1] + part
            else:
                units.append(part)
        normalized: list[str] = []
        for unit in units:
            normalized.extend(self.split(unit) if len(unit) > self.max_len else [unit])
        return [u.strip() for u in normalized if u.strip()]

    @staticmethod
    def _should_merge_chat_unit(previous: str, current: str) -> bool:
        if len(current) < _MIN_FRAGMENT_LEN and not current.endswith(("。", "！", "？", "!", "?")):
            return True
        if previous.endswith(("，", "、", "；", ",", ";")):
            return True
        return False

    @staticmethod
    def _strip_legacy_tags(text: str) -> str:
        text = re.sub(r"<thought>.*?</thought>", "", text, flags=re.S)
        text = re.sub(r"<action>.*?</action>", "", text, flags=re.S)
        return text
```

- [ ] **Step 4: 运行 splitter 相关测试**

```powershell
python -m pytest tests/test_human_message_flow.py -q
python tests/e2e/e2e_splitter_atomic.py
```

Expected: 新测试通过，原 atomic splitter 验证通过。

---

### Task 2: 主动消息输出结构与质量门槛

**Files:**
- Modify: `core/llm_caller.py`
- Test: `tests/test_human_message_flow.py`

- [ ] **Step 1: 写失败测试**

```python
from core.llm_caller import LLMCaller


def test_pick_best_candidate_strips_legacy_action_line():
    text = "<action>把手机举到眼前，眯着眼笑</action>\n刚切开青柠，突然想问你现在在干嘛。"
    assert LLMCaller._pick_best_candidate(text) == "刚切开青柠，突然想问你现在在干嘛。"


def test_pick_best_candidate_keeps_multiline_message_package():
    text = '[{"messages":["欸。", "我刚刚突然想到你。", "你现在是不是又在硬撑？"]}]'
    assert LLMCaller._pick_best_candidate(text) == "欸。\n我刚刚突然想到你。\n你现在是不是又在硬撑？"
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/test_human_message_flow.py -q
```

Expected: 当前 `_pick_best_candidate` 会返回 action-only 行，且不支持对象数组里的 `messages` 包。

- [ ] **Step 3: 修改候选解析**

在 `core/llm_caller.py` 中调整 `_pick_best_candidate`：

```python
    @staticmethod
    def _candidate_visible_text(value: object) -> str:
        if isinstance(value, dict):
            messages = value.get("messages")
            if isinstance(messages, list):
                return "\n".join(str(x).strip() for x in messages if str(x).strip())
            text = value.get("text") or value.get("content")
            return str(text or "").strip()
        return str(value or "").strip()

    @staticmethod
    def _strip_legacy_visibility_tags(text: str) -> str:
        text = re.sub(r"<thought>.*?</thought>", "", str(text or ""), flags=re.S)
        text = re.sub(r"<action>.*?</action>", "", text, flags=re.S)
        return text.strip()

    @staticmethod
    def _is_empty_after_legacy_tag_strip(text: str) -> bool:
        stripped = str(text or "").strip()
        return not LLMCaller._strip_legacy_visibility_tags(stripped)
```

然后将 list/dict/plain lines 的候选收集统一过滤：

```python
        candidates = []
        if isinstance(data, list):
            candidates = [LLMCaller._candidate_visible_text(x) for x in data]
        elif isinstance(data, dict):
            for key in ("candidates", "messages", "list", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    candidates = [LLMCaller._candidate_visible_text(x) for x in value]
                    break
        if not candidates:
            candidates = [ln.strip() for ln in t.splitlines() if ln.strip()]
        candidates = [LLMCaller._strip_legacy_visibility_tags(x) for x in candidates]
        candidates = [x for x in candidates if x]
        return candidates[0] if candidates else t
```

- [ ] **Step 4: 改写 `generate_push` 任务指令**

将 `core/llm_caller.py` 末尾主动消息任务说明改为 JSON 候选包：

```python
        sys_parts.append(
            "任务：输出 1-3 个候选，每个候选是一次真实拿起手机要发出的消息包。"
            "每个消息包允许 1-3 条 messages，但每条都必须承担不同聊天动作：反应、修正、补充、追问之一。"
            "禁止把一句完整文案按标点硬切；禁止输出动作描写、心理活动、舞台提示或 <action>/<thought> 标签。"
            "只有当最近对话上下文逐字出现相关内容时，才允许说'你刚才/你发来的/那两个字'这类强引用。"
            "输出 JSON：[{\"messages\":[\"第一条\",\"第二条\"]}]。不要解释，不要引号外正文，不要时间戳。"
        )
```

- [ ] **Step 5: 运行主动消息解析测试**

```powershell
python -m pytest tests/test_human_message_flow.py -q
```

Expected: 新增 `_pick_best_candidate` 测试通过。

---

### Task 3: 主动消息派发使用消息包

**Files:**
- Modify: `core/companion.py`
- Test: `tests/test_human_message_flow.py`

- [ ] **Step 1: 写纯函数测试**

```python
from core.companion import Companion


def test_proactive_message_package_splits_lines_and_drops_empty():
    assert Companion._proactive_message_package("欸。\n\n我突然想到你。") == ["欸。", "我突然想到你。"]


def test_proactive_message_package_drops_legacy_action_only():
    raw = "<action>把手机举到眼前</action>\n我突然想到你。"
    assert Companion._proactive_message_package(raw) == ["我突然想到你。"]
```

- [ ] **Step 2: 运行测试确认失败**

```powershell
python -m pytest tests/test_human_message_flow.py -q
```

Expected: `Companion` 不存在 `_proactive_message_package`。

- [ ] **Step 3: 新增主动消息包方法**

在 `core/companion.py` 的 `_dispatch_push` 附近新增：

```python
    @staticmethod
    def _proactive_message_package(content: str) -> list[str]:
        from communication.splitter import SemanticMessageSplitter

        splitter = SemanticMessageSplitter(max_len=80)
        return splitter.split_chat_units(content)
```

- [ ] **Step 4: 修改 `_dispatch_push` 派发**

在 `content = await self.brain.generate_push(...)` 后增加：

```python
            message_parts = self._proactive_message_package(content)
            if not message_parts:
                return False
            content = "\n".join(message_parts)
```

后续 QQ、desktop emit、notification 先保持全文 `content` 单条落库，避免前端历史和 normalized 层产生破坏性变化；第二阶段再评估是否一段一行落库。

- [ ] **Step 5: 运行主动消息包测试**

```powershell
python -m pytest tests/test_human_message_flow.py -q
```

Expected: 主动消息包测试通过。

---

### Task 4: 普通回复分段使用聊天单元规则

**Files:**
- Modify: `core/pipeline.py`
- Modify: `communication/send_queue.py`
- Test: `tests/test_human_message_flow.py`

- [ ] **Step 1: 非流式路径替换分段入口**

在 `core/pipeline.py` 非流式生成 segments 的位置，将：

```python
segments = self._splitter.split(final_text)
```

替换为：

```python
segments = self._splitter.split_chat_units(final_text)
```

- [ ] **Step 2: QQ 传统发送路径替换分段入口**

在 `communication/send_queue.py` 的 `_send_legacy_reply` 中，将：

```python
segments = self._splitter.split(reply.content)
```

替换为：

```python
segments = self._splitter.split_chat_units(reply.content)
```

- [ ] **Step 3: 流式路径保持保守**

`core/pipeline.py:_handle_streaming_reply` 仍使用 `IncrementalSplitter`，不直接改成消息包规则。原因是流式首句延迟优化依赖增量分句；这里只在最终 flush 时可追加一次短片段合并，不破坏快路径。

- [ ] **Step 4: 运行相关测试**

```powershell
python -m pytest tests/test_human_message_flow.py tests/test_pipeline.py tests/test_send_queue_batch.py -q
```

Expected: 分段新契约通过，pipeline 与 send queue 现有测试不回退。

---

### Task 5: 上下文强引用加证据约束

**Files:**
- Modify: `core/llm_caller.py`
- Modify: `core/companion.py`
- Modify: `core/context_builder.py`
- Test: `tests/test_human_message_flow.py`

- [ ] **Step 1: 写引用检测测试**

```python
from core.llm_caller import LLMCaller


def test_detects_unsupported_strong_reference():
    text = "你发来的两个字，我看了好久。"
    dialogue_context = "[user] 行，到时候你跟我说几点"
    assert LLMCaller._has_unsupported_strong_reference(text, dialogue_context)


def test_allows_supported_strong_reference():
    text = "你发来的两个字，我看了好久。"
    dialogue_context = "[user] 晚安"
    assert not LLMCaller._has_unsupported_strong_reference(text, dialogue_context)
```

- [ ] **Step 2: 实现检测函数**

在 `core/llm_caller.py` 增加：

```python
    @staticmethod
    def _has_unsupported_strong_reference(text: str, dialogue_context: str) -> bool:
        strong_patterns = ("你发来的两个字", "你刚才说", "你刚刚说", "你发来的")
        content = str(text or "")
        context = str(dialogue_context or "")
        if "你发来的两个字" in content:
            return not any(len(token.strip()) == 2 for token in re.findall(r"\[user\]\s*([^\n]+)", context))
        return any(pattern in content for pattern in strong_patterns if pattern != "你发来的两个字") and not context
```

- [ ] **Step 3: 主动消息生成后过滤强引用**

在 `generate_push` 选择候选后，如果 `_has_unsupported_strong_reference(candidate, dialogue_context)` 为真，则降级到下一个候选；没有候选时使用模板兜底。

- [ ] **Step 4: 日常 prompt 加入证据规则**

在 `core/context_builder.py:_build_l4_language` 的“去 AI 味儿”段落追加：

```python
            "- 引用证据：只有对话历史里明确出现过的内容，才可以说'你刚才说'、"
            "'你发来的两个字'、'你那句话'。没有证据时改成'我突然想到'、'我刚刚有个念头'。\n"
```

- [ ] **Step 5: 运行引用测试**

```powershell
python -m pytest tests/test_human_message_flow.py tests/test_context_builder.py -q
```

Expected: 强引用检测通过，context builder 测试不回退。

---

### Task 6: 主动触发时间自然化

**Files:**
- Modify: `core/push_scheduler.py`
- Modify: `config/proactive.yaml`
- Test: `tests/test_proactive_scheduler_v2.py`

- [ ] **Step 1: 写 jitter 测试**

```python
from datetime import datetime

from core.push_scheduler import naturalize_push_time


def test_naturalize_push_time_moves_half_hour_anchor():
    base = datetime(2026, 8, 20, 22, 30, 0)
    shifted = naturalize_push_time(base, scene="goodnight", seed="1001-goodnight")
    assert shifted != base
    assert abs((shifted - base).total_seconds()) <= 14 * 60


def test_naturalize_push_time_is_stable_for_same_seed():
    base = datetime(2026, 8, 20, 12, 30, 0)
    assert naturalize_push_time(base, scene="lunch_remind", seed="u1") == naturalize_push_time(base, scene="lunch_remind", seed="u1")
```

- [ ] **Step 2: 实现 deterministic jitter**

在 `core/push_scheduler.py` 增加：

```python
def naturalize_push_time(base: datetime, *, scene: str, seed: str, max_minutes: int = 14) -> datetime:
    digest = hashlib.sha256(f"{seed}:{scene}:{base.date().isoformat()}".encode("utf-8")).hexdigest()
    span = max_minutes * 2 + 1
    offset = int(digest[:8], 16) % span - max_minutes
    if offset == 0:
        offset = 3
    return base + timedelta(minutes=offset)
```

- [ ] **Step 3: 调度计划生成处应用 jitter**

在 cron 计划进入实际 `_dispatch` 前，对非 `force`、非 `exempt_quiet` 的普通主动消息应用 `naturalize_push_time`。如果当前架构只在整点触发 `_dispatch`，则将 jitter 放入 `PulsePlanner` 或 scheduler 的 next-run 计算处，而不是 dispatch 后 sleep。

- [ ] **Step 4: 配置层弱化整点模板**

将 `config/proactive.yaml` 中高频主动场景的 cron 从固定半点改为窗口化策略的输入；若当前 scheduler 仍必须 cron，则保留 cron 作为扫描窗口，不作为最终发送时间。

- [ ] **Step 5: 运行调度测试**

```powershell
python -m pytest tests/test_proactive_scheduler_v2.py -q
```

Expected: PushPolicy、RoutineLearner、jitter 测试全部通过。

---

### Task 7: 纯对话触发具体化

**Files:**
- Modify: `core/llm_caller.py`
- Modify: `core/context_builder.py`
- Test: `tests/test_human_message_flow.py`

- [ ] **Step 1: 写标签泄漏与抽象开口检测测试**

```python
from core.llm_caller import LLMCaller


def test_detects_legacy_visibility_tag_leak():
    text = "<action>把手机举到眼前</action>想你了。"
    assert LLMCaller._has_legacy_visibility_leak(text)


def test_detects_abstract_phone_opening():
    text = "突然想问问你现在在干嘛。"
    assert LLMCaller._has_abstract_proactive_opening(text)


def test_allows_specific_life_trigger():
    text = "刚切青柠溅了一手汁，第一反应居然是想问你要不要尝。"
    assert not LLMCaller._has_legacy_visibility_leak(text)
    assert not LLMCaller._has_abstract_proactive_opening(text)
```

- [ ] **Step 2: 实现检测函数**

```python
    @staticmethod
    def _has_legacy_visibility_leak(text: str) -> bool:
        content = str(text or "")
        return any(token in content for token in ("<action>", "</action>", "<thought>", "</thought>"))

    @staticmethod
    def _has_abstract_proactive_opening(text: str) -> bool:
        content = str(text or "")
        abstract = ("突然想问问你", "突然想问你", "想问问你现在", "在干嘛", "想你了")
        concrete = ("刚", "饭", "雨", "风", "青柠", "电梯", "外卖", "比赛", "梦", "截图", "声音", "咖啡")
        return any(item in content for item in abstract) and not any(item in content for item in concrete)
```

- [ ] **Step 3: 主动消息候选过滤标签泄漏和抽象开口**

在 `_pick_best_candidate` 或 `generate_push` 候选筛选阶段过滤 `_has_legacy_visibility_leak(candidate)` 为真的候选；对 `_has_abstract_proactive_opening(candidate)` 为真的候选降级排序，优先选择有具体生活触发的候选。

- [ ] **Step 4: 修改主动消息提示词**

在 `core/context_builder.py:_build_l4_language` 和 `generate_push` prompt 中删除“看手机、举手机、指尖”等动作示例，增加规则：主动消息优先来自具体小事、物件、声音、食物、天气、正在做的事；不能只写“想你了/在干嘛/突然想问你”。

- [ ] **Step 5: 运行测试**

```powershell
python -m pytest tests/test_human_message_flow.py tests/test_context_builder.py -q
```

Expected: 标签泄漏候选被过滤，抽象主动开口被降级，context prompt 测试不回退。

---

### Task 8: 最小端到端验证

**Files:**
- Test only

- [ ] **Step 1: 运行核心单元测试**

```powershell
python -m pytest tests/test_human_message_flow.py tests/test_proactive_scheduler_v2.py tests/test_context_builder.py tests/test_timestamp_strip.py -q
```

Expected: 全部通过。

- [ ] **Step 2: 运行消息链路回归测试**

```powershell
python -m pytest tests/test_pipeline.py tests/test_send_queue_batch.py tests/test_quote_v2.py -q
```

Expected: 普通回复、QQ 发送、引用链路不回退。

- [ ] **Step 3: 人工样本验收**

用以下输入手动触发普通回复：

```text
行，到时候你跟我说几点
你待到几号
要不要和我一起打这个比赛
```

验收标准：
1. 允许 1-3 条连续气泡。
2. 每条气泡承担不同聊天动作。
3. 不出现 `<action>` / `<thought>` 或动作/心理舞台提示。
4. 不出现无证据的“你发来的两个字”。
5. 主动消息优先有具体生活触发，而不是空泛“在干嘛/想你了”。

---

## 实施顺序

1. 先做 Task 0，从 Persona/Prompt 源头关闭 `<action>` / `<thought>` 产出协议。
2. 再做 Task 1 和 Task 2，建立纯对话分段与候选质量硬契约。
3. 然后做 Task 3 和 Task 4，让主动消息与普通回复共用新规则。
4. 接着做 Task 5 和 Task 7，解决上下文幻觉和抽象开口。
5. 最后做 Task 6，处理主动消息时间机械感。
6. 每个 Task 独立跑测试，不做兼容层，不保留旧标签产出协议作为 fallback。

## 不做的事

1. 不把真人聊天简单等价为“多发短句”。
2. 不禁止多气泡；只禁止没有聊天动作的机械碎片。
3. 不新增第三方依赖。
4. 不改前端视觉，除非后续决定主动消息一段一行落库导致历史展示需要调整。
5. 不改数据库结构；第一阶段保留主动消息全文单行落库。
