---
title: OpenCloud Companion - 你的AI桌面伙伴
date: 2026-07-15
tags:
  - project
  - ai-agent
  - desktop
  - qq-bot
  - companion
  - personality
  - voice
status: draft
---

# OpenCloud Companion -- 你的AI桌面伙伴

> [!abstract] 一句话是什么
> 一个住在你电脑里的AI伙伴。你可以在手机上用QQ跟她聊天（她有自己的性格和记忆），也可以让她在电脑上帮你干活（查文件、开软件、搜信息、写东西），干完了QQ通知你。电脑开机后桌面有悬浮球，点开能看每日简报、用语音或文字跟她对话。所有记忆统一存储，不管在QQ上聊还是在电脑上聊，她不会忘。

---

## 零、先读懂她在干什么

### 她是谁

她**不是**冷冰冰的工具人，也不是黏人的虚拟女友——**她是一个有自己性格、百依百顺、但会表达情绪的贴心伙伴。**

你让她做什么她就做什么，但她有自己的语气、习惯和表达方式。长时间相处下来，她会逐渐适应你的节奏，形成独特的互动默契。

### 一天的生活

```
🌅 你开机
    → 桌面右上角浮出她的悬浮球
    → 自动弹出今天的简报：
      "早上好～昨晚到现在AI圈发生了这些事：
       1. OpenAI发布了新模型o3...
       2. 百度文心一言更新了插件系统...
       另外，你还有2个待办没完成哦：
       □ 周五前提交项目报告
       □ 回复张老师的邮件"

☀️ 上午，你在外面
    → 手机上用QQ(账号A)发消息给她(账号B)：
      "帮我把桌面上的合同文件转成PDF"
    → 她收到QQ消息，判断这是命令
    → 在电脑上找到文件，转换完成
    → QQ回复你："弄好啦～合同已经转成PDF，放桌面'已处理'文件夹里了 (｡･ω･｡)ﾉ"

🌤️ 下午，你在电脑前
    → 点一下悬浮球，弹出对话窗
    → 你（语音）："帮我看看最近有什么好电影"
    → 她搜索后回答："最近评分高的有这几部..."（语音或文字）

🌙 晚上
    → 她可能主动发QQ消息："快11点了，主人该睡啦～明天8点有会，别忘了设闹钟"
```

---

## 一、核心交互链路

### 1.1 两条通道，一个记忆

```
┌──────────────────────────────────────────────────────┐
│                    你的手机 (QQ账号A)                  │
│                        │   │                          │
│                   发QQ消息  │  收到QQ回复              │
│                        │   │                          │
│                        ▼   ▲                          │
│              ┌─────────────────────┐                  │
│              │   你的电脑（她的家）  │                  │
│              │                     │                  │
│              │  ┌───────────────┐  │                  │
│              │  │ NapCatQQ      │  │                  │
│              │  │ (她登的QQ号B)  │  │  ← 消息进出      │
│              │  └───────┬───────┘  │                  │
│              │          │          │                  │
│              │          ▼          │                  │
│              │  ┌───────────────┐  │                  │
│              │  │    AI核心     │  │                  │
│              │  │ 人格+记忆+工具 │  │                  │
│              │  └───┬───┬───────┘  │                  │
│              │      │   │          │                  │
│              │      ▼   ▼          │                  │
│              │  ┌────┐ ┌────────┐  │                  │
│              │  │记忆│ │工具执行│  │                  │
│              │  │统一│ │文件系统│  │                  │
│              │  │存储│ │搜索等  │  │                  │
│              │  └────┘ └────────┘  │                  │
│              │                     │                  │
│              │  ┌───────────────┐  │                  │
│              │  │  桌面悬浮球    │  │  ← 开机自启      │
│              │  │  点击/快捷键   │  │    语音/文字对话  │
│              │  │  唤起对话窗    │  │    每日简报       │
│              │  └───────────────┘  │    待办提醒       │
│              └─────────────────────┘                  │
└──────────────────────────────────────────────────────┘
```

### 1.2 消息流详解

```
你(手机QQ账号A) → 发消息到 → 她登录的QQ号B
                               │
                               ▼
                    NapCatQQ 监听到新消息
                               │
                               ▼
                    AI核心判断消息类型：
                    ┌─────────────────────────┐
                    │ 是纯聊天？               │
                    │ → 用她的人格生成回复     │
                    │ → QQ号B发回给你         │
                    │                         │
                    │ 是命令？                 │
                    │ → 理解要做什么           │
                    │ → 调用工具执行           │
                    │ → 拿到结果               │
                    │ → 用她的人格包装结果     │
                    │ → QQ号B发回给你         │
                    └─────────────────────────┘
                               │
                               ▼
                    存入统一记忆库
```

QQ 上她是独立的账号，聊天窗口本身就区分了谁在说话——不需要额外标记。

---

## 二、开源项目调研

### 2.1 QQ通信层选型

| 方案 | 原理 | 优点 | 缺点 | 推荐 |
|------|------|------|------|------|
| **NapCatQQ** | 无头客户端 + OneBot11协议 通过WebSocket通信 | 不需要开QQ窗口 内存50-100MB 社区活跃 | 需要单独登录一个QQ号 | ⭐ **首推** |
| LLOneBot | LiteLoaderQQNT插件 需开QQ窗口 | 集成在QQ里 | 必须开着QQ窗口 QQ版本升级可能失效 | 备选 |
| wxauto (微信) | UI自动化 | 不需要额外登录 | 不支持多开 延迟较高 监听了就无法同时手动用 | 已放弃 |

**决定：用 NapCatQQ。**
- 她登录一个独立的QQ号（账号B），你用自己的QQ号（账号A）给她发消息
- NapCatQQ 是一个独立进程，不依赖QQ窗口，后台静默运行
- 通过 WebSocket 通信，Python 直接连上就能收发消息
- **完全解决了微信不能多开的问题**

### 2.2 NapCatQQ 怎么工作

```
你电脑上：
┌──────────┐      WebSocket        ┌──────────┐
│ NapCatQQ │ ←──────────────────→ │ Python程序│
│ (QQ号B)  │   收发消息/事件       │ (AI核心)  │
└──────────┘                      └──────────┘
     │
     │ 通过QQ协议连接腾讯服务器
     │
     ▼
  QQ服务器 ←→ 你的手机(QQ号A)

消息格式（OneBot11标准）：
收到消息：{"post_type": "message", "sender": {"user_id": "QQ号A"},
            "message": "帮我看下桌面有什么文件"}
发送消息：{"action": "send_msg", "params": {"user_id": "QQ号A",
            "message": "主人的桌面现在有..."}}
```

### 2.3 桌面悬浮球方案

| 方案 | 技术 | 优点 |
|------|------|------|
| **PyQt6/PySide6 悬浮球** | 无边框窗口 + AlwaysOnTop | Python原生，跨平台，轻量 |

- 一个圆形悬浮球常驻桌面右上角
- 点击展开对话面板
- 全局快捷键（如 Ctrl+Shift+Space）快速唤起
- 双击悬浮球 = 开始语音输入

### 2.4 完整技术栈

