"""Aerie · 云栖 v0.1.0-beta.1 — Skill scaffold generator (Block-4C R3.3 + Block-5B).

Generates the 50 skeleton skills (12 local + 5 data + 33 cloud) under
``skills/{local,data,cloud}/<name>/``. Each skill gets:

  - ``SKILL.md`` with YAML frontmatter (name / description / provider_hint / read_only,
    以及可选的可用性声明 ``requires_module`` / ``requires_env``：声明的前提不满足时
    SkillLoader **不注册**该 skill，模型看不到跑不了的工具)
  - ``run.py`` exporting ``run(args: dict) -> dict`` with a stub body
    that returns ``{"status": "stub", "error": "dependency_missing"}`` when
    the underlying native module is not installed.

Idempotent: re-running the script on an existing skill overwrites the
files (useful for re-aligning frontmatter after config changes). It
never touches non-skill files under the project root.

Usage:
    python tools/scaffold_skills.py            # create all 50
    python tools/scaffold_skills.py --dry-run  # preview only
"""

from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from textwrap import dedent

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
SKILLS_ROOT = _PROJECT_ROOT / "skills"


# ── Skill catalog: local ─────────────────────────────────────
#
# 语音口径（A3，2026-09-30 定）：**本地语音能力由功能包提供，不再由 local skill 提供**。
# 原先的 `asr` / `tts` 两个 local 桩（`requires_module: local_asr` / `local_tts`，
# 这两个 Python 模块本仓从来没实现过）已删除 —— 留着就是"面板上永远不可用、
# 对应能力其实由 voice-asr / voice-rvc 功能包提供"的两套实现，正是计划要避免的。
# 语音相关能力请走 `plugins/voice-asr`（ASR + KWS）与 `plugins/voice-rvc`（TTS + 变声）。
LOCAL_SKILLS: list[dict] = [
    {
        "name": "ocr",
        "description": "图像文字识别 / OCR",
        "provider_hint": "ocr-pp",
        "read_only": True,
        "import_module": "local_ocr_npu",
        "import_call": "recognize",
        "args_key": "image_path",
        "return_key": "text",
        "body_doc": "调本地 NPU PP-OCRv5 提取图像文字，输出 text。",
    },
    {
        "name": "img2img",
        "description": "图像编辑 / Image-to-image",
        "provider_hint": "image-sdxl",
        "read_only": False,
        "import_module": "local_img2img",
        "import_call": "transform",
        "args_key": "source",
        "return_key": "output_path",
        "body_doc": "调本地 SDXL img2img，prompt + source → output_path。",
    },
    {
        "name": "txt2img",
        "description": "文生图 / Text-to-image",
        "provider_hint": "image-sdxl",
        "read_only": False,
        "import_module": "local_txt2img",
        "import_call": "generate",
        "args_key": "prompt",
        "return_key": "output_path",
        "body_doc": "调本地 SDXL 文生图，prompt → output_path。",
    },
    {
        "name": "screenshot-qa",
        "description": "截图问答 / Screenshot Q&A",
        "provider_hint": "vision-llava",
        "read_only": True,
        "import_module": "local_screenshot_qa",
        "import_call": "ask",
        "args_key": "image_path",
        "return_key": "answer",
        "body_doc": "调本地 vision LLaVA 答屏上问题，输出 answer。",
    },
    {
        "name": "mineru",
        "description": "PDF/文档解析 / Document parse",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "local_mineru",
        "import_call": "parse",
        "args_key": "file_path",
        "return_key": "markdown",
        "body_doc": "调本地 MinerU 解析 PDF/图片，输出 markdown。",
    },
    {
        "name": "realtime-translator",
        "description": "实时翻译 / Realtime translate",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "local_realtime_translator",
        "import_call": "run",
        "args_key": "src",
        "return_key": "status",
        "body_doc": "调本地实时翻译模块跑 src→tgt，返 status。",
    },
    {
        "name": "vram",
        "description": "显存调整 / GPU VRAM limit",
        "provider_hint": "shell-safe",
        "read_only": False,
        "import_module": "local_vram",
        "import_call": "set_limit",
        "args_key": "percent",
        "return_key": "ok",
        "body_doc": "调本地 VRAM 调整器设置百分比，返 ok。",
    },
    {
        "name": "computer-use",
        "description": "系统状态查询 / System query",
        "provider_hint": "shell-safe",
        "read_only": True,
        "import_module": "local_computer_use",
        "import_call": "query",
        "args_key": "category",
        "return_key": "value",
        "body_doc": "调本地系统状态查询器，输出 value。",
    },
    {
        "name": "markitdown",
        "description": "Office→MD / Office to Markdown",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "markitdown",
        "import_call": "MarkItDown",
        "args_key": "file_path",
        "return_key": "markdown",
        "body_doc": "调 markitdown[all] 把 Office/PDF 转 markdown。",
    },
    {
        "name": "git-commit",
        "description": "提交信息生成 / Commit message gen",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "git_commit",
        "import_call": "generate",
        "args_key": "diff_text",
        "return_key": "message",
        "body_doc": "调 git-commit 模块基于 diff 生成提交信息。",
    },
]

