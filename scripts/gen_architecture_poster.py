"""Generate Aerie · 云栖 v9.0.0 system architecture poster — "Frozen Blueprint" aesthetic.

Output: e:\Agent_reply\documents\aerie_architecture_poster.png
"""

from pathlib import Path

# ── Create poster with Pillow ──────────────────────────────────────────
from PIL import Image, ImageDraw, ImageFont

W, H = 3370, 2380  # ~A2 at high DPI
NAVY   = (13, 27, 42)       # #0D1B2A
ICE    = (136, 181, 216)    # #88B5D8
PALE   = (184, 212, 232)    # #B8D4E8
CRIMSON = (139, 34, 82)     # #8B2252
WHITE  = (220, 230, 240)
DIM    = (60, 80, 100)      # for subtle lines
CARD_BG = (18, 35, 55)     # slightly lighter navy

img = Image.new("RGB", (W, H), NAVY)
draw = ImageDraw.Draw(img)

# ── Font loading ───────────────────────────────────────────────────────
def _load(name, size):
    p = Path(r"c:\Users\Administrator\.trae-cn\skills\canvas-design\canvas-fonts") / name
    return ImageFont.truetype(str(p), size) if p.exists() else ImageFont.load_default()

font_label  = _load("JetBrainsMono-Regular.ttf", 16)
font_small  = _load("JetBrainsMono-Regular.ttf", 14)
font_title  = _load("WorkSans-Regular.ttf", 56)
font_subtitle = _load("WorkSans-Regular.ttf", 24)
font_accent  = _load("CrimsonPro-Regular.ttf", 18)

# ── Helpers ────────────────────────────────────────────────────────────
def card(x, y, w, h, label="", desc="", tech="", accent=False):
    """Draw a module card."""
    draw.rectangle([x, y, x+w, y+h], fill=CARD_BG, outline=ICE, width=1)
    # Accent line on left edge
    if accent:
        draw.rectangle([x, y, x+3, y+h], fill=CRIMSON)
    # Label
    if label:
        draw.text((x+16, y+14), label, fill=WHITE, font=font_subtitle)
    # Description
    if desc:
        y_off = y + 46
        for line in desc.split("|"):
            draw.text((x+16, y_off), line.strip(), fill=PALE, font=font_small)
            y_off += 20
    # Tech tags at bottom
    if tech:
        draw.text((x+16, y+h-32), tech, fill=ICE, font=font_label)

def h_connect(x1, y1, x2, y2):
    """Horizontal connection line between two card edges."""
    mid = (x1 + x2) // 2
    draw.line([(x1, y1), (mid, y1)], fill=ICE, width=1)
    draw.line([(mid, y1), (mid, y2)], fill=ICE, width=1)
    draw.line([(mid, y2), (x2, y2)], fill=ICE, width=1)
    # Small dot at endpoints
    r = 3
    for px, py in [(x1, y1), (x2, y2)]:
        draw.ellipse([px-r, py-r, px+r, py+r], fill=CRIMSON)

def v_line(x, y1, y2):
    draw.line([(x, y1), (x, y2)], fill=DIM, width=1)

# ── MARGINS & GRID ─────────────────────────────────────────────────────
mx, my = 60, 60
cw, ch = 480, 260
gap_x, gap_y = 40, 36

# ── Row 1: Core Modules ───────────────────────────────────────────────
col = [mx + i*(cw+gap_x) for i in range(6)]
row = [my + 140 + j*(ch+gap_y) for j in range(4)]

# --- Row 1 ---
y0 = row[0]
card(col[0], y0, cw, ch, "COMPANION · 编排器",
     "中心运行时 | 全子系统组装 | start/stop 生命周期",
     "core/companion.py")
card(col[1], y0, cw, ch, "BRAIN · 调度器",
     "7-Provider fallback 链 | Qwen DeepSeek MiniMax | BigModel SiliconFlow Gemini GPT",
     "core/brain.py · core/providers/*")
card(col[2], y0, cw, ch, "EMOTION · 情感引擎",
     "PAD 三维情感 · 5 类分类 | 4 槽累积阈值 · 角色磨损",
     "core/emotion_engine.py · core/emotion_threshold.py", accent=True)
card(col[3], y0, cw, ch, "PIPELINE · 流水线",
     "路由→情感→上下文→Brain→着色入队 | MarkDown 自动检测",
     "core/pipeline.py · core/context_builder.py")
card(col[4], y0, cw, ch, "PERSONA · 人格引擎",
     "伊塔 v3.1 · 四级决策权重 | Markov 转移矩阵 · 闷骚病娇四爱",
     "persona/decision.py · persona/brain_random.py")
card(col[5], y0, cw, ch, "API · 服务层",
     "28 HTTP 端点 · aiohttp | 127.0.0.1:7890 · 仅本地",
     "core/api_server.py")

# --- Row 2 ---
y1 = row[1]
card(col[0], y1, cw, ch, "QQ CLIENT · 通信",
     "NapCat OneBot11 WebSocket | 收发·撤回·图片·MarkDown | Poke·声聊 DLC",
     "communication/qq_client.py · communication/recall_manager.py")
card(col[1], y1, cw, ch, "SEND QUEUE · 拟人发送",
     "PriorityQueue · 5 级节奏 | 语义分段 8 模式 · 撤回联动",
     "communication/send_queue.py · communication/splitter.py")
card(col[2], y1, cw, ch, "PROACTIVE · 主动推送",
     "9 场景 · Cron 定时轮询 | 频控·静默·暂停·豁免 | 情感触发联动",
     "proactive/messenger.py · proactive/policy.py · scheduler/cron.py", accent=True)