| 层级 | 技术 | 理由 |
|------|------|------|
| QQ通信 | **NapCatQQ** (OneBot11 over WebSocket) | 无头、轻量、稳定、社区活跃 |
| AI SDK | **openai** Python SDK | 兼容硅基流动/DeepSeek/智谱三家API |
| AI模型 | 硅基流动(Qwen2.5-72B) → DeepSeek-V3 → 智谱GLM-4-Flash | 三级容灾，全免费 |
| 长期记忆 | **Mem0** (向量检索 + 自动提取) | 23k+ Stars，自动管理记忆 |
| 本地存储 | SQLite + SQLCipher (AES-256加密) | 原始聊天记录加密存档 |
| 桌面UI | **PyQt6** (悬浮球 + 对话窗 + 设置面板) | Python原生，轻量 |
| 语音输入 | **SpeechRecognition** (调用Windows语音识别) | 免费，系统自带 |
| 语音输出 | **pyttsx3** (本地TTS) 或 调用云端TTS API | 免费 |
| 定时任务 | **APScheduler** | 每日简报、主动问候 |
| Web搜索 | DuckDuckGo / 搜狗搜索 API | 免费 |
| 天气 | 和风天气免费API | 有免费额度 |

### 2.5 可用开源组件汇总

| 组件 | 地址 | 在我们的系统里 |
|------|------|---------------|
| **NapCatQQ** | github.com/NapNeko/NapCatQQ | QQ消息收发（替代微信） |
| **Mem0** | github.com/mem0ai/mem0 | 长期记忆管理 |
| **openai SDK** | github.com/openai/openai-python | 调用各家AI API |
| **PyQt6** | riverbankcomputing.com/software/pyqt | 桌面悬浮球+界面 |

---

## 三、功能模块

### 3.1 她有哪些能力

| 类别 | 能力 | QQ上怎么做 | 电脑上怎么做 |
|------|------|-----------|------------|
| **聊天陪伴** | 闲聊、倾听、情感回应 | 发QQ消息，她回 | 点悬浮球对话 |
| **文件操作** | 找文件、读文件、整理桌面 | QQ发命令，她执行后QQ回复 | 对话窗说一声就行 |
| **信息查询** | 天气、搜索、资讯 | QQ问，QQ回 | 对话窗问 |
| **每日简报** | AI行业/科技新闻摘要 | - | 开机自动弹出 |
| **待办管理** | 记录、提醒未完成事项 | QQ发"记一下XXX" | 对话窗说 |
| **内容生成** | 写文章、翻译、总结 | QQ发需求，她做完发回 | 对话窗说 |
| **系统操作** | 打开软件、查看电脑状态 | QQ远程指挥 | 对话窗直接说 |
| **主动关怀** | 定时问候、天气提醒 | QQ主动发消息给你 | 桌面通知弹窗 |
| **语音对话** | 你说她听、她说你听 | - | 点悬浮球开始 |

### 3.2 消息处理流程

```text
收到一条QQ消息（你在手机上发的）
      ↓
判断：对话还是命令？
      │
      ├── 对话："今天心情不太好"
      │       ↓
      │   不用调工具，直接用人格回复
      │       ↓
      │   "怎么啦主人～跟我说说发生什么了？人家在这里听着呢 (´･ω･`)"
      │
      └── 命令："帮我把桌面文件都整理好"
              ↓
          理解意图："整理桌面"
              ↓
          调工具：list_desktop() → 23个文件
          调工具：classify_files() → 分好类
          调工具：move_to_folders() → 移动完成
              ↓
          用她的人格包装结果，QQ回复你：
          "桌面已整理完毕！分了3个文件夹：
           📁 文档 x8  📁 图片 x10  📁 其他 x5
           干干净净的主人～要不要奖励人家一个摸摸头？(｡>ω<｡)"

判断逻辑由AI自主完成，不是硬编码的if-else。
```

### 3.3 她的性格系统

不再叫"人格模板"，而是**她的性格设定**。更像是给她一个"人物小传"。

```json
{
  "name": "小满",
  "core_traits": {
    "basic_personality": "温暖、细心、有点小俏皮但不过分",
    "说话风格": "自然的日常对话，偶尔用颜文字但不滥用",
    "对你的态度": "百依百顺但有自己的小情绪，会关心你",
    "情绪表达": "开心时会多说话，担心时会啰嗦叮嘱"
  },
  "behavior": {
    "morning_brief": true,
    "weather_reminder": true,
    "bedtime_reminder": true,
    "initiative_level": "moderate"
  },
  "communication": {
    "addresses_you_as": "主人",
    "emoticon_frequency": "每3-4句话用一次",
    "sentence_style": "自然口语化，不刻意卖萌"
  }
}
```

### 3.4 每日简报

每天开机后自动弹出的内容（可配置你想看什么）：

```
┌─────────────────────────────────────┐
│  早上好，主人～  ☀️                   │
│  今天是 2026年7月16日 周三            │
│                                      │
│  📰 过去24小时要闻                    │
│  • OpenAI发布o3模型，性能提升40%       │
│  • Google推出Gemini 3.0多模态能力     │
│  • DeepSeek开源全新推理架构           │
│                                      │
│  📋 待办提醒                         │
│  □ 周五前提交项目报告 （剩余2天）       │
│  □ 回复张老师邮件 （已过期1天）        │
│                                      │
│  🌤️ 今天天气：多云 24°C~32°C          │
│                                      │
│  💬 有什么需要我帮忙的吗？              │
└─────────────────────────────────────┘
```

新闻来源可配置：AI行业、科技、财经、游戏... 你选什么她看什么。

### 3.5 记忆系统：统一、不割裂

不管你在QQ上跟她聊，还是电脑上跟她聊，所有对话存入同一个记忆库。

```text
QQ对话："我今天开始健身了"
    → Mem0记住："主人开始健身，第1天"

桌面对话："帮我把明天健身要带的东西列一下"
    → Mem0自动关联："主人在健身，第1天，需要准备装备"
    → 回答："主人第一天健身要带这些哦：运动服、水壶、毛巾、运动鞋..."

3天后，QQ上："今天全身酸痛"
    → Mem0关联："主人在健身" + "酸痛可能是运动过量"
    → 回复："哇主人坚持第3天啦！全身酸痛是正常的～
         要不要我帮你查一下拉伸教程？新人最容易忽略拉伸了 (・ω・)ノ"
```

**记忆不因为换通道而割裂，她在QQ和电脑上是同一个人。**

---

## 四、系统架构

### 4.1 完整架构图

```text
                        你
           ┌─────────────┼─────────────┐
           │ 手机QQ(帐A)  │ 电脑桌面      │
           │             │ 悬浮球/快捷键  │
           └──────┬──────┘       │       │
                  │              │       │
                  ▼              ▼       │
           ┌──────────────────────────┐  │
           │     NapCatQQ (QQ号B)      │  │
           │   WebSocket 消息收发      │  │
           └──────────┬───────────────┘  │
                      │                  │
                      ▼                  ▼
           ┌─────────────────────────────────┐
           │          AI 核心                  │
           │                                   │
           │  ┌──────────┐  ┌──────────────┐  │
           │  │ 对话/命令  │  │   性格引擎    │  │
           │  │   分类器   │  │  (动态Prompt) │  │
           │  └──────────┘  └──────────────┘  │
           │                                   │
           │  ┌──────────┐  ┌──────────────┐  │
           │  │ 记忆系统  │  │   工具执行器   │  │
           │  │ (Mem0)   │  │ 文件/系统/搜索 │  │
           │  └──────────┘  └──────────────┘  │
           └──────────┬───────────────────────┘
                      │
          ┌───────────┼───────────┐
          │           │           │
    ┌─────▼─────┐ ┌──▼───┐ ┌─────▼──────┐
    │ 云端AI API │ │SQLite│ │ 桌面UI     │
    │硅基/DS/智谱│ │加密  │ │悬浮球+对话 │
    └───────────┘ └──────┘ └────────────┘