# ── Skill catalog: 5 data read-only ──────────────────────────
DATA_SKILLS: list[dict] = [
    # notion-cli 桩已移除。Notion 的读写能力改由 MCP 通道提供
    # （config/mcp_servers.yaml 的 notion 预设，stdio + 个人访问令牌）。
    # 原桩声明 requires_module: notion_cli，而该 Python 模块根本不存在 ——
    # 一个永远不可能可用的僵尸条目。
    {
        "name": "figma",
        "description": "Figma MCP 调用 / Figma MCP",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "figma_mcp",
        "import_call": "call",
        "args_key": "method",
        "return_key": "data",
        "body_doc": "Figma MCP 客户端；无 token 返 stub。",
    },
    {
        "name": "obsidian-cli",
        "description": "Obsidian CLI 调用 / Obsidian vault",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "obsidian_cli",
        "import_call": "run",
        "args_key": "subcommand",
        "return_key": "stdout",
        "body_doc": "子进程调 obs CLI，返 stdout/stderr。",
    },
    {
        "name": "obsidian-bases",
        "description": "Obsidian Bases 读取 / Obsidian Bases",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "obsidian_bases",
        "import_call": "load",
        "args_key": "base_path",
        "return_key": "structure",
        "body_doc": "读 .base YAML → 返回结构。",
    },
    {
        "name": "spec-to-impl",
        "description": "Spec→tasks 拆解 / Spec to implementation",
        "provider_hint": "text",
        "read_only": True,
        "import_module": "spec_to_impl",
        "import_call": "decompose",
        "args_key": "spec_text",
        "return_key": "tasks",
        "body_doc": "LLM 调 spec 拆 tasks，无 LLM 返 stub。",
    },
]

