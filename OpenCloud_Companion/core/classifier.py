"""对话意图分类器

Phase 2：基于关键词规则 + LLM 辅助分类
Phase 3：Function Calling + Tool Schema 驱动

分类策略：
1. 首先用高速关键词规则（<1ms）
2. 规则不明确时，回退到 LLM 分类（小 Prompt，低 token 消耗）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from core.brain import AIBrain
from communication.message import Intent


# ===== 规则引擎：关键词 → 意图映射 =====
# (正则模式, 意图, 置信度)
_RULE_PATTERNS: List[Tuple[str, Intent, float]] = [
    # 命令类 — 文件操作
    (r"(打开|读取|读一下?|查看|看看?)\s*(文件|文档|代码|日志|桌面|下载|文档)", Intent.COMMAND, 0.90),
    (r"(保存|写入|创建|新建|生成|写一个?)\s*(文件|文档|代码|笔记)", Intent.COMMAND, 0.90),
    (r"(搜索|查找|帮我找|搜一下?)\s*(文件|文档|图片|音乐|视频|代码)", Intent.COMMAND, 0.90),
    (r"(删除|移除|清理|整理)\s*(文件|文档|缓存|垃圾|临时)", Intent.COMMAND, 0.85),
    # 命令类 — 系统操作
    (r"(打开|启动|运行|关闭|退出)\s*(软件|程序|应用|浏览器|微信|QQ|网易云|PyCharm|VS\s*Code)", Intent.COMMAND, 0.90),
    (r"(调节|调整|设置|修改)\s*(音量|亮度|分辨率|壁纸|主题|模式)", Intent.COMMAND, 0.88),
    (r"(查看|检查|显示)\s*(系统|CPU|内存|磁盘|GPU|温度|网络|IP|状态)", Intent.COMMAND, 0.90),
    (r"(截图|屏幕截图|截屏)", Intent.COMMAND, 0.95),
    # 命令类 — 待办
    (r"(记一下?|提醒我?|设置提醒|定个闹钟|创建待办|添加待办|记录)", Intent.COMMAND, 0.85),
    (r"(我的待办|今天有什么安排|查看待办|待办列表)", Intent.QUERY, 0.88),
    # 查询类
    (r"(天气|气温|温度|下雨|刮风|空气质量|雾霾|紫外线)", Intent.QUERY, 0.92),
    (r"(新闻|热点|热搜|最新消息|今天发生)", Intent.QUERY, 0.88),
    (r"(什么(是|意思)|解释一下?|如何|怎么(弄|做|办)|为什么|有多少)", Intent.QUERY, 0.82),
    (r"(什么时候|日期|时间|今天是周几|日历|几点了)", Intent.QUERY, 0.90),
    # 闲聊类
    (r"^(早|晚安|你好|嗨|Hi|Hello|在吗|在不在|哈喽|哟|嘿|嗨咯)", Intent.CHAT, 0.95),
    (r"(谢谢|多谢|感谢|ありがとう|Thanks|辛苦了)", Intent.CHAT, 0.95),
    (r"(爱你|喜欢|想你了|抱抱|亲亲|摸摸|贴贴)", Intent.CHAT, 0.95),
    (r"(开心|难过|生气|无聊|累了|困了|烦|压力|焦虑)", Intent.CHAT, 0.90),
    (r"(吃饭|睡觉|洗澡|出门|上课|上班|下班|放学|回家)", Intent.CHAT, 0.88),
]

# 最低置信度阈值：低于此值的规则匹配视为不明确
_MIN_RULE_CONFIDENCE = 0.85

# LLM 分类 Prompt（短小精悍，低 token 消耗）
_CLASSIFIER_SYSTEM_PROMPT = """你是一个意图分类器。将用户消息分类为以下之一：
- chat: 闲聊、情感表达、日常问候
- command: 需要执行操作的指令（打开/搜素/设置/创建等）
- query: 需要查询信息的问题（天气/新闻/知识等）

只回复一个单词：chat、command 或 query。不要回复其他任何内容。"""


@dataclass
class ClassificationResult:
    """分类结果"""

    intent: Intent
    confidence: float
    method: str  # "rule" | "llm"
    rule_match: Optional[str] = None  # 命中的规则描述


class IntentClassifier:
    """
    意图分类器

    使用流程：
    1. classifier = IntentClassifier(brain)
    2. result = await classifier.classify(msg.content)
    3. 根据 result.intent 分派处理逻辑
    """

    def __init__(self, brain: Optional[AIBrain] = None):
        """
        Args:
            brain: AIBrain 实例（用于 LLM 辅助分类）。None 则仅用规则。
        """
        self._brain = brain
        self._compiled_rules = [
            (re.compile(pattern, re.IGNORECASE), intent, conf)
            for pattern, intent, conf in _RULE_PATTERNS
        ]

    def _rule_classify(self, text: str) -> Optional[ClassificationResult]:
        """规则引擎分类，返回 None 表示不确定"""
        text_lower = text.lower().strip()

        best: Optional[ClassificationResult] = None
        for pattern, intent, conf in self._compiled_rules:
            if pattern.search(text_lower) or pattern.search(text):
                if best is None or conf > best.confidence:
                    best = ClassificationResult(
                        intent=intent,
                        confidence=conf,
                        method="rule",
                        rule_match=pattern.pattern[:60],
                    )

        if best and best.confidence >= _MIN_RULE_CONFIDENCE:
            return best
        return None

    async def classify(self, text: str) -> ClassificationResult:
        """
        分类消息意图。

        策略：规则明确 → 直接返回；规则不明确且有 brain → LLM 分类；否则默认 chat。

        Args:
            text: 用户消息文本

        Returns:
            ClassificationResult
        """
        # 第一层：规则引擎
        rule_result = self._rule_classify(text)
        if rule_result:
            logger.debug(f"规则分类: {rule_result.intent.value} (conf={rule_result.confidence:.2f})")
            return rule_result

        # 第二层：LLM 分类
        if self._brain:
            try:
                llm_result = await self._brain.classify_intent(
                    text, _CLASSIFIER_SYSTEM_PROMPT
                )
                intent_str = llm_result.strip().lower()
                if intent_str in ("chat", "command", "query"):
                    intent = Intent(intent_str)
                    logger.debug(f"LLM分类: {intent.value}")
                    return ClassificationResult(
                        intent=intent, confidence=0.80, method="llm"
                    )
            except Exception as e:
                logger.warning(f"LLM 分类失败: {e}")

        # 默认：闲聊
        logger.debug(f"分类回退: chat (default)")
        return ClassificationResult(
            intent=Intent.CHAT, confidence=0.70, method="fallback"
        )

    def classify_sync(self, text: str) -> ClassificationResult:
        """同步分类（仅规则引擎，不调用 LLM）"""
        rule_result = self._rule_classify(text)
        if rule_result:
            return rule_result
        return ClassificationResult(
            intent=Intent.CHAT, confidence=0.70, method="sync_fallback"
        )