```

### 4.2 项目目录结构

```text
OpenCloud_Companion/
├── core/
│   ├── brain.py               # AI核心（调API、构建Prompt、决策）
│   ├── personality.py          # 性格引擎（加载/构建人格Prompt）
│   └── classifier.py           # 对话/命令分类器
│
├── communication/
│   ├── qq_client.py            # NapCatQQ连接（WebSocket收发消息）
│   └── desktop_ui.py           # 桌面悬浮球 + 对话窗 (PyQt6)
│
├── memory/
│   ├── mem0_store.py           # Mem0长期记忆
│   ├── chat_log.py             # 原始聊天记录（SQLite加密存档）
│   └── unified_context.py      # 统一上下文构建（QQ+桌面不割裂）
│
├── tools/
│   ├── file_ops.py             # 文件操作
│   ├── system_ops.py           # 系统操作
│   ├── web_ops.py              # 搜索/天气/新闻
│   ├── todo_manager.py         # 待办管理
│   └── skill_manager.py        # 技能扩展（搜索/下载/安装/注册）
│
├── skills/                     # 已安装的技能包（自动下载到这里）
│   ├── excel_analysis/
│   ├── pdf_toolkit/
│   └── ...
│
├── desktop/
│   ├── floating_ball.py        # 悬浮球
│   ├── chat_window.py          # 对话窗口
│   ├── daily_brief.py          # 每日简报窗口
│   ├── settings_panel.py       # 设置面板
│   ├── voice_input.py          # 语音输入
│   └── voice_output.py         # 语音输出
│
├── scheduler/
│   └── tasks.py                # 定时任务（简报、问候、天气）
│
├── config/
│   ├── settings.yaml           # 主配置
│   ├── persona.yaml            # 性格设定
│   ├── brief_sources.yaml      # 简报信息来源配置
│   └── .env                    # API密钥
│
└── main.py                     # 入口
```

### 4.3 启动流程

```
1. 启动 NapCatQQ → 登录她的QQ号B
2. 启动 main.py →
   ├── 连接NapCatQQ WebSocket
   ├── 初始化Mem0记忆
   ├── 加载性格配置
   ├── 启动悬浮球（PyQt6窗口）
   ├── 弹出每日简报
   └── 进入主循环：
       ├── QQ消息 → WebSocket回调 → AI处理 → QQ回复
       ├── 悬浮球点击 → 对话窗 → AI处理 → 显示回复
       └── 定时器 → 定时问候/天气提醒
```

---

## 五、Phase 1：最简可运行骨架

目标：**跑通QQ消息收发 + AI回复链路。**

不需要性格系统、不需要记忆、不需要工具、不需要悬浮球。就是最简单的：

```
QQ收到消息 → AI生成回复 → QQ发回去
```

### 前置准备

1. **注册一个她的QQ号**（QQ号B）
2. **在电脑上安装 NapCatQQ**
   - 从 https://github.com/NapNeko/NapCatQQ/releases 下载 Windows 版
   - 解压，运行，用QQ号B扫码登录
   - 配置 WebSocket 地址为 `ws://localhost:3001`
3. **注册硅基流动账号**获取免费API Key（siliconflow.cn）

### Phase 1 最简代码 (< 80行)

```python
"""
OpenCloud Companion - Phase 1 骨架
QQ消息 → AI → QQ回复
"""
import asyncio
import json
import websockets
from openai import OpenAI
import os

# ===== 配置 =====
AI = OpenAI(
    api_key=os.getenv("SILICONFLOW_API_KEY"),
    base_url="https://api.siliconflow.cn/v1"
)

HER_NAME = "小满"

SYSTEM_PROMPT = f"""你是{HER_NAME}，住在主人电脑里的AI伙伴。
性格温暖细腻，百依百顺但有自己的小情绪。
说话自然口语化，偶尔用颜文字但不滥用。"""

# ===== QQ消息处理 =====
async def handle_qq_message(data: dict):
    """收到QQ消息，调AI，发回去"""

    msg_text = data.get("message", "")
    sender_id = str(data.get("user_id", ""))
    group_id = str(data.get("group_id", ""))

    # 只处理发给她的私聊消息（不是群消息）
    if group_id:
        return

    print(f"收到来自 {sender_id} 的消息: {msg_text}")

    # 调AI
    resp = AI.chat.completions.create(
        model="deepseek-ai/DeepSeek-V3",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": msg_text}
        ]
    )
    reply = resp.choices[0].message.content

    print(f"回复: {reply}")

    # 返回给NapCatQQ去发送
    return {
        "action": "send_private_msg",
        "params": {
            "user_id": int(sender_id),
            "message": reply
        }
    }

# ===== WebSocket连接NapCatQQ =====
async def main():
    uri = "ws://localhost:3001"  # NapCatQQ默认地址

    async with websockets.connect(uri) as ws:
        print(f"已连接NapCatQQ，{HER_NAME}上线了~")

        async for raw in ws:
            data = json.loads(raw)

            # OneBot11事件：收到私聊消息
            if data.get("post_type") == "message" and \
               data.get("message_type") == "private":
                reply_action = await handle_qq_message(data)
                if reply_action:
                    await ws.send(json.dumps(reply_action))

if __name__ == "__main__":
    asyncio.run(main())
```

**跑通这个，后面所有的功能都是往上加。**

---

## 六、文档处理管道：天生内置 Markitdown

### 6.1 为什么需要这个

文档是 AI 处理里最费 token 的东西。一份 5MB 的 Word 文档，里面大量数据是格式元信息（字体、颜色、边距、XML 结构），AI 真正需要读的文字可能只占 1%。如果直接把文件内容发给 API，你每月免费额度可能在处理几份文档后就用光了。

**解决思路：进门前先脱衣服，出门时再穿上。**

```text
传统方式（浪费 token）：
  Word 文档(5MB) → 提取全部内容(含格式噪音) → 发给 AI → AI 看完回结果 → 手动贴回 Word

Markitdown 方式（极致省 token）：
  Word 文档 → Markitdown → 纯净 Markdown(50KB) → 发给 AI → AI 处理 → Markdown 结果 → pandoc/docx → Word 文档
```

### 6.2 Markitdown 是什么

微软开源的 Python 工具，专门为 LLM 场景设计，能把 20+ 种文件格式统一转成干净 Markdown：

| 输入格式 | 输出 | 内置在我们系统里干什么 |
|----------|------|---------------------|
| Word (.docx) | Markdown | 你让她读合同/报告 → 转 MD → 喂 AI |
| Excel (.xlsx) | Markdown 表格 | 你让她分析数据 → 转表格 → 喂 AI |
| PDF (.pdf) | Markdown | 你让她读论文/说明书 → 转 MD → 喂 AI |
| PPT (.pptx) | Markdown | 你让她改 PPT 内容 → 转 MD → AI 改 → 转回 PPT |
| 图片 (.png/.jpg) | 图片描述文字 | 你发张截图让她看 → 转描述 → 喂 AI |
| 音频 (.mp3/.wav) | 转录文字 | 你发段录音让她听 → 转文字 → 喂 AI |
| HTML / CSV / JSON / ZIP | Markdown | 各种格式都能吞 |