# ── Skill catalog: 33 cloud (Block-5B 扩) ───────────────────
# 这些 skill 走云端 API，env 变量存 token；缺失时统一返 stub + 错误码
# 安全：所有 cloud skill 标记 read_only=True（默认不写），标记 env 变量名供 skill_loader 提示
CLOUD_SKILLS: list[dict] = [
    # ── 商业/支付/合规 (4) ──
    # tianyan 桩已移除。天眼查能力改由 MCP 通道提供
    # （config/mcp_servers.yaml 的 tianyancha 预设，远程 HTTP）。
    # 凭据 TIANYAN_TOKEN 仍保留在设置页「平台凭证」里 —— MCP 预设引用它。
    {
        "name": "alipay-payment",
        "description": "支付宝开放平台 / Alipay",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "ALIPAY_APP_ID",
        "stub_note": "本轮不做，涉及真实资金（用户已拍板）。条目保留是为了让面板能看出"
                     "是故意没做，不是坏了",
        "args_key": "out_trade_no",
        "return_key": "trade_status",
        "body_doc": "支付宝当面付/JSAPI/App 支付下单与查单。",
    },
    {
        "name": "douyinpay-payment",
        "description": "抖音支付 / DouyinPay",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "DOUYINPAY_MCH_ID",
        "stub_note": "本轮不做，涉及真实资金（用户已拍板）。条目保留是为了让面板能看出"
                     "是故意没做，不是坏了",
        "args_key": "out_order_no",
        "return_key": "pay_status",
        "body_doc": "抖音支付 APP/JSAPI/H5/Native 支付下单与查单。",
    },
    {
        "name": "security-review",
        "description": "安全审查 / Security review",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "diff_text",
        "return_key": "findings",
        "body_doc": "对代码 diff 做 path_traversal / unsafe_deserialization / xss / ssrf 风险扫描。",
    },
    # ── 字节跳动 / 火山引擎 (5) ──
    {
        "name": "byted-bp-cdn-pagesdeploy",
        "description": "字节边缘 Pages 部署 / BytePlus Pages（官方 CLI）",
        "provider_hint": "shell-safe",
        "read_only": False,
        "env_var": "",
        "cli": "nest",          # 凭据由 `nest config set` 写进 CLI 自己的配置
        "stub": False,
        "args_key": "project_dir",
        "return_key": "url",
        "body_doc": "一键部署静态站到 BytePlus Edge Pages；含域名绑定与 CDN。",
    },
    {
        "name": "byted-mediakit",
        "description": "字节 AI MediaKit 音视频处理 / ByteDance mediakit（官方 CLI）",
        "provider_hint": "shell-safe",
        "read_only": False,
        "env_var": "",
        "cli": "mediakit-cli",  # 凭据由 `mediakit-cli init --api-key` 写进 CLI 自己的配置
        "stub": False,
        "args_key": "input_path",
        "return_key": "output_path",
        "body_doc": "音视频剪辑、格式转换、抽帧等。",
    },
    {
        "name": "byted-seedance",
        "description": "Seedance 文生视频 / Seedance video",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "SEEDANCE_KEY",
        "args_key": "prompt",
        "return_key": "video_url",
        "body_doc": "Seedance 模型文生视频；支持图生视频与参考视频。",
    },
    {
        "name": "byted-seedream",
        "description": "Seedream 文生图 / Seedream image",
        "provider_hint": "image-sdxl",
        "read_only": False,
        "env_var": "SEEDREAM_KEY",
        "args_key": "prompt",
        "return_key": "image_url",
        "body_doc": "Seedream 高质量文生图；多风格多尺寸。",
    },
    {
        "name": "volcengine-tos",
        "description": "火山引擎对象存储 / TOS",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "TOS_AK",
        "args_key": "key",
        "return_key": "url",
        "body_doc": "上传/下载/签名 URL 火山 TOS。",
    },
    # ── 平台部署 / 文档 (4) ──
    {
        "name": "iga-pages",
        "description": "IGA Pages 部署 / IGA Pages（未接入）",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "IGAPAGES_TOKEN",
        "stub_note": "未接入：IGA Pages 官方只提供控制台部署（模板 / ZIP 上传 / GitHub 导入），"
                     "没有公开的 REST 或 CLI 契约；IGA 的 OpenAPI 只管边缘加速域名（CreateDomain），"
                     "不能创建 Pages 项目",
        "args_key": "project_dir",
        "return_key": "url",
        "body_doc": "IGA Pages 部署前端与全栈项目；带预览部署。",
    },
    {
        "name": "gh-cli",
        "description": "GitHub CLI / gh",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "GH_TOKEN",
        "args_key": "subcommand",
        "return_key": "stdout",
        "body_doc": "gh CLI 仓库 / Issue / PR / Actions / Release 操作。",
    },
    {
        "name": "electron",
        "description": "Electron 自动化 / Electron",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "app_path",
        "return_key": "elements",
        "body_doc": "agent-browser 走 Chrome DevTools Protocol 自动化 Electron 桌面应用。",
    },
    # screenshot 桩已移除，不再生成。截图能力由内置工具承担：
    # core/computer_control.py 的 ScreenshotCapturer（Pillow ImageGrab + GDI 回退），
    # 经 tools/compute_tools.py 注册为工具 `screenshot`。再放一个同名桩只会造成
    # "面板上不可用、模型那里其实可用"的错位（skill_loader 也会因撞名拒绝注册）。
    # ── Notion 套件（桩已移除） ──
    # 四个 notion-* 工作流（知识捕获 / 会议情报 / 跨库研究 / spec 拆任务）已转为
    # **指令型** skill（frontmatter 声明 kind: instruction），由 core/skill_instructions.py
    # 按触发词注入上下文，不再生成 run.py；Notion 的读写能力由 MCP 通道提供。
    # notion-cli 桩同样删除（它声明的 notion_cli 模块并不存在）。
    # 这里保留空段以标记位置，避免后人以为漏了。
    # ── Obsidian 套件 (3) ──
    {
        "name": "obsidian-markdown",
        "description": "Obsidian Markdown / Obsidian MD",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "content",
        "return_key": "rendered",
        "body_doc": "Obsidian Flavored Markdown 渲染（callouts / wikilinks / properties）。",
    },
    {
        "name": "obsidian-bases",
        "description": "Obsidian Bases / Bases",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "base_path",
        "return_key": "structure",
        "body_doc": "读 .base YAML → 返回结构。",
        "_is_dup": True,
    },
    {
        "name": "obsidian-cli",
        "description": "Obsidian CLI / Obsidian",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "subcommand",
        "return_key": "stdout",
        "body_doc": "obs CLI 包装。",
        "_is_dup": True,
    },
    # ── 内容创作 / 视觉 (7) ──
    {
        "name": "algorithmic-art",
        "description": "算法艺术 / Algorithmic art",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "seed",
        "return_key": "p5_url",
        "body_doc": "p5.js seeded randomness + 交互参数艺术。",
    },
    {
        "name": "canvas-design",
        "description": "海报/画布设计 / Canvas design",
        "provider_hint": "image-sdxl",
        "read_only": False,
        "env_var": "",
        "args_key": "topic",
        "return_key": "png_path",
        "body_doc": "海报/艺术/设计/静态视觉 → PNG/PDF。",
    },
    {
        "name": "frontend-design",
        "description": "前端组件设计 / Frontend design",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "spec",
        "return_key": "html_path",
        "body_doc": "生产级前端 UI/页面/组件；高设计质量。",
    },
    {
        "name": "frontend-skill",
        "description": "前端着陆页设计 / Frontend skill",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "topic",
        "return_key": "html_path",
        "body_doc": "着陆页/网站/应用/原型/游戏 UI。",
    },
    {
        "name": "web-artifacts-builder",
        "description": "复杂 artifact 构建 / Web artifacts",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "spec",
        "return_key": "html_path",
        "body_doc": "React + Tailwind + shadcn/ui 复杂 artifact。",
    },
    {
        "name": "web-design-guidelines",
        "description": "Web 设计审查 / Web guidelines",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "html",
        "return_key": "findings",
        "body_doc": "Web Interface Guidelines 合规性审查。",
    },
    {
        "name": "webapp-testing",
        "description": "Web 应用测试 / Webapp testing",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "url",
        "return_key": "report",
        "body_doc": "Playwright 验证前端功能 / 截屏 / 浏览器日志。",
    },
    {
        "name": "shadcn",
        "description": "shadcn/ui 组件 / shadcn",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "component",
        "return_key": "code",
        "body_doc": "shadcn 组件管理（add/search/fix/composing）。",
    },
    # ── 视频/动画/演示 (5) ──
    {
        "name": "gsap",
        "description": "GSAP 动画 / GSAP",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "spec",
        "return_key": "code",
        "body_doc": "GSAP timeline / fromTo / stagger / scrollTrigger。",
    },
    {
        "name": "hyperframes",
        "description": "HyperFrames 视频合成 / HyperFrames",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "spec",
        "return_key": "video_path",
        "body_doc": "HyperFrames HTML 视频合成；含 caption / TTS / audio-reactive。",
    },
    {
        "name": "hyperframes-media",
        "description": "HyperFrames 媒体预处理 / HF media",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "asset",
        "return_key": "processed",
        "body_doc": "TTS Kokoro / Whisper 转录 / 抠图。",
    },
    {
        "name": "hyperframes-registry",
        "description": "HyperFrames 块注册 / HF registry",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "block",
        "return_key": "ok",
        "body_doc": "安装 / 接入 hyperframes 块与组件。",
    },
    {
        "name": "slides",
        "description": "PowerPoint 幻灯片 / Slides",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "outline",
        "return_key": "pptx_path",
        "body_doc": "PptxGenJS 生成 .pptx；含图表 / 视觉。",
    },
    {
        "name": "ppt-page",
        "description": "HTML PPT 单页 / PPT page",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "outline",
        "return_key": "html_path",
        "body_doc": "单文件 HTML PPT 画廊（垂直单列 + 卡片）。",
    },
    # ── 文档/报告/数据 (5) ──
    {
        "name": "doc-page",
        "description": "可打印文档页 / Doc page",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "topic",
        "return_key": "pdf_path",
        "body_doc": "报告/表单/排班/简历/备忘录 A4 排版 + PDF/DOCX 导出。",
    },
    {
        "name": "report-page",
        "description": "源引用报告 / Report page",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "data",
        "return_key": "html_path",
        "body_doc": "可编辑静态 HTML + 干净阅读体验 + ECharts 图。",
    },
    {
        "name": "dashboard-page",
        "description": "本地离线仪表盘 / Dashboard",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "data",
        "return_path": "html_path",
        "return_key": "html_path",
        "body_doc": "ECharts KPI 仪表盘 + 时间控件 + 数据源弹窗。",
    },
    {
        "name": "chart-visualization",
        "description": "图表可视化 / Chart viz",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "data",
        "return_key": "image_path",
        "body_doc": "26 种图表选最优并渲染。",
    },
    # data-analysis 桩已移除。表格/CSV 分析由内置工具
    # core/office_tools.py 的 spreadsheet_analyze 承担，模型侧已可见。
    {
        "name": "consulting-analysis",
        "description": "咨询级报告 / Consulting",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "topic",
        "return_key": "report_path",
        "body_doc": "市场 / 消费者 / 品牌 / 财务分析两阶段报告。",
    },
    {
        "name": "doc-coauthoring",
        "description": "文档协作 / Doc coauthoring",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "draft",
        "return_key": "doc",
        "body_doc": "结构化协作文档（提案/技术 spec/决策记录）。",
    },
    {
        "name": "internal-comms",
        "description": "内部沟通 / Internal comms",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "topic",
        "return_key": "memo",
        "body_doc": "状态报告/管理层更新/3P/Newsletter/FAQ/事故报告。",
    },
    # ── 创作/规划/检索 (5) ──
    {
        "name": "brainstorming",
        "description": "需求探索 / Brainstorming",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "intent",
        "return_key": "spec",
        "body_doc": "在写代码前探索用户意图 / 需求 / 设计。",
    },
    {
        "name": "writing-plans",
        "description": "写实施计划 / Writing plans",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "spec",
        "return_key": "plan_md",
        "body_doc": "多步任务前的实施计划。",
    },
    {
        "name": "executing-plans",
        "description": "执行计划 / Executing plans",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "plan_id",
        "return_key": "status",
        "body_doc": "带检查点的实施会话。",
    },
    {
        "name": "test-driven-development",
        "description": "TDD / Test-driven",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "feature",
        "return_key": "tests",
        "body_doc": "实现前先写测试。",
    },
    {
        "name": "dogfood",
        "description": "Bug 猎手 / Dogfood",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "url",
        "return_key": "report",
        "body_doc": "系统性测试 web app 出结构化报告。",
    },
    {
        "name": "brand-guidelines",
        "description": "Anthropic 品牌指南 / Brand",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "asset",
        "return_key": "styled",
        "body_doc": "应用 Anthropic 官方品牌色与字体。",
    },
    {
        "name": "theme-factory",
        "description": "主题工厂 / Theme factory",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "artifact",
        "return_key": "themed",
        "body_doc": "10 预置主题或即时生成主题。",
    },
    # ── MCP / JSON Canvas / 工具 (4) ──
    {
        "name": "mcp-builder",
        "description": "MCP 服务器构建 / MCP builder",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "service_spec",
        "return_key": "server_path",
        "body_doc": "构建 MCP 服务（Python FastMCP / Node SDK）。",
    },
    {
        "name": "json-canvas",
        "description": "JSON Canvas / Canvas",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "diagram",
        "return_key": "canvas_path",
        "body_doc": "Obsidian .canvas（节点/边/组）。",
    },
    {
        "name": "redis-development",
        "description": "Redis 开发 / Redis",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "REDIS_URL",
        "args_key": "query",
        "return_key": "result",
        "body_doc": "Redis 数据结构 / RQE / 向量检索 / 性能优化。",
    },
    {
        "name": "vercel-react",
        "description": "Vercel React 最佳实践 / Vercel React",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "code",
        "return_key": "review",
        "body_doc": "React/Next.js 性能优化指南。",
    },
    {
        "name": "vercel-react-native",
        "description": "Vercel RN 最佳实践 / Vercel RN",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "code",
        "return_key": "review",
        "body_doc": "React Native / Expo 最佳实践。",
    },
    {
        "name": "vercel-composition",
        "description": "Vercel 组合模式 / Vercel composition",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "code",
        "return_key": "review",
        "body_doc": "React 19 组合模式（compound/render props/context）。",
    },
    {
        "name": "defuddle",
        "description": "Defuddle 网页抓取 / Defuddle",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "url",
        "return_key": "markdown",
        "body_doc": "从网页抽干净 markdown。",
    },
    # ── 抖音 / 互动内容 (2) ──
    {
        "name": "douyin-interact-creation",
        "description": "抖音互动 H5 / Interact creation",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "",
        "args_key": "spec",
        "return_key": "h5_zip",
        "body_doc": "抖音互动空间 H5 单文件 index.html / zip。",
    },
    {
        "name": "douyin-interactive-publish",
        "description": "抖音互动空间发布 / Interact publish",
        "provider_hint": "text",
        "read_only": False,
        "env_var": "DOUYIN_OPEN_ID",
        "stub_note": "本轮不做，涉及真实账号对外发布（用户已拍板）。条目保留是为了让面板能看出"
                     "是故意没做，不是坏了",
        "args_key": "zip_path",
        "return_key": "app_id",
        "body_doc": "上传 zip+icon 创建/更新互动空间。",
    },
    # ── 视频分析 (2) ──
    {
        "name": "hook-analyzer",
        "description": "视频前 3 秒钩子 / Hook analyzer",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "breakdown_json",
        "return_key": "report",
        "body_doc": "视频前 3 秒分镜钩子吸引力分析。",
    },
    {
        "name": "report-generator",
        "description": "视频分析报告 / Report gen",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "breakdown_json",
        "return_key": "report_md",
        "body_doc": "分镜 + 钩子 + BGM + 场景分析报告。",
    },
    # ── 与 local/data 重名的占位（不生成） ──
    # agent-browser 桩已移除。浏览器自动化由内置工具承担：
    # tools/browser_tools.py 的 browser_navigate / browser_snapshot / browser_click
    # 等（Kimi WebBridge，HTTP 127.0.0.1:10086）。
    {
        "name": "spec-to-impl",
        "description": "Spec→任务拆解 / Spec to impl",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "spec_text",
        "return_key": "tasks",
        "body_doc": "拆解 spec 为可执行任务。",
        "_is_dup": True,
    },
    {
        "name": "figma",
        "description": "Figma MCP / Figma",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "FIGMA_TOKEN",
        "args_key": "method",
        "return_key": "data",
        "body_doc": "Figma MCP 客户端。",
        "_is_dup": True,
    },
    {
        "name": "git-commit",
        "description": "git 提交信息生成 / git commit",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "diff_text",
        "return_key": "message",
        "body_doc": "基于 diff 生成 commit 信息。",
        "_is_dup": True,
    },
    {
        "name": "markitdown",
        "description": "MarkItDown / Office to MD",
        "provider_hint": "text",
        "read_only": True,
        "env_var": "",
        "args_key": "file_path",
        "return_key": "markdown",
        "body_doc": "Office / PDF → Markdown。",
        "_is_dup": True,
    },
]