card(col[3], y1, cw, ch, "TOOLS · 工具系统",
     "16 工具 · Function Calling | 知识·待办·截图·音乐·天气·系统",
     "core/tool_registry.py · core/function_calling.py · tools/")
card(col[4], y1, cw, ch, "MEMORY · 记忆层",
     "短期 8 条 · 长期 SQLite | 知识库 4 类目 · 关键词检索",
     "memory/memory_store.py · memory/short_term.py · knowledge/kb.py")
card(col[5], y1, cw, ch, "VOICE · 声聊模块",
     "MiniMax TTS · Silk 编码 FFmpeg | NapCat send_record 语音消息",
     "voice/tts_engine.py · voice/silk_encoder.py")

# --- Row 3: Infrastructure ---
y2 = row[2]
card(col[0], y2, cw, ch, "DATABASE · 数据层",
     "SQLite 9 表 · 参数化查询 | chat_log·emotion_log·token_usage·push_log",
     "core/database.py · core/token_tracker.py")

x_elec = col[1]
ew, eh = cw*3 + gap_x*2, ch
card(col[1], y2, ew, eh, "ELECTRON · 前端",
     "主窗口·悬浮球·托盘·IPC | contextIsolation:true nodeIntegration:false | 5 主题切换器 · 侧边栏 5 Tab",
     "electron/src/main.js · preload.js · renderer/ · 打包: NSIS + Portable")

card(col[4], y2, cw, ch, "BACKUP · 备份",
     "zip 备份·7 天清理·一键迁移 | 每日 04:00 自动备份",
     "core/backup.py")
card(col[5], y2, cw, ch, "SYS · 基础设施",
     "UAC 提权·Task Scheduler | 系统监控·14 故障自愈",
     "core/elevator.py · core/task_scheduler.py · core/system_monitor.py")

# --- Row 4: External connections ---
y3 = row[3]
# NapCat block
card(col[0], y3, cw//2+20, 180, "NAPCAT",
     "v4.18.9 · QQ 9.9.26 | PacketBackend · OneBot11",
     "ws://127.0.0.1:3001")
# LLM block
llm_x = col[1] + (cw//2+20) + gap_x
card(llm_x, y3, cw*3 + gap_x*2 - (cw//2+20) - gap_x*2, 180,
     "LLM PROVIDERS · 7 模型",
     "DeepSeek · MiniMax-M3 · BigModel GLM-4 · SiliconFlow Gemma | Qwen-plus · Gemini Flash · GPT-5.5 (Proxy)",
     "core/providers/*.py · .env API Keys")

# ── Connection lines ───────────────────────────────────────────────────
# Row 1 → Row 2: Pipeline connects to QQ / SendQueue / Tools
h_connect(col[3]+cw//2, y0+ch, col[0]+cw//2, y1)       # Pipeline → QQ
h_connect(col[3]+cw//2, y0+ch+4, col[1]+cw//2, y1+4)   # Pipeline → SendQueue
h_connect(col[3]+cw//2, y0+ch+8, col[3]+cw//2, y1+8)   # Pipeline → Tools

# Brain → Providers
h_connect(col[1]+cw//2, y0+ch, col[3]+cw//2, y1-20)    # Brain → Tools

# Companion → everything
v_line(col[0]+cw//2, y0+ch, y1)                         # Companion ↓

# Emotion → Proactive
h_connect(col[2]+cw//2, y0+ch, col[2]+cw//2, y1)       # Emotion → Proactive

# QQ Client → NapCat
h_connect(col[0]+cw//2, y1+ch, col[0]+cw//4, y3)       # QQ → NapCat

# Tools → Voice
h_connect(col[3]+cw//2, y1+ch, col[5]+cw//2, y1+20)    # Tools → Voice

# Database → all bottom
draw.line([(col[0]+cw//2, y2+ch), (col[0]+cw//2, y3)], fill=DIM, width=1)

# ── Title block ────────────────────────────────────────────────────────
draw.text((mx, my), "AERIE", fill=WHITE, font=font_title)
draw.text((mx + 170, my + 74), "· 云 栖", fill=PALE, font=_load("WorkSans-Regular.ttf", 36))
draw.text((mx, my + 120), "v9.0.0", fill=CRIMSON, font=font_label)
draw.text((mx, my + 144), "SYSTEM ARCHITECTURE · FROZEN BLUEPRINT", fill=DIM, font=font_small)

# ── Footer ─────────────────────────────────────────────────────────────
draw.text((mx, H - 50), "PYTHON 3.14.3  ·  ASYNCIO  ·  WINDOWS 11  ·  NODE.JS 24.14.1  ·  ELECTRON 28",
          fill=DIM, font=font_small)
draw.text((W - mx - 200, H - 50), "2026/07/16 · AERIE/9.0.0/FP-1", fill=DIM, font=font_label)

# ── Top-right thin crimson accent bar ──────────────────────────────────
draw.rectangle([W-12, 60, W-2, H-60], fill=CRIMSON)

# ── Title divider line ─────────────────────────────────────────────────
draw.line([(mx, my+170), (W-mx-30, my+170)], fill=ICE, width=1)
# Small crimson dot at start
draw.ellipse([mx-3, my+167, mx+3, my+173], fill=CRIMSON)

# ── Save ───────────────────────────────────────────────────────────────
out = Path(r"e:\Agent_reply\documents\aerie_architecture_poster.png")
img.save(str(out), "PNG")
print(f"Saved: {out}  ({W}x{H})")
