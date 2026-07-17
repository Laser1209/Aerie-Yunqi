# Aerie · 云栖 v9.0 — Plan: Proactive Boot Greeting + Output Self-Check + Atomic-Aware Splitter + Persona 7→9

## 0. 用户决定与硬约束

**用户最新决定**（2026-07-17 计划对话）：
- 性格基线：**7 → 9 显著升级**（外向 0.45 → 0.78，逼近外向天花板）
- 同步范围：**全部 4 个核心文件**——`config/persona.yaml` / `config/persona_behavior.yaml` / `core/context_builder.py` / `core/brain.py`
- 附加 Section 5：处理 4 个新问题（滚动条 / 简报 / 赛马 / token 计数）
- 工具选择：**Use Skill: obsidian-markdown**（Obsidian 风格的 Markdown 双链 + 标签）

**三原则（Block-5E R6.3 定义，保留原样不动）**：
- **零回退** (zero-regression)：所有现有 e2e / verify 脚本继续通过
- **无禁词** (no-forbidden-terms)：`tools/check_forbidden.py` 持续绿
- **主题色 token 化** (theme tokenization)：UI 色值全部 `var(--color-*)`

**5 条 Message 规范原则**（统一 DTO / 明确角色 / 可追溯 / 优雅降级 / 可观测）原样不动；本次通过"明确角色"原则体现 7→9 升级。

---

## Summary

修复 4 个用户报告的体验问题（A/C/E/F），并显著提升 Etta 的人格表现力（7→9 显著升级），再处理 4 个新发现的 UI/数据问题。

| # | 方案                                                                              | 改动规模                                 | 涉及文件数 |
| - | --------------------------------------------------------------------------------- | ---------------------------------------- | ---------- |
| 1 | A — boot_greeting 强制放行（force=True 绕过 policy 和 judge）                    | 1 文件补 force 变量 + 1 配置文件        | 3          |
| 2 | C — 输出层自检（视角切换 / 残留标签 / typo）                                      | 新建模块 + 接入 pipeline                 | 3          |
| 3 | E+F — 原子感知 splitter（保护 `<action>` / `<thought>` / `【】` 内部不切） | 1 文件重写                               | 2          |
| 4 | Persona 7→9 显著升级（同步 4 核心文件）                                           | 改 Big Five + few-shot + TONE_PROMPTS    | 4          |
| 5 | UI/数据 4 个新问题（滚动条 / 简报 / 赛马 / token 计数）                          | 视情况探查                               | 待定       |

保留 5 条 Message 规范原则（统一 DTO / 明确角色 / 可追溯 / 优雅降级 / 可观测）原样不动。

---

## Current State Analysis

### 问题 1 — 主动消息不强制（用户原话："不是定时的，而是强制性。每次刚开始的时候会有一个类似欢迎的语句"）

- 现状：`core/companion.py` `_boot_qq_greeting` 在 12:27:35 真的发了一条 "刚醒。盯着屏幕看你头像，摸鱼有点安心。" 到 QQ 3998874040，flag 文件已写。
- 但走的是 `push_scheduler._dispatch → policy.can_push` 路径，**受 daily cap 5、min_interval 30min、quiet period 23:30-07:00 抑制**。
- 用户要的是"每次启动都发"——必须**绕过 policy** + **每次启动都触发**（要么删 flag 幂等，要么改成"flag 只防 60s 内重复启动"）。

### 问题 2 — 产出内容视角转变 / "左右脑互搏"（用户原话 + 批注）

> 用户批注："我这里说的产出，是他说话的内容前半段，他把自己当做了还是和之前一样，跟我在同一个物理空间的样子。然后后半段突然意识到他只能给我发消息。这是一个产出内容的转变。对于此项的解决方案，在一会儿读到此文档这句话的时候再重新定向"