def _skill_md(meta: dict, kind: str) -> str:
    """Build SKILL.md with YAML frontmatter + body."""
    is_cloud = "env_var" in meta
    env_line = (
        f"- 环境变量：`{meta['env_var']}`（缺失时返 stub）" if (is_cloud and meta.get("env_var")) else "- 无需凭据"
    )
    body = dedent(
        f"""
        # {meta["name"]} / {meta["description"].split(" / ")[0]}

        {meta["body_doc"]}

        ## 入参
        - `{meta["args_key"]}`：核心入参（见具体 run.py）
        - 其余键透传至底层模块

        ## 出参
        - 成功：`{{"status": "ok", "{meta["return_key"]}": ...}}`
        - 依赖缺失：`{{"status": "stub", "error": "..."}}`
        - 异常：`{{"status": "error", "error": "..."}}`

        ## 凭据
        {env_line}

        ## 安全
        - read_only = `{str(meta["read_only"]).lower()}`，由 SkillLoader 强制
        - run.py 不主动调子进程 / shell，依赖底层模块自管安全
        - 路径解析走项目根白名单

        provider_hint: `{meta["provider_hint"]}`
        """
    ).strip() + "\n"
    # 可用性声明：让"跑不了的 skill"不进模型可见的工具清单（§十四 #63 / #74）。
    # 直接由 catalog 已有字段派生，避免同一事实写两处 —— 重新生成不会丢。
    #
    # 占位口径（A1，2026-09-30 收敛）：
    #   - cloud 默认仍是占位桩（run.py 恒返 cloud_call_not_implemented）→
    #     声明 implemented: false；若给了 stub_note，一并写出去，面板就能显示
    #     「是故意没做 + 原因」而不是一个沉默的 false。
    #   - 已经换成真实现的（官方 CLI / SDK）在 catalog 里标 stub: False，
    #     用 cli: <二进制名> 声明 requires_cli（凭据由 CLI 自己持有，不写 requires_env）。
    is_stub = kind == "cloud" and meta.get("stub", True)
    requires = ""
    if is_stub:
        requires += "implemented: false\n"
        note = str(meta.get("stub_note") or "").strip()
        if note:
            requires += f"not_implemented_note: {json.dumps(note, ensure_ascii=False)}\n"
    if meta.get("import_module"):
        requires += f"requires_module: {meta['import_module']}\n"
    cli_name = str(meta.get("cli") or "").strip()
    if cli_name:
        requires += f"requires_cli: {cli_name}\n"
    elif str(meta.get("env_var") or "").strip():
        requires += f"requires_env: {meta['env_var']}\n"
    front = (
        "---\n"
        f"name: {meta['name']}\n"
        f"description: {meta['description']}\n"
        f"provider_hint: {meta['provider_hint']}\n"
        f"read_only: {str(meta['read_only']).lower()}\n"
        f"{requires}"
        "---\n\n"
    )
    return front + body