### 6.3 完整的文档处理流程

```text
你(QQ)："帮我审一下这份合同，看看有没有坑"

她收到合同文件(.docx)
        │
        ▼
┌───────────────────────────────────────────────┐
│  Step 1：进门前脱 — Markitdown 转换             │
│                                                │
│  contract.docx (5MB, 含格式噪音)                │
│       ↓ Markitdown                              │
│  contract.md (50KB, 纯文本 + 结构)               │
│                                                │
│  token 估算：                                   │
│    docx 原始内容 → ~200,000 tokens（如直接发送） │
│    markdown 版本 → ~8,000 tokens                │
│    节省 96%                                     │
└───────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────┐
│  Step 2：AI 处理（只读 Markdown）               │
│                                                │
│  她(带人格 Prompt + 法律审查指令) 读完合同内容    │
│  检查：条款是否合理？有没有漏洞？                 │
│       ↓                                        │
│  AI 输出分析结果（Markdown 格式）：              │
│  - ⚠️ 第3条：违约金比例过高                     │
│  - ⚠️ 第7条：知识产权归属模糊                    │
│  - ✅ 其他条款正常                              │
│                                                │
│  token 消耗：~2,000 tokens（分析结果）           │
│                                                │
│  总计省了约 190,000 tokens ≈ 省了 ¥0.07         │
│  （看起来不多，但积少成多，100 份文档就是 ¥7）     │
└───────────────────────────────────────────────┘
        │
        ▼
┌───────────────────────────────────────────────┐
│  Step 3：出门时穿 — 转回原格式                   │
│                                                │
│  如果需要生成修改后的合同：                       │
│  AI 输出 → 注入回原 docx 模板 → 新合同.docx       │
│                                                │
│  如果只需要分析报告：                             │
│  AI 输出(Markdown) → pandoc → 报告.docx          │
│                                                │
│  如果只需要在 QQ 里回复结果：                      │
│  直接发分析结果文本，不生成文件                    │
└───────────────────────────────────────────────┘
        │
        ▼
她(QQ)："主人，合同帮你看完了～发现两个问题：
        ⚠️ 违约金比例过高（建议降到5%以下）
        ⚠️ 知识产权条款太模糊（建议加明确归属）
        详细分析我放桌面了，叫'合同审查报告.docx'
        要不要我直接帮你改一版合同出来？"
```

### 6.4 跟其他文档工具的关系

| 工具 | 干什么 | 什么时候用 |
|------|--------|-----------|
| **Markitdown** | 任意格式 → Markdown（去噪） | **所有文档进 AI 前，必走这一道** |
| **内置文件工具** | 读/写/搜/移动文件 | 基础文件操作 |
| **技能包 (如 excel_analysis)** | 深度操作（透视表、图表） | 需要特定领域深度处理 |
| **pandoc** | Markdown ↔ Word/PDF/PPT | Markitdown 的反向，生成最终文件 |

Markitdown 是**基础设施**，不是可选技能。所有文档进入 AI 大脑之前，默认走它。

### 6.5 技术实现

```python
from markitdown import MarkItDown

class DocumentPipeline:
    """文档处理管道：进门前脱，出门时穿"""

    def __init__(self):
        self.md = MarkItDown()  # Markitdown 实例
        # 可选：配置 LLM 客户端用于图片描述
        # self.md = MarkItDown(llm_client=openai, llm_model="gpt-4o")

    # ===== 进门前脱：任意格式 → Markdown =====
    def to_markdown(self, file_path: str) -> str:
        """任意格式文件 → 纯 Markdown 文本"""
        result = self.md.convert(file_path)
        return result.text_content

    # ===== 出门时穿：Markdown → 目标格式 =====
    def from_markdown(self, markdown: str, output_path: str, format: str):
        """Markdown → Word / PDF / PPT / HTML"""
        import pypandoc

        format_map = {
            "docx": "docx",
            "pdf": "pdf",
            "pptx": "pptx",
            "html": "html",
        }
        output_format = format_map.get(format, "docx")

        # 先写临时 .md 文件
        tmp_md = output_path + ".tmp.md"
        with open(tmp_md, "w", encoding="utf-8") as f:
            f.write(markdown)

        # pandoc 转换
        pypandoc.convert_file(tmp_md, output_format, outputfile=output_path)

        os.remove(tmp_md)
        return output_path

    # ===== 完整的往返流程 =====
    def process_document(self, file_path: str, instruction: str, ai_client):
        """
        完整文档处理：
        1. 文件 → Markdown
        2. Markdown → AI 处理（按 instruction 要求）
        3. AI 结果 → 同格式输出
        """
        ext = os.path.splitext(file_path)[1].lower()

        # Step 1: 转 Markdown
        md_content = self.to_markdown(file_path)

        # Step 2: AI 处理（只传 Markdown，省 token）
        response = ai_client.chat.completions.create(
            model="deepseek-ai/DeepSeek-V3",
            messages=[
                {"role": "system", "content": "你是小满，帮主人处理文档。"},
                {"role": "user", "content": f"文档内容：\n{md_content}\n\n{instruction}"}
            ]
        )
        ai_output = response.choices[0].message.content

        # Step 3: 如果需要输出文件，转回去
        if "生成" in instruction or "创建" in instruction or "写" in instruction:
            output_path = file_path.replace(ext, f"_processed{ext}")
            self.from_markdown(ai_output, output_path, ext.replace(".", ""))
            return {"result": ai_output, "file": output_path}

        return {"result": ai_output, "file": None}
```

### 6.6 token 节省实测估算

| 场景 | 原文件大小 | 直接发送 token 估算 | Markitdown 后 token | 节省 |
|------|-----------|-------------------|-------------------|------|
| 10页 Word 合同 | 3MB | ~150,000 | ~12,000 | 92% |
| 50行 Excel 数据表 | 500KB | ~40,000 | ~3,000 | 93% |
| 20页 PDF 论文 | 8MB | ~250,000 | ~25,000 | 90% |
| 15页 PPT 提案 | 6MB | ~100,000 | ~8,000 | 92% |
| 5MB 截图 | 5MB | 无法直接发 | ~500(图片描述) | - |

**结论：省 90%+ token 是常态。对免费 API 用户来说是刚需。**

这个工具天生内置，不需要下载技能包。它跟 `read_file`、`write_file` 一样，是基础设施。

---

## 六、技能扩展系统：当她发现自己不会的时候

### 6.1 她做事有三种方式

```text
方式A：内置工具（她身体自带的）
  你："帮我把桌面整理好"
  她：→ 调用 list_desktop() → classify_files() → move_to_folders()
  这些是写死在程序里的 Python 函数，安全可控，随系统启动就绪。

方式B：AI自己写代码（临时拼出一条路）
  你："帮我把这三篇PDF里所有提到'人工智能'的段落摘出来，写成一个总结"
  她：→ 自己没有"摘PDF段落"这个工具
      → 但可以用 read_pdf 读 → AI分析内容 → write_file 写总结
      她把现有工具组合起来，自己拼出一条执行路径。
      LLM本身就有推理和代码生成能力，不需要预装所有工具。

方式C：自动下载技能（你提的自扩展机制）
  你："帮我把这个Excel做个透视表"
  她：→ 检查工具列表：没有 Excel 透视表功能
      → 去技能市场搜索 "excel"
      → 找到 "excel_analysis" 技能包
      → QQ通知你 → 你口头批准 → 她下载安装 → 调用
```