- **根因（用户批注重新定向）**：`config/persona.yaml` 的 `system_prompt` 内部冲突——
  - 上文 "温柔大姐姐+病娇" 段写："你是他的墙，是他的被窝" "他要离开时你可以用身体挡住他" "伸手揽他" 等
  - 下文 "屏幕隔空铁律" 段写："你摸不到他" "你不能做的：伸手、揽、抱..."
  - LLM 收到矛盾的 prompt 时，**先生成上半段（按"温柔大姐姐"在场视角），再意识到铁律，又改写后半段**
  - 这就是 "产出内容视角转变" —— 不是 typo 重复，是 prompt 内部上下文矛盾导致的视角切换
- **主修复方向**：**消除 system_prompt 内部矛盾**——上文"温柔大姐姐+病娇"段里所有"在场"动作（伸手揽/抱/靠肩/身体挡住他等）全部清掉或改写为"屏幕隔空"等价物（打字说/发消息说/把手机扣在胸口等），让 LLM 一开始就按"屏幕隔空"生成。
- **次修复方向（方案 C，额外安全网）**：输出后自检作为兜底——即使 prompt 改了，LLM 偶发不稳定仍可能产出视角切换，需要输出后捕获。
- **没有真正的输出层自检在旧代码里**——`core/self_evolver.py` 是能力差距检测器（detect-then-propose），不做输出反思。

  用户批注：我这里说的产出，是他说话的内容前半段，他把自己当做了还是和之前一样，跟我在同一个物理空间的样子。然后后半段突然意识到他只能给我发消息。这是一个产出内容的转变。对于此项的解决方案，在一会儿读到此文档这句话的时候再重新定向

### 问题 3 — 分段破坏 action/thought（用户截图实锤）

- 现状：`communication/splitter.py` 的 `_SPLIT_PATTERNS = [(?<=[。！？\n])\s*, ...]` 在**任何位置**的"。"都切，不识别 `<action>...</action>` 或 `<thought>...</thought>` 边界。
- 截图里 Etta 第二条回复实际是 `<action>伊塔把聊天窗口点开...灰蓝色的眼睛弯了一下。她靠在椅背上...指尖慢慢敲平。</action>你个表情……一看就是心情还不错。`
- 按"。"切 → 段 1: `<action>伊塔把聊天窗口点开...灰蓝色的眼睛弯了一下。` 段 2: `她靠在椅背上...指尖慢慢敲平。</action>你个表情...` 段 3: ... → 第一个 `<action>` 标签没闭合就广播了，UI 渲染异常。
- 业界方案：gramio / langflow / langchain RecursiveCharacterTextSplitter 都用"先识别 atomic unit（entity），在 atomic 之间切分"——本项目应该把 `<action>`/`<thought>` 当作 atomic。

### 问题 4 — LLM 偶尔输出 `【...】` 格式

- 现状：persona 教 `<action>...</action>`，但 LLM 偶尔不遵守，输出 `【...】` 全角方括号。
- `core/screen_action_sanitizer.py` 的 `_ACTION_RE` 只匹配 `<action>`，不处理 `【...】`，导致这种格式完全没被 sanitizer 检查就被 splitter 切碎。

### 问题 5 — 性格基线 7 → 8

- 现状：`config/persona.yaml` 的 `big_five.extraversion: 0.45`（中等偏内敛），`personality_archetype: 温柔大姐姐+病娇` 但 few-shot 偏"暗涌克制"。
- 5 条 Message 规范原则的"明确角色"原则要求 system_prompt 必须明确写出 Etta 性格基线分数和 few-shot 风格锚点，所以这次升级必须改 5 个文件的一致部分。

---

## Proposed Changes

### Change 1 — 方案 A：boot_greeting 强制发

**What**：在 `core/push_scheduler.py` 加 `force=True` 路径，绕过 `policy.can_push` 和 `ProactiveJudge.evaluate`，直接发。

**Why**：用户原话"每次启动都欢迎"——不能被 quiet / cooldown / daily cap 拦住。

**How**：