def _run_py(meta: dict) -> str:
    """Build run.py with a stub body.

    - local/data: try `from {module} import {call}`; on ImportError → stub
    - cloud: 查 env_var；缺失 → stub with credential_missing；否则仍 stub（真实调用待实现）
    """
    desc = meta["description"]
    is_cloud = "env_var" in meta
    env_var = meta.get("env_var", "")
    arg = meta["args_key"]
    ret = meta["return_key"]
    name = meta["name"]

    if not is_cloud:
        # local / data
        module = meta["import_module"]
        call = meta["import_call"]
        body = dedent(
            f'''\
            """{name} skill — {desc}.

            Block-4C R3.3 scaffold. Tries to call the native module
            ``{module}`` when it is importable; otherwise returns a stub
            response so the main pipeline is never broken by a missing
            dependency.

            Stub contract:
              - missing required arg  -> {{"error": "missing <key>"}}
              - module not installed  -> {{"status": "stub", "error": "..."}}
              - other exception       -> {{"status": "error", "error": "..."}}
            """
            from __future__ import annotations
            import logging
            import os
            logger = logging.getLogger(__name__)

            PROVIDER_HINT = "{meta["provider_hint"]}"
            READ_ONLY = {meta["read_only"]!r}


            def run(args: dict) -> dict:
                """Skill entry point. ``args`` is a free-form dict from
                the API caller; convention keys: {arg!r}.
                """
                args = args or {{}}
                {arg}_value = args.get("{arg}")
                if not {arg}_value:
                    return {{"error": "missing {arg}", "provider_hint": PROVIDER_HINT}}

                try:
                    from {module} import {call} as _impl
                except ImportError as e:
                    return {{
                        "status": "stub",
                        "error": f"{module} not installed: {{e}}",
                        "provider_hint": PROVIDER_HINT,
                        "read_only": READ_ONLY,
                        "{arg}": str({arg}_value)[:80],
                    }}

                try:
                    result = _impl({arg}_value, **{{k: v for k, v in args.items() if k != "{arg}"}})
                except Exception as e:
                    logger.exception("{name} skill failed")
                    return {{"status": "error", "error": str(e), "provider_hint": PROVIDER_HINT}}

                if not isinstance(result, dict):
                    result = {{"{ret}": result}}
                result.setdefault("status", "ok")
                result.setdefault("provider_hint", PROVIDER_HINT)
                result.setdefault("read_only", READ_ONLY)
                return result
            '''
        )
    else:
        # cloud
        env_check = (
            f"os.getenv({env_var!r})"
            if env_var else "True  # 无需凭据"
        )
        body = dedent(
            f'''\
            """{name} skill (cloud) — {desc}.

            Block-5B scaffold. Cloud-based skill that requires external
            credentials (env: `{env_var or "none"}`). When the env var is
            missing we return a stub so the main pipeline is never broken.
            The actual HTTP/sign/SDK call is intentionally a TODO until
            the corresponding cloud account is provisioned.
            """
            from __future__ import annotations
            import logging
            import os
            logger = logging.getLogger(__name__)

            PROVIDER_HINT = "{meta["provider_hint"]}"
            READ_ONLY = {meta["read_only"]!r}
            ENV_VAR = {env_var!r}


            def run(args: dict) -> dict:
                """Skill entry point. ``args`` is a free-form dict; key: {arg!r}."""
                args = args or {{}}
                {arg}_value = args.get("{arg}")
                if not {arg}_value:
                    return {{"error": "missing {arg}", "provider_hint": PROVIDER_HINT}}

                if not {env_check}:
                    return {{
                        "status": "stub",
                        "error": f"credential_missing: env {{ENV_VAR!r}} not set",
                        "provider_hint": PROVIDER_HINT,
                        "read_only": READ_ONLY,
                        "{arg}": str({arg}_value)[:80],
                    }}

                # TODO: actual cloud call
                return {{
                    "status": "stub",
                    "error": "cloud_call_not_implemented",
                    "provider_hint": PROVIDER_HINT,
                    "read_only": READ_ONLY,
                    "env": ENV_VAR,
                    "note": "real SDK call pending cloud account provisioning",
                }}
            '''
        )
    return body