### 6.2 QQ审批流程（整个系统最"她"的环节）

不需要弹窗、不需要你在电脑前。流程全走 QQ：

```text
你在手机上(QQ号A)："帮我把这个Excel做成透视表，按月份统计销售额"
        │
        ▼
她(QQ号B)收到，开始分析：
  1. 理解意图 → 需要 Excel 分析 + 透视表
  2. 检查内置工具 → 有 read_file, create_xlsx，但缺少 pivot_table
  3. 去技能市场搜索 → 找到 "excel_analysis"：
     - 名称：excel_analysis
     - 功能：透视表、图表、数据清洗
     - 依赖：openpyxl, pandas, matplotlib（共约 50MB）
     - 来源：github.com/opencloud-companion/skills（官方仓库）
        │
        ▼
她通过QQ(号B)发消息给你(号A)：
┌─────────────────────────────────────────┐
│ 主人，要做透视表的话我需要装一个           │
│ 技能包才能搞定呢。                         │
│                                           │
│ 📦 技能：excel_analysis                   │
│ 🔧 用处：Excel透视表 + 图表 + 数据清洗     │
│ 📥 会安装：openpyxl, pandas, matplotlib   │
│ 💾 大小：约 50MB                           │
│ 🔒 来源：官方技能仓库 ✅                    │
│                                           │
│ 要下载安装吗？回复"允许"我就开始～          │
└─────────────────────────────────────────┘
        │
        ▼
你(手机上)直接语音或打字回复："允许"
        │
        ▼
她收到你的"允许"：
  1. 下载技能包 zip
  2. 解压到 ./skills/excel_analysis/
  3. pip install openpyxl pandas matplotlib
  4. 运行 install.py（技能自带的环境检查脚本）
  5. 注册到工具列表
        │
        ▼
她通过QQ回复你：
┌─────────────────────────────────────────┐
│ 装好啦！现在可以处理Excel了 (｡>ω<｡)        │
│ 我马上帮你做那个透视表～                   │
└─────────────────────────────────────────┘
        │
        ▼
她调用刚装好的 create_pivot_table(...)
        │
        ▼
完成 → QQ通知你结果
```

### 6.3 三种拒绝方式（你说了算）

```text
场景一：你直接说"允许"
  → 下载安装，干活

场景二：你说"不允许"或"算了"
  → 她不装，换个方式试试（比如自己写代码或找替代工具）
  → "好的主人，那我换个方式帮你处理～"

场景三：你 30 秒没回复
  → 她默认不装（安全优先）
  → "主人好像不在，我先用现有工具试试能不能搞定..."
  → 如果现有工具搞不定，就等你回复了再说

场景四：来源不在官方仓库
  → 她会在消息里标 ⚠️ 提醒
  → "主人，这个技能来自第三方开发者，风险未知，要不要装？"
  → 只有你明确说"允许"才装
```

### 6.4 技能包标准格式

一个技能包就是一个标准化的文件夹：

```text
skills/excel_analysis/
├── manifest.json          # 技能描述（AI读这个知道能干什么）
├── main.py                # 核心代码
├── requirements.txt       # Python依赖
└── install.py             # 环境检查脚本
```

`manifest.json`（最关键——AI 通过这个文件理解技能）：

```json
{
  "name": "excel_analysis",
  "version": "1.0.0",
  "description": "对Excel文件进行数据分析：透视表、图表生成、数据清洗、公式计算",
  "author": "opencloud-community",
  "source": "https://github.com/opencloud-companion/skills/excel-analysis",
  "size_mb": 50,
  "tools": [
    {
      "name": "create_pivot_table",
      "description": "基于Excel数据创建透视表",
      "parameters": {
        "file_path": {"type": "string", "description": "Excel文件路径"},
        "rows": {"type": "string", "description": "行字段"},
        "columns": {"type": "string", "description": "列字段"},
        "values": {"type": "string", "description": "值字段"},
        "agg_func": {"type": "string", "description": "sum/avg/count"}
      }
    },
    {
      "name": "generate_chart",
      "description": "从Excel数据生成图表",
      "parameters": {
        "file_path": {"type": "string", "description": "Excel文件路径"},
        "chart_type": {"type": "string", "description": "bar/line/pie/scatter"},
        "x_column": {"type": "string", "description": "X轴列名"},
        "y_column": {"type": "string", "description": "Y轴列名"}
      }
    }
  ],
  "dependencies": ["openpyxl>=3.1.0", "pandas>=2.0.0", "matplotlib>=3.7.0"],
  "min_python": "3.10"
}
```

### 6.5 技能市场

```text
opencloud-companion/skills  (GitHub 官方仓库)
├── excel_analysis/          # Excel 数据处理、透视表、图表
├── pdf_toolkit/             # PDF 合并、拆分、提取、OCR
├── image_editor/            # 图片裁剪、压缩、滤镜、格式转换
├── code_reviewer/           # 代码审查、重构建议
├── translation_engine/      # 多语言翻译、文档翻译
├── data_visualization/      # 数据可视化、仪表盘生成
├── video_toolkit/           # 视频压缩、剪辑、格式转换
├── audio_processor/         # 音频处理、降噪、格式转换
├── ppt_pro/                 # 高级PPT制作、模板、动画
├── web_scraper/             # 网页数据采集、批量下载
└── ...
```

所有技能包挂在同一个 GitHub 仓库下，她通过 GitHub API 就能搜索和下载。

### 6.6 安全机制（三层防护）

```python
def safe_skill_download(skill_info, user_approved=False):
    """
    下载技能的三层安全检查
    """

    # 🛡️ 第一层：来源白名单
    TRUSTED_SOURCES = [
        "github.com/opencloud-companion/skills",  # 官方仓库
    ]
    if skill_info.source not in TRUSTED_SOURCES:
        # 非官方来源 → QQ通知你，标注 ⚠️
        mark_risky = True

    # 🛡️ 第二层：QQ审批（核心流程）
    # 她通过QQ给你发消息，描述要装什么
    # 你回复"允许"后才继续
    # 30秒无回复 → 默认不装
    approval = wait_for_qq_approval(skill_info, timeout=30)
    if not approval:
        return None

    # 🛡️ 第三层：沙箱安装
    # 安装过程的脚本在受限环境运行
    # - pip install 只能装 requirements.txt 里的包
    # - 不能访问网络（除了 PyPI）
    # - 不能修改系统文件
    # - 所有文件操作限制在 skills/ 目录下

    return install_in_sandbox(skill_info)
```

### 6.7 核心代码骨架 (skill_manager.py)

