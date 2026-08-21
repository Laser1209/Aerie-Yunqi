"""临时脚本：将 persona system_prompt 中的 action/thought 标签协议替换为纯对话约定。"""
import io
import json

OLD_HEAD = "任何 `<action>` 标签里的描写都要符合本铁律。\n\n## 消息结构约定（必须遵守 · v1）"
NEW_HEAD = "你输出的任何话都不得假装你们在同一个空间。\n\n## 消息结构约定（必须遵守 · v2）"
MARKER = "## 消息结构约定（必须遵守 · v2）"
TAIL = "现在，让他感受到。"
NEW_BLOCK = (
    "## 消息结构约定（必须遵守 · v2） 你输出的是**纯对话**：每条消息都是真正会发进聊天气泡里的话。\n"
    "规则： 1. 只输出会发进气泡的话；不要输出动作描写、心理描写、舞台提示。 "
    "2. 绝不使用 action / thought 这类尖括号标签；想表达状态时，把它变成一句自然聊天，"
    "例如\"我刚刚切青柠溅了一手汁，突然就想你了\"。 "
    "3. 情绪到位想表达爱意时直接说渴望——\"我好想现在就把你揽过来\"——不要写括号动作，也不写\"在场\"行为。 "
    "4. 说完就后悔/想收回上一条已发消息时，可用可执行指令 <recall reason=\"原因\">…</recall>，"
    "框架会自动撤回你上一条已发送的消息并从正文剔除该指令；不要频繁使用撤回。\n\n"
)

PATHS = (
    r"e:\Agent_reply\data\personas\yita_default.json",
    r"e:\Agent_reply\data\personas\custom.json",
)

for path in PATHS:
    with io.open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    behavior = data.get("behavior") or {}
    behavior["action_tags"] = False
    behavior["thought_tags"] = False
    data["behavior"] = behavior
    sp = data["prompt_overrides"]["system_prompt"]
    legacy_head = "## 消息结构约定（必须遵守 · v1）"
    if legacy_head not in sp and MARKER in sp:
        print("already updated:", path)
        continue
    assert legacy_head in sp, f"legacy block not found in {path}"
    if OLD_HEAD in sp:
        sp = sp.replace(OLD_HEAD, NEW_HEAD)
    start = sp.index(MARKER) if MARKER in sp else sp.index(legacy_head)
    tail_pos = sp.find(TAIL, start)
    end = tail_pos if tail_pos > start else len(sp)
    sp = sp[:start] + NEW_BLOCK + sp[end:]
    data["prompt_overrides"]["system_prompt"] = sp
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("updated:", path)
