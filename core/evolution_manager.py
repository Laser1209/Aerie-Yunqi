"""Aerie · 云栖 v13.9.8 — Self-Evolution L1/L2/L3.

升级自进化机制，从 v9.0 的工具提案扩展为三级进化：

  L1 · 梦境整理 (Dream Consolidation)
     └─ 空闲时自动整理记忆，合并相似条目，提取主题标签
     └─ 降低记忆冗余，提升检索质量
     └─ 对用户完全无感知，后台静默运行

  L2 · 会话复盘 (Session Reflection)
     └─ 会话结束后自动回顾，总结要点与洞察
     └─ 将高频话题、用户偏好沉淀到长期记忆
     └─ 生成会话摘要，便于后续上下文引用

  L3 · 主动沉淀 (Proactive Knowledge Distillation)
     └─ 根据对话历史，主动生成新知识卡片
     └─ 更新用户画像、人格模型微调
     └─ 发现并记录行为模式、情感规律

与 v9.0 SelfEvolver 的关系：
  - 保留原能力缺口提案机制 (L0)
  - L1/L2/L3 是新增的记忆/知识层面的自我进化
  - 全部异步运行，绝不阻塞主响应流程
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger(__name__)


class EvolutionLevel(str, Enum):
    L0_TOOL_PROPOSAL = "l0_tool_proposal"
    L1_DREAM = "l1_dream"
    L2_SESSION_REFLECTION = "l2_session_reflection"
    L3_KNOWLEDGE_DISTILL = "l3_knowledge_distill"
    L4_CODE_SELF_MODIFY = "l4_code_self_modify"


@dataclass
class EvolutionTask:
    """单次自进化任务"""
    level: EvolutionLevel
    task_id: str
    status: str = "pending"  # pending | running | done | failed
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    input_data: dict = field(default_factory=dict)
    output_data: dict = field(default_factory=dict)
    error: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class DreamResult:
    """L1 梦境整理结果"""
    consolidated: int = 0
    decayed: int = 0
    merged: int = 0
    tagged: int = 0
    themes: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)


@dataclass
class SessionReflectionResult:
    """L2 会话复盘结果"""
    session_id: str = ""
    message_count: int = 0
    duration_min: float = 0.0
    topics: list[str] = field(default_factory=list)
    key_insights: list[str] = field(default_factory=list)
    user_mood: str = "neutral"
    memories_stored: int = 0
    summary: str = ""


@dataclass
class KnowledgeDistillResult:
    """L3 主动沉淀结果"""
    new_knowledge_cards: int = 0
    persona_updates: int = 0
    patterns_discovered: list[str] = field(default_factory=list)
    preferences_updated: list[str] = field(default_factory=list)


# ── 关键词提取与主题识别 ────────────────────────────

_STOP_WORDS = {
    "的", "了", "是", "在", "我", "有", "和", "就", "不", "人", "都", "一", "一个",
    "上", "也", "很", "到", "说", "要", "去", "你", "会", "着", "没有", "看", "好",
    "自己", "这", "那", "他", "她", "它", "们", "什么", "怎么", "为什么", "哪",
    "可以", "就是", "但是", "因为", "所以", "如果", "虽然", "而且", "或者",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "this", "that", "these", "those", "i", "you", "he", "she", "it",
    "we", "they", "what", "which", "who", "whom", "whose", "where",
    "when", "how", "why", "not", "no", "nor", "not", "so", "yet",
    "and", "but", "or", "as", "if", "than", "because", "while",
}

_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "工作": ["工作", "上班", "加班", "项目", "会议", "汇报", "deadline", "任务", "同事", "老板", "领导", "职场", "绩效"],
    "学习": ["学习", "读书", "看书", "课程", "考试", "研究", "论文", "知识", "技能", "进步", "成长", "自学"],
    "生活": ["生活", "日常", "吃饭", "睡觉", "休息", "周末", "假期", "旅行", "旅游", "出门", "逛街", "做饭"],
    "情感": ["想你", "喜欢", "爱", "开心", "难过", "生气", "委屈", "感动", "温暖", "幸福", "孤独", "寂寞", "想念"],
    "健康": ["健康", "身体", "生病", "感冒", "睡觉", "失眠", "运动", "健身", "减肥", "饮食", "体检", "医院"],
    "技术": ["代码", "编程", "开发", "bug", "程序", "软件", "算法", "架构", "技术", "AI", "模型", "框架"],
    "娱乐": ["游戏", "电影", "剧", "音乐", "综艺", "小说", "动漫", "追剧", "直播", "短视频"],
    "理财": ["钱", "工资", "理财", "投资", "股票", "基金", "省钱", "消费", "预算", "收入", "支出"],
    "家庭": ["家人", "爸妈", "父母", "家里", "亲戚", "家庭", "孩子", "宠物"],
    "天气": ["天气", "下雨", "晴天", "热", "冷", "降温", "升温", "台风", "下雪"],
}


def extract_keywords(text: str, top_k: int = 10) -> list[tuple[str, int]]:
    """简单的关键词提取（基于词频 + 停用词过滤）"""
    if not text:
        return []

    words = re.findall(r"[\w\u4e00-\u9fff]+", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w in _STOP_WORDS or len(w) < 2:
            continue
        freq[w] = freq.get(w, 0) + 1

    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return sorted_words[:top_k]


def detect_topics(text: str) -> list[str]:
    """识别对话主题"""
    if not text:
        return []

    scores: dict[str, int] = {}
    for topic, keywords in _TOPIC_KEYWORDS.items():
        score = 0
        for kw in keywords:
            count = text.count(kw)
            if count > 0:
                score += count
        if score > 0:
            scores[topic] = score

    sorted_topics = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    # 返回得分 >= 2 的主题，最多 3 个
    return [t for t, s in sorted_topics if s >= 2][:3] or [t for t, s in sorted_topics[:1]]


def detect_mood(text: str) -> str:
    """简单的情绪倾向检测"""
    if not text:
        return "neutral"

    positive_words = [
        "开心", "高兴", "快乐", "幸福", "满足", "舒服", "棒", "好", "喜欢",
        "爱", "感动", "温暖", "期待", "希望", "有趣", "惊喜", "棒极了",
        "happy", "glad", "joy", "love", "great", "good", "nice", "wonderful",
    ]
    negative_words = [
        "难过", "伤心", "生气", "烦躁", "焦虑", "担心", "害怕", "委屈",
        "累", "疲惫", "压力", "郁闷", "无聊", "失望", "痛苦", "悲伤",
        "sad", "angry", "tired", "worried", "bad", "terrible", "awful",
    ]

    pos_score = sum(text.count(w) for w in positive_words)
    neg_score = sum(text.count(w) for w in negative_words)

    if pos_score > neg_score * 2:
        return "happy"
    if pos_score > neg_score:
        return "positive"
    if neg_score > pos_score * 2:
        return "sad"
    if neg_score > pos_score:
        return "negative"
    return "neutral"


# ── L1 梦境整理器 ────────────────────────────────

class DreamConsolidator:
    """L1 梦境整理

    空闲时运行，对记忆进行：
    1. 相似条目合并
    2. 过期条目衰减
    3. 主题标签提取
    4. 重要度重估
    """

    def __init__(
        self,
        memory: Any = None,
        min_idle_seconds: int = 300,
        max_items_per_run: int = 50,
    ) -> None:
        self.memory = memory
        self.min_idle_seconds = min_idle_seconds
        self.max_items_per_run = max_items_per_run
        self._last_active_at: float = time.time()
        self._run_count: int = 0

    def mark_active(self) -> None:
        """标记系统处于活跃状态（用户在交互）"""
        self._last_active_at = time.time()

    @property
    def is_idle(self) -> bool:
        """系统是否空闲（可以运行梦境整理）"""
        return (time.time() - self._last_active_at) >= self.min_idle_seconds

    async def run(self, force: bool = False) -> DreamResult:
        """运行一次梦境整理"""
        if not force and not self.is_idle:
            return DreamResult()

        result = DreamResult()
        self._run_count += 1

        try:
            # 如果有记忆系统，调用其维护功能
            if self.memory is not None and hasattr(self.memory, 'maintenance'):
                try:
                    maint_result = await self.memory.maintenance()
                    if isinstance(maint_result, dict):
                        result.consolidated = maint_result.get('consolidated', 0)
                        result.decayed = maint_result.get('decayed', 0)
                    elif hasattr(maint_result, 'consolidated'):
                        result.consolidated = maint_result.consolidated
                        result.decayed = maint_result.decayed
                except Exception:
                    logger.debug("memory.maintenance failed", exc_info=True)

            # 主题提取（基于模拟数据，实际用记忆内容）
            if self.memory is not None and hasattr(self.memory, 'retrieve'):
                try:
                    recent = await self.memory.retrieve(0, "", limit=20)
                    if isinstance(recent, list):
                        all_text = " ".join(
                            getattr(item, 'content', '') or item.get('content', '')
                            for item in recent
                            if isinstance(item, (dict, object))
                        )
                        result.themes = detect_topics(all_text)
                except Exception:
                    logger.debug("memory.retrieve for dream failed", exc_info=True)

            result.details.append(f"第 {self._run_count} 次梦境整理完成")
            result.details.append(f"合并 {result.consolidated} 条，衰减 {result.decayed} 条")
            if result.themes:
                result.details.append(f"识别主题: {', '.join(result.themes)}")

        except Exception as e:
            logger.exception("Dream consolidation failed")
            result.details.append(f"错误: {e}")

        return result


# ── L2 会话复盘器 ────────────────────────────────

class SessionReflector:
    """L2 会话复盘

    会话结束后运行：
    1. 统计会话基本信息（时长、消息数）
    2. 提取对话主题
    3. 总结关键洞察
    4. 评估用户情绪
    5. 沉淀重要记忆
    """

    def __init__(self, memory: Any = None) -> None:
        self.memory = memory
        self._sessions: dict[str, list[dict]] = {}
        self._session_start: dict[str, float] = {}

    def start_session(self, session_id: str) -> None:
        """开始一个新会话"""
        self._sessions[session_id] = []
        self._session_start[session_id] = time.time()

    def add_message(self, session_id: str, role: str, content: str) -> None:
        """添加消息到会话"""
        if session_id not in self._sessions:
            self.start_session(session_id)
        self._sessions[session_id].append({
            "role": role,
            "content": content,
            "timestamp": time.time(),
        })

    async def reflect(self, session_id: str) -> SessionReflectionResult:
        """对指定会话进行复盘"""
        messages = self._sessions.get(session_id, [])
        start_time = self._session_start.get(session_id, time.time())
        end_time = time.time()

        result = SessionReflectionResult(
            session_id=session_id,
            message_count=len(messages),
            duration_min=round((end_time - start_time) / 60, 1),
        )

        if not messages:
            result.summary = "空会话，无内容可复盘。"
            return result

        # 拼接所有文本
        all_text = "\n".join(
            f"[{m['role']}] {m['content']}"
            for m in messages
        )
        user_text = "\n".join(
            m["content"] for m in messages if m["role"] == "user"
        )

        # 主题识别
        result.topics = detect_topics(all_text)

        # 用户情绪检测
        result.user_mood = detect_mood(user_text)

        # 关键词提取作为洞察
        keywords = extract_keywords(all_text, top_k=5)
        result.key_insights = [f"高频关键词: {kw} ({count}次)" for kw, count in keywords]

        # 生成会话摘要
        topic_str = "、".join(result.topics) if result.topics else "日常闲聊"
        result.summary = (
            f"本次会话共 {result.message_count} 条消息，"
            f"时长约 {result.duration_min} 分钟。"
            f"主要话题: {topic_str}。"
            f"用户整体情绪: {result.user_mood}。"
        )

        # 沉淀重要记忆（如果有记忆系统）
        if self.memory is not None and hasattr(self.memory, 'store'):
            try:
                # 存会话摘要到长期记忆
                memory_id = await self.memory.store(
                    user_id=0,
                    content=result.summary,
                    memory_type="reflection",
                    importance=6.0,
                    metadata={
                        "session_id": session_id,
                        "topics": result.topics,
                        "message_count": result.message_count,
                        "user_mood": result.user_mood,
                    },
                    source="session_reflection",
                )
                if memory_id:
                    result.memories_stored = 1
            except Exception:
                logger.debug("Session reflection memory store failed", exc_info=True)

        return result

    def get_session_stats(self, session_id: str) -> dict:
        """获取会话统计信息"""
        messages = self._sessions.get(session_id, [])
        start = self._session_start.get(session_id, time.time())
        return {
            "session_id": session_id,
            "message_count": len(messages),
            "user_messages": sum(1 for m in messages if m["role"] == "user"),
            "assistant_messages": sum(1 for m in messages if m["role"] == "assistant"),
            "duration_min": round((time.time() - start) / 60, 1),
            "active": session_id in self._sessions,
        }


# ── L3 知识蒸馏器 ────────────────────────────────

class KnowledgeDistiller:
    """L3 主动知识沉淀

    定期运行：
    1. 生成新知识卡片
    2. 更新用户画像偏好
    3. 发现行为模式
    4. 微调人格模型参数
    """

    def __init__(self, memory: Any = None) -> None:
        self.memory = memory
        self._knowledge_base: list[dict] = []
        self._preferences: dict[str, Any] = {}
        self._patterns: list[str] = []
        self._last_run: float = 0

    @property
    def preferences(self) -> dict[str, Any]:
        return dict(self._preferences)

    @property
    def patterns(self) -> list[str]:
        return list(self._patterns)

    def add_observation(self, text: str, user_id: int = 0) -> None:
        """添加一条观察数据，用于后续蒸馏"""
        self._knowledge_base.append({
            "text": text,
            "user_id": user_id,
            "timestamp": time.time(),
        })
        # 最多保留 1000 条
        if len(self._knowledge_base) > 1000:
            self._knowledge_base = self._knowledge_base[-1000:]

    async def distill(self) -> KnowledgeDistillResult:
        """运行一次知识蒸馏"""
        result = KnowledgeDistillResult()
        self._last_run = time.time()

        if not self._knowledge_base:
            return result

        # 拼接所有观察文本
        all_text = "\n".join(item["text"] for item in self._knowledge_base[-100:])

        # 发现主题作为新知识卡片
        topics = detect_topics(all_text)
        if topics:
            for topic in topics:
                card = {
                    "type": "topic",
                    "topic": topic,
                    "evidence_count": all_text.count(topic),
                    "discovered_at": time.time(),
                }
                # 避免重复
                if not any(
                    k.get("topic") == topic and k.get("type") == "topic"
                    for k in self._knowledge_base
                ):
                    self._knowledge_base.append(card)
                    result.new_knowledge_cards += 1

        # 发现用户偏好（从 "我喜欢"、"我不喜欢" 等模式）
        preference_patterns = [
            (r"我喜欢([\u4e00-\u9fff\w]+)", "like", "喜欢"),
            (r"我爱([\u4e00-\u9fff\w]+)", "like", "爱"),
            (r"我不喜欢([\u4e00-\u9fff\w]+)", "dislike", "不喜欢"),
            (r"我讨厌([\u4e00-\u9fff\w]+)", "dislike", "讨厌"),
            (r"我觉得([\u4e00-\u9fff\w]+)最好?", "preference", "觉得最好"),
        ]

        for pattern, pref_type, label in preference_patterns:
            matches = re.findall(pattern, all_text)
            for match in matches:
                if match and len(match) >= 2:
                    key = f"{pref_type}:{match}"
                    if key not in self._preferences:
                        self._preferences[key] = {
                            "type": pref_type,
                            "item": match,
                            "pattern": label,
                            "first_seen": time.time(),
                            "count": 1,
                        }
                        result.preferences_updated.append(f"{label}{match}")
                        result.persona_updates += 1
                    else:
                        self._preferences[key]["count"] += 1

        # 发现行为模式（时间/频次规律）
        observations = [item for item in self._knowledge_base[-100:] if "timestamp" in item]
        timestamps = [item["timestamp"] for item in observations[-50:]]
        if len(timestamps) >= 5:
            # 检查是否有夜间活跃模式
            from datetime import datetime
            hours = [datetime.fromtimestamp(ts).hour for ts in timestamps]
            night_count = sum(1 for h in hours if 22 <= h or h < 6)
            if night_count >= len(hours) * 0.4:
                pattern = "用户夜间活跃（22:00-06:00）"
                if pattern not in self._patterns:
                    self._patterns.append(pattern)
                    result.patterns_discovered.append(pattern)

            # 工作日 vs 周末
            from datetime import date
            weekdays = sum(
                1 for ts in timestamps
                if date.fromtimestamp(ts).weekday() < 5
            )
            if weekdays >= len(timestamps) * 0.7:
                pattern = "用户工作日更活跃"
                if pattern not in self._patterns:
                    self._patterns.append(pattern)
                    result.patterns_discovered.append(pattern)

        # 存入记忆系统
        if self.memory is not None and result.new_knowledge_cards > 0:
            try:
                content = f"新知识卡片 {result.new_knowledge_cards} 张: {', '.join(topics[:3])}"
                await self.memory.store(
                    user_id=0,
                    content=content,
                    memory_type="knowledge",
                    importance=5.0,
                    metadata={
                        "new_cards": result.new_knowledge_cards,
                        "topics": topics,
                    },
                    source="knowledge_distill",
                )
            except Exception:
                logger.debug("Knowledge distill memory store failed", exc_info=True)

        return result

    def get_insights_summary(self) -> str:
        """获取洞察摘要"""
        lines = []
        if self._preferences:
            likes = [v["item"] for v in self._preferences.values() if v["type"] == "like"][:5]
            dislikes = [v["item"] for v in self._preferences.values() if v["type"] == "dislike"][:3]
            if likes:
                lines.append(f"喜欢: {', '.join(likes)}")
            if dislikes:
                lines.append(f"不喜欢: {', '.join(dislikes)}")
        if self._patterns:
            lines.append(f"行为模式: {', '.join(self._patterns[:3])}")
        return "\n".join(lines) if lines else "暂无洞察"


# ── 统一自进化管理器 ──────────────────────────────

class EvolutionManager:
    """统一自进化管理器（L1/L2/L3）

    协调三个层级的自进化任务，提供统一的调度接口。
    """

    def __init__(
        self,
        memory: Any = None,
        enable_l1: bool = True,
        enable_l2: bool = True,
        enable_l3: bool = True,
    ) -> None:
        self.memory = memory
        self.enable_l1 = enable_l1
        self.enable_l2 = enable_l2
        self.enable_l3 = enable_l3

        self.dream = DreamConsolidator(memory=memory)
        self.reflector = SessionReflector(memory=memory)
        self.distiller = KnowledgeDistiller(memory=memory)

        self._task_history: list[EvolutionTask] = []
        self._total_runs: dict[str, int] = {
            "l1": 0, "l2": 0, "l3": 0,
        }

    def mark_active(self) -> None:
        """标记用户活跃（重置 L1 空闲计时）"""
        self.dream.mark_active()

    async def run_l1_dream(self, force: bool = False) -> DreamResult:
        """运行 L1 梦境整理"""
        if not self.enable_l1:
            return DreamResult()

        task = EvolutionTask(
            level=EvolutionLevel.L1_DREAM,
            task_id=f"l1_dream_{int(time.time())}",
            status="running",
        )
        self._task_history.append(task)

        result = await self.dream.run(force=force)
        task.status = "done" if result.consolidated >= 0 else "failed"
        task.finished_at = time.time()
        task.output_data = {
            "consolidated": result.consolidated,
            "decayed": result.decayed,
            "themes": result.themes,
        }
        self._total_runs["l1"] += 1
        return result

    async def run_l2_reflect(self, session_id: str) -> SessionReflectionResult:
        """运行 L2 会话复盘"""
        if not self.enable_l2:
            return SessionReflectionResult(session_id=session_id)

        task = EvolutionTask(
            level=EvolutionLevel.L2_SESSION_REFLECTION,
            task_id=f"l2_reflect_{session_id}",
            status="running",
            input_data={"session_id": session_id},
        )
        self._task_history.append(task)

        result = await self.reflector.reflect(session_id)
        task.status = "done"
        task.finished_at = time.time()
        task.output_data = {
            "topics": result.topics,
            "memories_stored": result.memories_stored,
            "user_mood": result.user_mood,
        }
        self._total_runs["l2"] += 1
        return result

    async def run_l3_distill(self) -> KnowledgeDistillResult:
        """运行 L3 知识蒸馏"""
        if not self.enable_l3:
            return KnowledgeDistillResult()

        task = EvolutionTask(
            level=EvolutionLevel.L3_KNOWLEDGE_DISTILL,
            task_id=f"l3_distill_{int(time.time())}",
            status="running",
        )
        self._task_history.append(task)

        result = await self.distiller.distill()
        task.status = "done"
        task.finished_at = time.time()
        task.output_data = {
            "new_cards": result.new_knowledge_cards,
            "persona_updates": result.persona_updates,
            "patterns": result.patterns_discovered,
        }
        self._total_runs["l3"] += 1
        return result

    def get_stats(self) -> dict:
        """获取自进化统计"""
        return {
            "total_runs": dict(self._total_runs),
            "total_tasks": len(self._task_history),
            "pending_tasks": sum(1 for t in self._task_history if t.status == "pending"),
            "failed_tasks": sum(1 for t in self._task_history if t.status == "failed"),
            "l1_idle": self.dream.is_idle,
            "l2_sessions": len(self.reflector._sessions),
            "l3_knowledge_items": len(self.distiller._knowledge_base),
            "l3_preferences": len(self.distiller._preferences),
            "l3_patterns": len(self.distiller._patterns),
        }