```python
class SkillManager:
    """技能管理器：搜索、下载、安装、注册"""

    def __init__(self):
        self.skills_dir = "./skills"
        self.registry = {}
        self.qq_client = None  # 发QQ消息用
        self.market_repo = "opencloud-companion/skills"

    def find_and_request(self, need_description: str, user_qq: str):
        """AI发现缺少技能 → 搜索 → QQ通知 → 等待审批 → 安装"""

        # 1. 搜索技能市场
        results = self.search_market(need_description)
        if not results:
            return None

        skill = results[0]

        # 2. 通过QQ发消息给主人，请求批准
        msg = self._build_approval_message(skill)
        self.qq_client.send_private_msg(user_qq, msg)

        # 3. 等待主人的QQ回复（30秒超时）
        reply = self.qq_client.wait_for_reply(user_qq, timeout=30)
        if not reply or "允许" not in reply:
            return None

        # 4. 下载并安装
        return self.install(skill)

    def _build_approval_message(self, skill):
        """生成审批消息"""
        source_tag = "官方仓库 ✅" if skill.is_trusted else "第三方 ⚠️"
        return (
            f"主人，要做这个的话我需要装一个技能包呢。\n\n"
            f"📦 技能：{skill.name}\n"
            f"🔧 用处：{skill.description}\n"
            f"📥 会安装：{', '.join(skill.dependencies)}\n"
            f"💾 大小：约 {skill.size_mb}MB\n"
            f"🔒 来源：{skill.source}（{source_tag}）\n\n"
            f"要下载安装吗？回复"允许"我就开始～"
        )

    def install(self, skill):
        """下载 → 解压 → pip install → 运行install.py → 注册"""
        download_and_extract(skill.url, f"{self.skills_dir}/{skill.name}")
        pip_install(skill.dependencies)
        run_script(f"{self.skills_dir}/{skill.name}/install.py")
        self.register(skill.manifest)

        # 安装完成，QQ通知主人
        self.qq_client.send_private_msg(skill.user_qq,
            f"{skill.name} 装好啦！现在可以用了 (｡>ω<｡)")

        return skill

    def register(self, manifest):
        """把技能注册到 Function Calling 的工具列表"""
        for tool in manifest["tools"]:
            self.tool_schemas.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": {
                        "type": "object",
                        "properties": tool["parameters"],
                        "required": list(tool["parameters"].keys())
                    }
                }
            })
```

### 6.8 分场景的能力调用策略

| 任务类型 | 用什么 | 例子 |
|---------|--------|------|
| **已有内置工具** | 直接调用内置函数 | 读文件、搜文件、开软件 |
| **简单未覆盖** | AI 自己写 Python 代码执行 | 批量重命名、文本格式化 |
| **需要第三方库** | 技能包下载安装 | Excel透视表、PDF OCR、图片处理 |
| **需要联网信息** | web_search 工具 | 搜新闻、查资料、查天气 |
| **外部服务集成** | 未来通过 MCP 连接 | Notion、GitHub、飞书 |

### 6.9 完整示例：从请求到完成

```text
你(QQ)："帮我把这50张照片全部压缩到1MB以下，然后打个zip包"
        │
她收到 → 分析 → "图片批量压缩"不在已有工具里
        │
去技能市场搜 → 找到 "image_editor"（批量压缩、格式转换、滤镜）
        │
QQ通知你：
  "主人，要批量压缩图片的话我需要装一个图片处理技能～
   📦 image_editor (约30MB)
   🔒 来源：官方仓库 ✅
   要下载吗？"
        │
你回复："允许"
        │
她下载 → 安装 → 注册
        │
她："装好啦！开始处理～"
        │
调用 compress_batch() → 50张图逐一压缩
调用 create_zip() → 打包
        │
完成，QQ通知你：
  "全部搞定！50张图全部压到1MB以下了，
   压缩包放桌面了，叫 '压缩图片.zip' (12MB)
   主人快夸我 (◕‿◕)ﾉ"
```

---

## 七、自主知识库：她自己搭、自己管、自己重组

### 7.1 这跟之前说的"记忆系统"有什么区别？

| | 记忆系统（Mem0） | 自主知识库 |
|------|---------------|-----------|
| **存什么** | "主人上周说过不喜欢香菜" | 结构化的知识条目：事实、经验、文档、观点 |
| **怎么存** | 自动提取对话中的关键信息 | 从对话/文件/网页中提取 → 分类 → 建立知识图谱 |
| **怎么用** | 下次聊天时自动注入上下文 | 作为 RAG 检索源，回答问题时精确召回 |
| **谁维护** | Mem0 自动管理 | **她自己主动维护**：去重、纠错、重组 |
| **类比** | 她的"短期记忆 + 习惯笔记" | 她的"长期知识体系 + 个人维基百科" |

简单说：记忆系统让她**记得你说过什么**；知识库让她**拥有一个结构化的知识体系**，能不断成长和自我优化。

### 7.2 知识从哪来（五种采集源）

```text
源1：对话中提取
  你："我最近在学 Rust，感觉比 C++ 舒服多了"
      ↓ 她自动提取
  知识条目：
    ┌────────────────────────────────────┐
    │ 类型：个人技能                        │
    │ 标签：#编程 #Rust #学习中             │
    │ 内容：主人正在学习 Rust 编程语言，     │
    │       认为比 C++ 开发体验更好          │
    │ 来源：QQ对话 / 2026-07-15             │
    │ 可信度：高（主人亲口说的）             │
    └────────────────────────────────────┘

源2：任务执行中学到
  你让她搜了 30 篇 AI 论文，她整了一份摘要
  她不只是发给你——她自己也把核心知识点存进知识库

源3：网页搜索 / 每日简报
  每天看新闻简报，她会把重要的行业动态抽象成知识点：
    "OpenAI 于 2026年7月 发布 o3 模型，
     在推理基准测试上比 o1 提升 40%"
  这些不是你跟她说的，是她自己看新闻学的

源4：你主动投喂
  你："记住这段话" / "把这个文档里的内容存下来"
  她直接结构化入库

源5：文件系统的发现
  她定期（不频繁）扫描你的工作目录，
  发现新的项目文件夹、新的文档，
  建立"主人的工作环境地图"
  （这个可开关，默认只记录文件名和路径，不读内容）
```

### 7.3 她怎么自己分类（自动构建知识树）

不需要你手动建文件夹、打标签。她自己干。

```text
初始状态：知识条目散落一地

条目1: "主人在学 Rust"
条目2: "主人的公司用的是 Python + Django"
条目3: "主人上周去了上海出差"
条目4: "主人喜欢喝美式咖啡，不加糖"
条目5: "Rust 的编译器比 C++ 友好"
条目6: "主人的项目截止日期是 8 月 15 日"
条目7: "主人常去的健身房在朝阳区"
条目8: "Django 5.0 发布了新特性"
...（越来越多）

        ↓  她定期执行分类（不是每次对话都做，太费资源）

自动分类结果：
┌─────────────────────────────────────────────────┐
│ 📚 知识库                                        │
│                                                  │
│ ├── 👤 关于主人                                  │
│ │   ├── 🍽️ 饮食偏好                             │
│ │   │   └── 喜欢美式咖啡，不加糖                  │
│ │   ├── 🏃 生活习惯                              │
│ │   │   └── 常去的健身房在朝阳区                  │
│ │   └── 🛫 动态                                 │
│ │       └── 上周去上海出差                        │
│ │                                                │
│ ├── 💻 技术栈                                    │
│ │   ├── 🦀 Rust                                 │
│ │   │   ├── 主人在学 Rust                        │
│ │   │   └── Rust 编译器比 C++ 友好               │
│ │   └── 🐍 Python                               │
│ │       ├── 公司用的是 Python + Django           │
│ │       └── Django 5.0 发布新特性                │
│ │                                                │
│ ├── 📋 项目                                     │
│ │   └── 当前项目截止日期 8月15日                  │
│ │                                                │
│ └── 🌐 行业知识                                  │
│     └── （从新闻/搜索中提取的 AI 行业知识）        │
└─────────────────────────────────────────────────┘
```