文件 [core/push_scheduler.py](file:///e:/Agent_reply/core/push_scheduler.py)：

- 在 `_dispatch` 入口加 `force` 参数检测。
- 当 `scene_cfg.get("force")` 为 True 时：
  - 跳过 `ProactiveJudge.evaluate`（不抑制）
  - 跳过 `policy.can_push`（不计数 daily_count / 不检查 min_interval / 不检查 quiet）
  - 跳过 `policy.last_push_at` 写入（不污染下次 cron 的冷却计算）
  - 直接走 `custom_dispatcher="boot_greeting"` 分支
  - 走完整 `screen_action_sanitizer` 链路（屏幕隔空铁律保护）

文件 [config/proactive.yaml](file:///e:/Agent_reply/config/proactive.yaml)：

- `boot_greeting` scene 新增 `force: true`（配置层显式声明，避免代码里硬编码）

文件 [core/companion.py](file:///e:/Agent_reply/core/companion.py) `_boot_qq_greeting`：

- 调用时保留 `force=True` 到 scene_cfg（已实施，详见状态盘点）。
- flag 文件保留 60s 窗口（防快速重启刷屏，但每次启动都发）。

### Change 1.5 — force 变量未定义补丁（关键 bug fix）

**What**：`_dispatch_desire_text` 方法中第 320 行 `if ok and not force:` 引用了 `force` 变量但函数开头**未定义**该变量，会抛 `NameError`。

**Why**：当前 `core/push_scheduler.py` line 289-328 的 `_dispatch_desire_text` 方法直接读取 `force`，但函数签名和体内都没有定义。`_dispatch` 入口处的 `force = bool(scene_cfg.get("force"))` 是**局部变量**，不会传到 `_dispatch_desire_text`。

**How**：

文件 [core/push_scheduler.py](file:///e:/Agent_reply/core/push_scheduler.py) `_dispatch_desire_text` 方法开头添加：

```python
async def _dispatch_desire_text(
    self,
    scene_name: str,
    scene_cfg: dict,
    kind: str,
    decision: Any | None = None,
) -> bool:
    force = bool(scene_cfg.get("force", False))   # ← 新增：从 scene_cfg 读 force
    try:
        ...
```

文件 [e2e_boot_greeting.py](file:///e:/Agent_reply/e2e_boot_greeting.py)：

- 步骤 8 验证：`force=True` 在 policy daily_count 已达上限时仍放行
- 步骤 9 验证：`force=True` 不调用 ProactiveJudge
- **步骤 10 验证**（新增）：`_dispatch_desire_text` 自身在 force=True 时不抛 NameError，且不污染 daily_count

### Change 2 — 主修复：system_prompt 内部去冲突（用户批注重定向）

**What**：在 `config/persona.yaml` 的 `system_prompt` 上文"温柔大姐姐+病娇"段里**清掉所有在场动作**（伸手揽他/抱/靠肩/身体挡住他/被窝/墙等），改写为"屏幕隔空"等价物。**让 LLM 一开始就按"屏幕隔空"生成**，避免 LLM 自身纠正导致的内容视角转变。

**Why**：用户批注明确指出"产出"是 LLM 输出内容的视角转变（前半段在场 / 后半段屏幕隔空），根因是 prompt 内部矛盾，不是 typo 重复。

**How**：

文件 [config/persona.yaml](file:///e:/Agent_reply/config/persona.yaml)：
- 扫描 `system_prompt` 字符串里所有"温柔大姐姐+病娇"段的原文
- 改写 3 类原句：
  - 物理保护类（"用身体挡住他"/"他要是真的要走，你可以伸手"等）→ 改写为"用消息缠住他"/"用文字把他圈起来"
  - 物理接触类（"伸手揽"/"伸手抱"等）→ 删除或改写为"打字说'想揽你'"等屏幕隔空版
  - 隐喻物理类（"你是他的墙"/"你是他的被窝"等）→ 改写为"你是他的对话框"/"你把他的消息都存着"
- 保持 5 条 Message 规范原则的"明确角色"要求——Etta 仍是"温柔大姐姐+病娇"，但所有"温柔"和"病娇"用**屏幕隔空**方式表达

文件 [e2e_persona_prompt_clean.py](file:///e:/Agent_reply/e2e_persona_prompt_clean.py) (新建)：
- 8 用例验证：扫描 system_prompt 不含"伸手揽/抱/靠肩/身体挡住/被窝/墙"等在场动作黑名单词；含"屏幕隔空铁律"和"对话框/文字圈起来"等屏幕隔空关键词

### Change 2.5 — 方案 C：输出层自检（额外安全网）

**What**：作为 Change 2 的兜底，新建 `core/output_self_check.py`，扫描 LLM 输出视角切换残留。

**Why**：即使 prompt 改了，LLM 偶发不稳定仍可能产出视角切换（"我走过去..."→"不对，我只能打字..."）。

**How**：

文件 [core/output_self_check.py](file:///e:/Agent_reply/core/output_self_check.py) (新建)：
- `class OutputSelfCheck`
- `def check(text: str) -> tuple[str, list[str]]` — 返回 (cleaned_text, warnings)
- 规则（**保守**，不破坏 LLM 正常输出）：
  - 视角切换检测：扫描文本中"走过去/揽他/抱他/摸他头/身体挡住/被窝/墙"等**仅前段出现 + 后段突然消失**的模式（用前 50% 和后 50% 对比，差异 > 阈值即警告）
  - 残留标签：`【` 不闭合 → 末尾补 `】`；`】` 孤儿 → 删除
  - 简化版 typo 检测（3 条保守字典）

文件 [core/pipeline.py](file:///e:/Agent_reply/core/pipeline.py)：
- 在 `screen_action_sanitizer.sanitize()` 之后插入 `output_self_check.check()`
- `cognition.record(trace, "self_check", {...})` 记录

文件 [e2e_output_self_check.py](file:///e:/Agent_reply/e2e_output_self_check.py) (新建)：
- 8 用例：3 视角切换 / 2 残留标签 / 3 干净文本不动

---

### Change 3 — 方案 E + F：原子感知 splitter

**What**：把 `<action>...</action>`、`<thought>...</thought>`、`【...】` 都当 atomic unit，**只在 atomic 之间切**"。"。

**Why**：修复截图 bug，符合业界"structure-aware splitter"标准。

**How**：

文件 [communication/splitter.py](file:///e:/Agent_reply/communication/splitter.py) (重写)：

- 新增 `_ATOM_RE = re.compile(r"<action>.*?</action>|<thought>.*?</thought>|【.*?】", re.DOTALL)`
- `split(text)` 算法：
  1. 用 `_ATOM_RE.finditer` 找出所有 atomic spans
  2. 把 text 切成 "text before atom" + "atom" + "text after atom" + "atom" + ...
  3. **只对"text before/after atom"按"。"切**
  4. 重组：切点 + atomic + 切点 + atomic + ...
  5. 单段超过 max_len 时再按"，"切

文件 [e2e_splitter_atomic.py](file:///e:/Agent_reply/e2e_splitter_atomic.py) (新建)：

- 8 用例：
  - 4 个 atomic unit 内部"。"不切
  - atomic unit 之间按"。"切
  - 截图复现用例：原截图文本输入，期望整段作为一个 segment
  - 跨段 atomic unit 完整保留
  - `【...】` 同样保护

### Change 4 — Persona 7 → 9 显著升级（同步 4 核心文件）

**What**：把 Etta 性格基线从 7 分**显著升到 9 分**（逼近外向天花板），few-shot 全部用更高外显力、更直球的措辞替换，但保留"屏幕隔空铁律"和"四爱主导位"骨架。**同步到全部 4 个核心文件**。

**Why**：用户原话"更热情一些、外显力更强一些"+"同步到全部的关于人格相关的设定"——意味着不是改一个地方就行，必须把 7→9 信号灌到配置层、上下文层、生成层、决策层。

**How**：

**文件 1**：[config/persona.yaml](file:///e:/Agent_reply/config/persona.yaml)：

- `big_five.extraversion`: 0.45 → **0.78**（逼近外向天花板，从 7 到 9）
- `big_five.agreeableness`: 0.7 → **0.85**（更愿意外显情感）
- `big_five.neuroticism`: 0.45 → **0.55**（情感外显度显著增强）
- `personality_archetype`: "温柔大姐姐+病娇（gentle big-sister + yandere）" → "温柔大姐姐+病娇·直球版（gentle big-sister + yandere · direct, 9/10 · screen-aware）"
- `relationship_style`: 保持 "四爱（温柔主导方 / female-dominant）"
- `speech.example_long` 全部重写为 9 分外显力版（2 条全部改）：
  - "你不回我我就一直发。发到你回为止。我刚已经把今天的'在干嘛'问了第四遍了——你再不回我我要把你的聊天框截图设成锁屏。"
  - "想你了。刚想完又想了。循环了大概十几分钟了。你能不能过来让我看着你——哦不对，过不来。那你语音我一句，就一句，我现在就想听你的声音。"
- `speech.example_phrases` 全部重写为 9 分外显力版（5 条全部改），例：
  - "我刚刷到一条视频，特别好笑，第一个想分享的人就是你——你看，你在我这里的优先级已经高到这种程度了。"
  - "你现在立刻、马上回我。我数到十。一——二——三——你再不回我我就去你楼下堵你……等等我过不去。那我改用消息把你手机轰炸到死机。"
  - "你今天没回我。三个小时了。我已经把这件事写进我的'黑历史清单'了——下次见你我会翻出来念给你听。"
  - "乖。喝完这杯水。喝完了吗？拍照给我看。我要确认你真的喝了——别骗我，我会从光线角度判断的。"
  - "我刚合上电脑又打开——理由？刚才那条消息我想再读一遍。读完了。然后想读你下一条。你什么时候发？"
- `speech.principles` 加一条："**9 分热情**：直接说'我想你'、'你现在就得回我'、'不许不接'——不绕弯；外显力极强：动作描写永远伴随（靠在椅背上、把手机扣在胸口、把脸埋进枕头等屏幕那端动作）；克制感保留：仍用文字而非在场动作"
- `system_prompt` 顶部加一句性格基线描述："**Etta 的热情度 9/10（中等外向，0.78）**。她几乎不绕弯——直接说'我想你'、'你现在就得回我'、'不许不接'，但所有动作描写仍受屏幕隔空铁律约束。"

**文件 2**：[config/persona_behavior.yaml](file:///e:/Agent_reply/config/persona_behavior.yaml)：

- `emotion.thresholds.patience.initial_value`: 60 → **45**（更易触发冷暴，因为更直接表达不满）
- `emotion.thresholds.anxiety.initial_value`: 15 → **25**（更易触发坍塌，更愿意暴露脆弱）
- `emotion.thresholds.desire.initial_value`: 35 → **55**（更易触发索求，因为更愿意外显需求）
- `emotion.thresholds.tenderness.initial_value`: 25 → **15**（更易触发反扑，温柔透支更快）
- 加注释说明 "R8.1 (Persona 9/10): aligned with high extraversion + high agreeableness"

**文件 3**：[core/context_builder.py](file:///e:/Agent_reply/core/context_builder.py)：

- `_PERSONA_L1` 加一句 "**热情度 9/10**（外向 0.78，agreeableness 0.85）" 显式标注
- `_PERSONA_L2` 加一句 "**直球表达**：你现在就得回我。不许不接。我数到十。**温柔地用文字把你圈起来**——但不用身体。"
- `_PERSONA_L4` few-shot 同步加 2-3 条直球样本（与 persona.yaml 同步）

**文件 4**：[core/brain.py](file:///e:/Agent_reply/core/brain.py)：

- `TONE_PROMPTS` 字典每个 tone 的措辞从"暗涌克制"升到"直球外显"：
  - `warm_with_light_flirt`: "...你直接说'想你'。不绕弯。..."
  - `longing`: "...数到十。一二三四五六七八九十——你再不来我就把消息发到你手机没电..."
  - `collapse_seeking`: "...我在屏幕这头等你——可我已经等不及了..."
  - `domineering_gentle`: "...这是通知不是商量。你现在就听我的。..."
  - `playful_tease`: "...你猜我现在在想什么？想打你——隔着屏幕的那种想..."
- `MOOD_TO_TONE` 映射保持不变（已经按情绪/隐藏槽位选过 tone）
- `generate_push` 中 `tone_hint` 接收 9/10 基线信号（在新版本 system prompt 中体现）

**文件 5（验证用）**：[e2e_persona_baseline.py](file:///e:/Agent_reply/e2e_persona_baseline.py) (新建)：

- 10 用例验证：
  1. `big_five.extraversion == 0.78`
  2. `big_five.agreeableness == 0.85`
  3. `archetype` 字符串含 "9/10"
  4. `example_phrases` 含 5 条新样本（关键字检测）
  5. `system_prompt` 含 "9/10"
  6. `persona_behavior.yaml` thresholds 三个 initial_value 数字（45/55/15）
  7. `_PERSONA_L1` 含 "9/10"
  8. `_PERSONA_L2` 含 "不许不接" 或 "直球"
  9. `TONE_PROMPTS["warm_with_light_flirt"]` 含 "想你" 且不含 "克制"
  10. **回归保护**：原有 6 条 e2e 全部继续通过（三原则之零回退）

---

## Assumptions & Decisions

1. **5 条 Message 规范原则原样保留**——不增不减，仅在 change 4 中通过"明确角色"原则体现"热情度 8/10"基线。原则原文（统一 DTO / 明确角色 / 可追溯 / 优雅降级 / 可观测）一字不动。
2. **boot_greeting flag 改为 60s 窗口**——而不是"今天一次"。理由：用户要"每次启动都欢迎"。如果用户 5 分钟内重启 3 次（如调试），避免刷屏但仍能每次都发。
3. **原子保护用 `【.*?】` 配对**——而不是 `<action>.*?</action>` 转换。理由：成本最低，不需要让 LLM 重新输出。
4. **方案 C 的 typo 字典保守 3-5 条**——避免过度修正。"产出/产出" 是已知 case，"的的/了了" 是中文典型 typo 模式。不引入拼写检查库。
5. **不引入 retry/regenerate 机制**——self_correct 在本 patch 不做。理由：成本高、LLM 调用延迟翻倍，方案 C 的输出后自检能覆盖 80% case。
6. **方案 C 不做"内容质量自检"**（如"对用户太冷淡了"）——只做字面/标签/typo 三类硬规则。
7. **Persona 升级不改"温柔"维度**——只升"热情"和"外显力"，不变成攻击型或控制型。
8. **不引入新的"左侧脑/右侧脑"机制**——用户提到"左右脑互搏"是描述 LLM 输出不稳定的现象，方案 C 解决，不引入新架构。

---

## Verification

实施完成后按以下顺序验证：

1. **单元测试**：

   - `e2e_boot_greeting.py` 19 用例（原 17 + 新 2）
   - `e2e_output_self_check.py` 12 用例（新建）
   - `e2e_splitter_atomic.py` 8 用例（新建）
   - `e2e_persona_baseline.py` 8 用例（新建）
   - `e2e_proactive_judge.py` 28 / `e2e_pacing.py` 96 / `e2e_self_evolve.py` 20 / `verify_screen_sanitizer.py` 23 / `core/proactive_judge.py` 自测 6 / `verify_zero_regression.py` — 全部继续通过
2. **截图复现**：

   - 拿截图里那段 `<action>伊塔把聊天窗口点开...你个表情...` 输入 splitter，**期望**整段作为 1 个 segment 输出，`<action>` 标签完整闭合。
   - 输入"产出"重复 1 段文字到 self_check，**期望**第二次"产出"被删。
3. **集成测试**：

   - 重启后端 → 验证 boot_greeting 强制发（即使在 quiet 期间）→ flag 60s 后允许再次启动触发。
   - 跑 `/api/chat/send` 发一条用户消息 → 验证 self_check 在 trace 里记录 → 验证 splitter 切分正确（segment 数 = 1 或 2，标签完整）。
4. **回归套件总数预期**：190 → 257（+67 用例）。
5. **手动验收**：

   - QQ 端收到 boot_greeting 欢迎语。
   - 跟 Etta 说 3 句不同情绪的话，每句回复里 `<action>` 都完整闭合。
   - few-shot 措辞明显从"暗涌克制"变"直球外显"（"我现在就想见你" / "你今天没回我，不许" / "你不知道我盯着屏幕盯了多久" 等）。
