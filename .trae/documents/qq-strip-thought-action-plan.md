# QQ 聊天 thought/action 标签过滤计划

> **版本**: v13.9  
> **类型**: 功能优化  
> **核心目标**: QQ 消息发送前过滤掉 `<thought>` 和 `<action>` 标签内容，只输出纯对话文本

---

## 一、现状分析

### 1.1 标签来源

系统提示词（`context_builder.py`）中会引导 AI 使用两种标签：

- **`<thought>...</thought>`**：包裹心理活动描写
- **`<action>...</action>`**：包裹动作描写（仅限屏幕那端动作）

相关配置项：
- `action_tags`：是否启用动作标签（默认 `True`）
- `thought_tags`：是否启用心理活动标签（默认 `True`）

### 1.2 发送链路

```
LLM 生成回复 → Pipeline 处理 → SendQueue 入队 → QQ Client 发送
                                                   ↑
                                            最佳过滤点
```

**当前链路**:
1. `pipeline.py` 生成 `reply_text`，包装为 `OutgoingReply`
2. 调用 `self.send_queue.enqueue(reply)` 入队
3. `SendQueue` 调度后调用 `qq_client.send_message()` 发送

### 1.3 需要确认的问题

- **Web UI 是否保留标签？** 用户只提到了 QQ，推测 Web UI 保留（增强沉浸感）
- **数据库存储是否保留标签？** 建议存储原始回复（带标签），发送时再过滤，方便后续分析

---

## 二、实现方案

### 2.1 最佳注入点

在 **`qq_client.py` 的 `send_message()` 方法入口** 处过滤，原因：
1. 职责清晰：QQ 通道专属过滤，不影响 Web UI
2. 数据完整：数据库仍然保存完整的带标签回复
3. 影响面小：只改一个文件，风险低

### 2.2 过滤规则

1. 移除 `<thought>...</thought>` 整段内容（包括标签本身）
2. 移除 `<action>...</action>` 整段内容（包括标签本身）
3. 支持自闭合或多行的情况
4. 过滤后清理多余空行和首尾空白
5. 如果过滤后内容为空，回退到原文（防止极端情况发空消息）

### 2.3 过滤函数

```python
import re

def strip_thought_action_tags(text: str) -> str:
    """移除 <thought> 和 <action> 标签及其内容。"""
    # 移除 <thought>...</thought>（支持跨行）
    text = re.sub(r'<thought>.*?</thought>', '', text, flags=re.DOTALL)
    # 移除 <action>...</action>（支持跨行）
    text = re.sub(r'<action>.*?</action>', '', text, flags=re.DOTALL)
    # 清理多余空行（连续多个换行合并为一个）
    text = re.sub(r'\n{3,}', '\n\n', text)
    # 清理首尾空白
    text = text.strip()
    return text
```

### 2.4 备选方案（如后续需要扩展）

如果未来需要：
- 其他通道也过滤
- 或者根据配置开关过滤

可以把过滤逻辑移到 `SendQueue` 层，通过 `OutgoingReply` 的属性控制是否过滤。

---

## 三、涉及文件

| 文件 | 修改内容 |
|------|---------|
| `communication/qq_client.py` | 在 `send_message()` 和 `send_message_with_segments()` 入口处添加标签过滤 |

---

## 四、验证方案

1. 构造带标签的测试文本，验证过滤函数正确性
2. 测试覆盖：
   - 只有 `<thought>` 标签
   - 只有 `<action>` 标签
   - 两种标签都有
   - 跨行标签
   - 多个同类标签
   - 没有标签的纯文本（应原样返回）
   - 过滤后为空的边界情况
3. 真实 QQ 对话测试，确认收到的消息无标签

---

## 五、扩展考虑（可选，本次不做）

如果后续需要，可以增加：
- 配置项：`qq.strip_thought_action`（默认开启）
- Web UI 开关：是否显示 thought/action 标签
- 不同通道不同过滤策略