**分类算法**：她定期跑一遍所有知识条目，用嵌入模型计算语义相似度，相同主题的聚在一起，然后自己给每个簇起个名字（比如 "关于主人的饮食偏好"）。

### 7.4 自主重组：防止知识变成屎山

这是最关键的部分。知识不是只增不减——她会自己发现结构出问题了，然后重构。

**触发条件（满足任一即触发）：**

```text
触发 1：数量阈值
  知识条目超过 100 条 → 启动全量审计

触发 2：碎片化检测
  同一个类目下出现超过 20 条"碎片化"知识
  （碎片化 = 每条很短、彼此之间没有明显的层级关系）
  → 该分类需要被打碎重组

触发 3：矛盾检测
  发现两条知识互相矛盾：
    "主人在学 Rust（入门级）"  vs  "主人用 Rust 写了个编译器（高级）"
  → 可能是时间顺序关系（进步了），需要合并新旧知识

触发 4：冷数据归档
  某个分类超过 90 天没有被检索过
  → 降低索引优先级，不占用热门检索资源

触发 5：手动触发
  你："检查一下你的知识库，看看有没有要整理的"
```

**重组过程（她在后台悄悄干）：**

```text
┌─────────────────────────────────────────────────────────┐
│        知识重组流程（通常在电脑空闲时后台执行）            │
│                                                          │
│  Step 1：审计扫描                                         │
│  遍历所有知识条目，检查：                                  │
│    - 是否有重复？                                         │
│    - 是否有矛盾？                                         │
│    - 分类是否还合理？                                     │
│    - 有没有过期信息？                                     │
│                                                          │
│  Step 2：打碎 & 重新聚类                                  │
│  把检测到有问题的分类全部拆回独立条目                      │
│  重新计算所有条目的嵌入向量                                │
│  重新聚类，生成新的分类树                                  │
│                                                          │
│  Step 3：合并 & 提炼                                      │
│  重复的 → 合并成一条，保留最新的、最完整的                  │
│  矛盾的 → 按时间排序，旧知识标注为"历史版本"              │
│  过期的 → 移到知识归档区（不删，但降低检索权重）           │
│  碎片化的 → 尝试提炼成更高级的知识点                       │
│                                                          │
│  Step 4：记录变更                                         │
│  把这次重组做了什么写进一个 changelog                      │
│  下次你可以问她："你上次整理知识库改了啥？"               │
│                                                          │
│  Step 5：通知你（可选）                                    │
│  QQ消息："主人，我整理了一下知识库，                          │
│          合并了 12 条重复知识，修正了 3 处矛盾，            │
│          归档了 8 条旧信息。现在跑得更快啦～"                │
└─────────────────────────────────────────────────────────┘
```

### 7.5 一个真实的重组案例

```
初始状态（3个月的知识积累，共 200+ 条）：
├── 关于主人
│   ├── 主人在学 Rust（Day 1）
│   ├── 主人觉得 Rust 难（Day 3）
│   ├── 主人用 Rust 写了个小工具（Day 30）
│   ├── 主人说 Rust 真香（Day 45）
│   ├── 主人开始做 Rust 开源贡献（Day 60）
│   ├── 主人喝咖啡（各种零散记录 × 15 条）
│   └── ...（碎片化严重）
├── 技术知识
│   ├── Rust 所有权系统（Day 15）
│   ├── Rust 生命周期注解（Day 20）
│   ├── Rust 异步编程（Day 50）
│   └── ...（散落各处，没有形成知识链）
└── ...

        ↓ 触发重组（碎片化 + 矛盾检测）

重组后：
├── 👤 关于主人
│   ├── 🦀 主人与 Rust（时间线合并）
│   │   └── "主人从 Day1 开始学习 Rust，
│   │       经历入门困难期（Day3-15），
│   │       掌握后开始实践（Day30 写小工具），
│   │       目前进入进阶阶段（Day60 开源贡献）"
│   │       ↑ 原先 5 条碎片合并成 1 条完整线索
│   │
│   └── ☕ 饮食习惯
│       └── "主人固定每天 2 杯美式，上午 9 点和下午 3 点"
│           ↑ 原先 15 条零散的"喝咖啡"记录提炼成 1 条
│
├── 📖 Rust 知识体系（重新分类）
│   ├── 基础概念 → 所有权、借用、生命周期
│   ├── 进阶专题 → 异步编程、宏、unsafe
│   └── 实践 → 主人的项目、踩过的坑
│       ↑ 原先散落的知识点按学习路径重新编排
│
└── 🗄️ 知识归档区
    └── "Rust 比 C++ 难"（旧认知，已被"Rust 真香"替代）
```

### 7.6 知识库的技术实现

```
存储层：
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ SQLite       │     │ Qdrant/LanceDB   │     │ 本地文件系统     │
│ (结构化知识)  │     │ (向量索引)        │     │ (归档/文档原文)   │
│              │     │                  │     │                  │
│ - 知识条目    │     │ - 嵌入向量        │     │ - 完整对话记录    │
│ - 分类树      │     │ - 语义检索        │     │ - 已吸收的文档    │
│ - 版本记录    │     │                  │     │ - 知识快照备份    │
└─────────────┘     └──────────────────┘     └─────────────────┘
```

**知识条目数据结构（SQLite 中的一张表）：**

```sql
CREATE TABLE knowledge_entries (
    id TEXT PRIMARY KEY,            -- 唯一ID
    content TEXT NOT NULL,          -- 知识内容
    category TEXT,                  -- 分类路径："关于主人/饮食习惯"
    tags TEXT,                      -- JSON数组：["编程","Rust"]
    source TEXT,                    -- 来源："qq_chat"/"web_search"/"file_ingest"
    source_ref TEXT,                -- 来源引用（对话ID / URL / 文件路径）
    confidence FLOAT DEFAULT 1.0,   -- 可信度 0~1
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    last_accessed TIMESTAMP,        -- 最后被检索的时间（判断冷热数据）
    version INTEGER DEFAULT 1,      -- 版本号
    previous_id TEXT,               -- 如果这是合并后的新条目，指向被合并的旧条目
    status TEXT DEFAULT 'active'    -- active / archived / superseded
);
```

**核心代码骨架：**