def scaffold(dry_run: bool = False, *, force: bool = False) -> int:
    """Generate the skill skeletons. Returns the count actually written.

    **默认不覆盖已存在的文件**：SKILL.md 与 run.py 一旦被人手写成真实内容
    （指令型正文 / 真接 SDK），再跑一次生成器把它冲掉就是灾难 —— 与
    「根目录 main.js 双写互毁」是同一类陷阱。需要重新对齐 frontmatter 时
    显式传 ``force=True``（或先删掉目标文件）。
    """
    written = 0
    skipped = 0
    plans: list[tuple[Path, Path, dict]] = []
    seen: set[str] = set()  # 去重（一些 skill 在 local + cloud 都出现）

    for meta in LOCAL_SKILLS:
        if meta["name"] in seen:
            continue
        seen.add(meta["name"])
        base = SKILLS_ROOT / "local" / meta["name"]
        plans.append((base / "SKILL.md", base / "run.py", meta, "local"))
    for meta in DATA_SKILLS:
        if meta["name"] in seen:
            continue
        seen.add(meta["name"])
        base = SKILLS_ROOT / "data" / meta["name"]
        plans.append((base / "SKILL.md", base / "run.py", meta, "data"))
    for meta in CLOUD_SKILLS:
        if meta.get("_is_dup"):
            continue  # 已在 local/data 里
        if meta["name"] in seen:
            continue
        seen.add(meta["name"])
        base = SKILLS_ROOT / "cloud" / meta["name"]
        plans.append((base / "SKILL.md", base / "run.py", meta, "cloud"))

    for skill_md, run_py, meta, kind in plans:
        base = skill_md.parent
        if dry_run:
            print(f"[dry-run] would create: {base}")
            written += 1
            continue
        if not force:
            # 已被人手写成真实内容的 skill 一律跳过，绝不覆盖。
            marker = skill_md if skill_md.exists() else run_py
            if marker.exists():
                skipped += 1
                continue
        base.mkdir(parents=True, exist_ok=True)
        skill_md.write_text(_skill_md(meta, kind), encoding="utf-8")
        run_py.write_text(_run_py(meta), encoding="utf-8")
        written += 1
    return written, len(plans), skipped


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be created without touching the filesystem",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="覆盖已存在的 SKILL.md / run.py（默认跳过，保护手写内容）",
    )
    ns = parser.parse_args(argv)
    written, planned, skipped = scaffold(dry_run=ns.dry_run, force=ns.force)
    print(
        f"--- {written}/{planned} skill(s) processed"
        + (f"，跳过已存在 {skipped}（要覆盖请加 --force）" if skipped else "")
        + " ---"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