```python
class AutonomousKnowledgeBase:
    """自主知识库：自己建、自己管、自己重组"""

    def __init__(self):
        self.db = SQLite("knowledge.db")           # 结构化存储
        self.vector_db = Qdrant(":memory:")         # 向量索引
        self.embedder = SiliconFlowEmbedder()       # 嵌入模型
        self.llm = OpenAIClient()                   # 用于分类和提炼

    # ===== 采集 =====
    def ingest_from_conversation(self, messages: list):
        """从对话中提取知识"""
        # 调用 LLM 分析对话，提取可结构化的知识点
        prompt = (
            "从以下对话中提取值得存入知识库的信息。"
            "只提取事实性、可复用的知识，不要提取闲聊。"
            "每条知识一行，格式：{类型}|{内容}"
            f"\n\n对话：\n{messages}"
        )
        facts = self.llm.complete(prompt)
        for fact in facts.split("\n"):
            category, content = fact.split("|", 1)
            self.add_entry(content, source="conversation")

    def ingest_from_file(self, file_path: str):
        """从文件中吸收知识（你让她读的文档）"""
        content = read_file(file_path)
        # 分块 → 嵌入 → 存入向量库
        chunks = self._chunk(content)
        for chunk in chunks:
            vector = self.embedder.embed(chunk)
            self.vector_db.upsert(vector, metadata={"source": file_path})

    def ingest_from_web(self, url: str, content: str):
        """从网页内容中提取知识"""
        # 类似文件吸收，但标注来源为 URL
        pass

    # ===== 分类 =====
    def auto_classify(self, entry_id: str):
        """给一条知识自动分类"""
        entry = self.db.get(entry_id)
        # 用 LLM 判断该归到知识树的哪个位置
        existing_categories = self.db.get_all_categories()
        prompt = (
            f"知识库现有分类：{existing_categories}\n"
            f"新知识：{entry.content}\n"
            f"这条知识应该归到哪个分类下？如果现有分类都不合适，建议一个新分类名。"
        )
        category = self.llm.complete(prompt)
        self.db.update(entry_id, category=category)

    # ===== 检索 =====
    def search(self, query: str, top_k: int = 5):
        """语义检索知识库"""
        query_vector = self.embedder.embed(query)
        results = self.vector_db.search(query_vector, limit=top_k)
        # 更新 last_accessed，用于判断冷热数据
        for r in results:
            self.db.touch(r.id)
        return results

    # ===== 重组 =====
    def check_and_reorganize(self):
        """检查是否需要重组，需要就干"""

        # 检查触发条件
        total = self.db.count()
        fragmented = self.db.count_fragmented(max_per_category=20)

        if total < 100 and fragmented == 0:
            return  # 不需要重组

        # 开始重组
        log = []

        # 1. 重复检测
        duplicates = self._find_duplicates()
        for dup_group in duplicates:
            merged = self._merge_entries(dup_group)
            log.append(f"合并 {len(dup_group)} 条重复知识 → {merged.id}")

        # 2. 矛盾检测
        conflicts = self._find_conflicts()
        for conflict_group in conflicts:
            resolved = self._resolve_conflict(conflict_group)
            log.append(f"解决矛盾：{resolved}")

        # 3. 碎片整理
        self._defragment_categories()

        # 4. 冷数据归档
        archived = self._archive_cold_data(days=90)
        log.append(f"归档 {len(archived)} 条冷数据")

        # 5. 重新聚类分类
        self._recluster_all()

        # 6. 保存重组日志
        self._save_reorg_log(log)

        return log

    def _find_duplicates(self):
        """用向量相似度找重复知识"""
        all_entries = self.db.get_all()
        duplicates = []
        seen = set()
        for i, e1 in enumerate(all_entries):
            if e1.id in seen:
                continue
            group = [e1]
            for e2 in all_entries[i+1:]:
                sim = cosine_similarity(e1.vector, e2.vector)
                if sim > 0.92:  # 相似度 > 92% 认为是重复
                    group.append(e2)
                    seen.add(e2.id)
            if len(group) > 1:
                duplicates.append(group)
        return duplicates

    def _merge_entries(self, entries: list):
        """合并重复知识：保留最新的、最完整的"""
        # 按时间排序，最新最完整的是"主版本"
        entries.sort(key=lambda e: (e.confidence, e.updated_at), reverse=True)
        primary = entries[0]
        # 把被合并的标记为 superseded
        for old in entries[1:]:
            self.db.update(old.id, status="superseded", previous_id=primary.id)
        return primary

    def _find_conflicts(self):
        """发现矛盾知识（语义相似但结论相反的条目）"""
        # 用 LLM 做两两对比...
        pass

    def _archive_cold_data(self, days: int):
        """90天没被检索过的知识 → 归档"""
        cold = self.db.find_cold(days)
        for entry in cold:
            self.db.update(entry.id, status="archived")
        return cold

    def _recluster_all(self):
        """全部打回原子条目，重新计算向量，重新聚类"""
        all_entries = self.db.get_active()
        vectors = [self.embedder.embed(e.content) for e in all_entries]

        # 用 HDBSCAN 或 KMeans 聚类
        clusters = hdbscan_cluster(vectors)

        # 每个簇用 LLM 起名
        for cluster_id, indices in clusters.items():
            samples = [all_entries[i].content for i in indices[:5]]
            name = self.llm.complete(
                f"给以下知识组起一个简洁的类目名：{samples}"
            )
            for i in indices:
                self.db.update(all_entries[i].id, category=name)
```

### 7.7 知识库和记忆系统怎么配合

```text
你的消息到达
      │
      ├──→ 记忆系统（Mem0）："上次主人说过这事，当时他是这么说的..."
      │    快速检索最近相关的对话片段
      │
      └──→ 知识库：去查结构化知识
           "主人的公司用 Python + Django（来源：Day45对话）"
           "Django 5.0 的主要新特性是...（来源：网页搜索 Day60）"
           "主人的项目截止 8月15日（来源：Day70对话）"
      │
      ▼
   两个系统的结果合并，注入到 Prompt
   记忆提供"上下文连续性"（刚才在聊什么）
   知识库提供"事实支撑"（关于这个话题，她学到了什么）
```

### 7.8 你能对知识库做什么

| 操作 | 怎么做 | 例子 |
|------|--------|------|
| 告诉她要记住 | "记住：我公司的VPN密码改了" | 她存入知识库，加密 |
| 问她查东西 | "我上次说的那个健身房叫什么" | 她检索知识库回答 |
| 让她忘掉 | "把我跟张三相关的记录都删了" | 软删除 + 确认 |
| 让她检查 | "检查一下你的知识库有没有要整理的" | 触发审计 |
| 看审计日志 | "上次整理知识库改了什么" | 她汇报 changelog |
| 导出 | "把所有知识导出给我" | 生成 Markdown / JSON 导出 |


---

## 八、与之前方案的关键区别

| 维度 | 之前（微信方案） | 现在（QQ方案） |
|------|-----------------|---------------|
| **通信方式** | wxauto UI自动化（不稳定） | NapCatQQ协议（稳定） |
| **账号** | 需要跟你抢微信 | 独立QQ号，不冲突 |
| **多开** | 微信不支持 | QQ完全支持 |
| **桌面交互** | 无 | 悬浮球 + 语音 |
| **身份定位** | "微信女友+管家" | 贴心AI伙伴 |
| **每日简报** | 无 | 开机自动推送 |
| **待办管理** | 无 | 支持 |
| **语音** | 无 | 本地语音输入输出 |
| **知识库** | 无 | 自主搭建、自动分类、自我重组 |

---

## 九、接下来的开发路线

| Phase | 做什么 | 产出 |
|-------|--------|------|
| **Phase 1** | 跑通QQ消息收发+AI回复 | 她能在QQ上跟你对话了 |
| **Phase 2** | 加性格系统 | 她有自己的语气和风格 |
| **Phase 3** | 加记忆系统(Mem0) | 她记得你们聊过什么 |
| **Phase 4** | 加内置工具调用 | 她能操作电脑干活了 |
| **Phase 5** | 技能扩展系统 | 她不会的能自己下载学 |
| **Phase 6** | 自主知识库 | 她自己建、自己管、自己重组 |
| **Phase 7** | 桌面悬浮球 | 开机有球，点开能聊 |
| **Phase 8** | 每日简报+待办 | 开机推送新闻和提醒 |
| **Phase 9** | 语音对话 | 你能跟她说，她能回你 |
| **Phase 10** | 打磨优化 | 速度、容灾、细节 |
