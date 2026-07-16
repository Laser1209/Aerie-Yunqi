# Aerie · 云栖 R3 收尾 + 用户新增需求 续做计划

> 锚定：[plan-r0-r3-resume-and-complete-2026-07-17.md](file:///e:/Agent_reply/.trae/documents/plan-r0-r3-resume-and-complete-2026-07-17.md)（R0–R2 已 100% 完成）
> 用户新需求：日报弹窗 / 24h 欲望 / 70+ skills / 多 AI 选项 / 行为集中化
> 用户确认范围 = 17 skills（12 local + 5 data），70+ 留作后续批次

---

## 〇、Phase 1 探索结论（实际状态盘点）

| 段 | 任务 | 状态 | 证据 / 待做点 |
| --- | --- | --- | --- |
| R0 | 行为集中化 `persona_behavior.yaml` | ✅ 完成 | [persona_behavior.yaml](file:///e:/Agent_reply/config/persona_behavior.yaml) 5 段全；[companion.py:46-71](file:///e:/Agent_reply/core/companion.py#L46-L71) 注入 |
| R1.1 | `brief_fetcher.py` 5 源 | ✅ 完成 | [brief_fetcher.py](file:///e:/Agent_reply/core/brief_fetcher.py) RSS 白名单 + 15s 超时 |
| R1.2 | `brain.compose_brief` | ✅ 完成 | [brain.py:248-304](file:///e:/Agent_reply/core/brain.py#L248-L304) |
| R1.3 | 日报弹窗 `daily-brief.{html,css,js}` | ✅ 完成 | renderer/ 目录下三件套 |
| R1.4 | `api_server` 3 端点 | ✅ 完成 | [api_server.py:1171-1241](file:///e:/Agent_reply/core/api_server.py#L1171-L1241) |
| R1.5 | boot 8s + `morning_brief_9am` cron + `custom_dispatcher=brief` | ✅ 完成 | [companion.py:148-241](file:///e:/Agent_reply/core/companion.py#L148-L241) + [proactive.yaml:28-32](file:///e:/Agent_reply/config/proactive.yaml#L28-L32) + [push_scheduler.py:176-227](file:///e:/Agent_reply/core/push_scheduler.py#L176-L227) |
| R1.6 | 托盘「打开简报」+ iframe | ✅ 完成 | [main.js:222-236](file:///e:/Agent_reply/electron/src/main.js#L222-L236) + [preload.js:52-54](file:///e:/Agent_reply/electron/src/preload.js#L52-L54) + [app.js:149-170](file:///e:/Agent_reply/electron/src/renderer/js/app.js#L149-L170) |
| R2.1 | `desire_engine.py` 5 变量 + 5min tick | ✅ 完成 | [desire_engine.py](file:///e:/Agent_reply/core/desire_engine.py) 完整 |
| R2.2 | companion 集成 + 3 端点 + proactive idle_care/voice_miss | ✅ 完成 | [api_server.py:1244-1279](file:///e:/Agent_reply/core/api_server.py#L1244-L1279) + [proactive.yaml:37-49](file:///e:/Agent_reply/config/proactive.yaml#L37-L49) |
| R3.1 | `skill_loader.py` + `skill_router.py` + companion 集成 | ✅ 完成 | [skill_loader.py](file:///e:/Agent_reply/core/skill_loader.py) + [skill_router.py](file:///e:/Agent_reply/core/skill_router.py) + [companion.py:158-168](file:///e:/Agent_reply/core/companion.py#L158-L168) |
| R3.2 | `tool_registry.provider_hint` 字段 | ❌ **缺** | [tool_registry.py:12-44](file:///e:/Agent_reply/core/tool_registry.py#L12-L44) 仍用 `tuple[ToolFn, dict]`；`register()` 不接受 `provider_hint=`，**与 skill_loader 调用不兼容** |
| R3.3 | 17 个 skill 骨架（SKILL.md + run.py） | ❌ **缺** | `e:\Agent_reply\skills\` 目录根本不存在 |
| R3.4 | api 3 端点 `/api/skills/{list,get,call}` | ✅ 完成 | [api_server.py:1284-1356](file:///e:/Agent_reply/core/api_server.py#L1284-L1356) |
| R3.5 | `brain.py` 多 provider 入口 | ❌ **缺** | [brain.py:44-79](file:///e:/Agent_reply/core/brain.py#L44-L79) 只有文本 LLM；缺 image_sdxl / voice_tts / vision_llava / shell_safe 入口 |
| R3.6 | 复跑 6 脚本 + R3.7 安全审查 | ❌ **缺** | 未跑 |

**唯一卡点** = R3.2 / R3.3 / R3.5 三个文件级改造。

---

## 一、本次执行清单（按依赖顺序）

### R3.2 · `core/tool_registry.py` 加 `provider_hint` 字段（0.3h）

> 根因：`skill_loader.py:122-143` 调用 `self.registry.register(..., provider_hint=meta["hint"])`，但当前 `register(name, func, schema)` 不接受 `provider_hint` — 启动时 17 个 skill 全部会报 `TypeError: register() got an unexpected keyword argument 'provider_hint'`，静默被 `except Exception` 吞掉。

- [ ] **R3.2.1** `core/tool_registry.py` 重构为 dict 存储（保留向后兼容）
  ```python
  def __init__(self, db=None):
      self._tools: dict[str, dict] = {}  # name -> {func, schema, provider_hint}
      self.db = db

  def register(self, name, func, schema, provider_hint="text"):
      self._tools[name] = {
          "func": func,
          "schema": schema or {},
          "provider_hint": str(provider_hint or "text"),
      }

  def get(self, name) -> dict | None:
      return self._tools.get(name)

  def get_openai_schema(self) -> list[dict]:
      out = []
      for name, t in self._tools.items():
          s = deepcopy(t["schema"])
          fn = s.get("function", {})
          desc = fn.get("description", "") or ""
          fn["description"] = f"{desc} [provider={t['provider_hint']}]"
          s["function"] = fn
          out.append(s)
      return out

  async def execute(self, name, args):
      if name not in self._tools:
          return {"error": f"unknown tool: {name}"}
      func = self._tools[name]["func"]
      try:
          result = func(**(args or {}))
          if asyncio.iscoroutine(result):
              result = await result
          return result
      except Exception as e:
          return {"error": str(e)}
  ```
- [ ] **R3.2.2** 不删旧接口签名，**追加** `provider_hint` 参数（带默认 `"text"`）保证 `register_all_tools()` 既有调用不破
- [ ] **R3.2.3** 验证：跑 `verify_self_evolve.py` + `e2e_self_evolve.py` — 现有 3 个内置 tool (`long_term_memory` / `web_search` / `image_search`) 不破

### R3.3 · 17 个 skill 骨架（2.0h）

> 设计：12 本地 + 5 数据只读，每个 = `SKILL.md`（frontmatter）+ `run.py`（async run(args) → dict）
> 原则：所有 run.py 调不通时返回 `{"status": "stub", "error": "dependency_missing"}`，不崩主程序

#### A. 本地 12 个（`skills/local/{name}/`）

| 序 | name | description | provider_hint | read_only | run.py 行为 |
| --- | --- | --- | --- | --- | --- |
| 1 | `tts` | 文字转语音 / Text to speech | `tts-openvino` | false | 调 `local_tts.synthesize(text)` → wav 路径；无依赖返 stub |
| 2 | `asr` | 语音识别 / Speech recognition | `asr-whisper` | true | 调 `local_asr.transcribe(audio_path)` → text；无依赖返 stub |
| 3 | `ocr` | 图像文字识别 / OCR | `ocr-pp` | true | 调 `local_ocr_npu.recognize(img_path)` → text；无依赖返 stub |
| 4 | `img2img` | 图像编辑 / Image-to-image | `image-sdxl` | false | 调 `local_img2img.transform(prompt, src)` → out 路径；无依赖返 stub |
| 5 | `txt2img` | 文生图 / Text-to-image | `image-sdxl` | false | 调 `local_txt2img.generate(prompt)` → out 路径；无依赖返 stub |
| 6 | `screenshot-qa` | 截图问答 / Screenshot Q&A | `vision-llava` | true | 调 `local_screenshot_qa.ask(img_path, q)` → 答案；无依赖返 stub |
| 7 | `mineru` | PDF/文档解析 / Document parse | `text` | true | 调 `local_mineru.parse(pdf_path)` → markdown；无依赖返 stub |
| 8 | `realtime-translator` | 实时翻译 / Realtime translate | `text` | true | 调 `local_realtime_translator.run(src, tgt)` → 启动后台流；无依赖返 stub |
| 9 | `vram` | 显存调整 / GPU VRAM limit | `shell-safe` | false | 调 `local_vram.set_limit(pct)` → ok；无依赖返 stub |
| 10 | `computer-use` | 系统状态查询 / System query | `shell-safe` | true | 调 `local_computer_use.query(category, key)` → value；无依赖返 stub |
| 11 | `markitdown` | Office→MD / Office to MD | `text` | true | 调 `markitdown.convert(file_path)` → markdown 字符串；无依赖返 stub |
| 12 | `git-commit` | 提交信息生成 / Commit msg gen | `text` | true | 调 `git_commit.generate(diff_text)` → commit msg；无依赖返 stub |

#### B. 数据只读 5 个（`skills/data/{name}/`）

| 序 | name | description | provider_hint | read_only | run.py 行为 |
| --- | --- | --- | --- | --- | --- |
| 1 | `notion-cli` | Notion CLI | `text` | true | 子进程 `notion-cli <subcmd>` → stdout；无 CLI 返 stub |
| 2 | `figma` | Figma MCP | `text` | true | MCP client stub；无 token 返 stub |
| 3 | `obsidian-cli` | Obsidian vault | `text` | true | 子进程 `obs <subcmd>` → stdout；无 CLI 返 stub |
| 4 | `obsidian-bases` | Obsidian Bases | `text` | true | 读 .base YAML → 返回结构 |
| 5 | `spec-to-impl` | Spec→tasks 拆解 | `text` | true | LLM 调 spec → 任务列表 stub |

#### C. 目录结构 + 文件模板

```
skills/
├── local/
│   ├── tts/
│   │   ├── SKILL.md
│   │   └── run.py
│   ├── asr/... (12 个)
├── data/
│   ├── notion-cli/... (5 个)
```

**SKILL.md frontmatter 模板**（每个 skill 一份）：
```yaml
---
name: tts
description: 文字转语音 / Text to speech
provider_hint: tts-openvino
read_only: false
---

# TTS / 文字转语音

调本地 OpenVINO Qwen3-TTS 把文字转成 wav 文件，输出路径在 wav_path 字段。
依赖缺失时返回 {"status": "stub", "error": "..."} 不崩主程序。
```

**run.py 模板**（每个 skill 一份）：
```python
"""tts skill — invokes local OpenVINO Qwen3-TTS."""
import logging
logger = logging.getLogger(__name__)

def run(args: dict) -> dict:
    text = (args or {}).get("text", "")
    if not text:
        return {"error": "missing text"}
    try:
        from local_tts import synthesize
        wav_path = synthesize(text)
        return {"status": "ok", "wav_path": str(wav_path), "provider": "voice_tts"}
    except ImportError:
        return {"status": "stub", "error": "local_tts module missing", "text": text[:50]}
    except Exception as e:
        return {"status": "error", "error": str(e)}
```

- [ ] **R3.3.1** 一次性创建 17 个目录（用 PowerShell `New-Item -ItemType Directory` 或 Python 脚本）
- [ ] **R3.3.2** 写脚本 `tools/scaffold_skills.py` 自动生成 17 份 `SKILL.md` + `run.py`（不在 plan 写代码，只放伪代码；执行时跑脚本）
- [ ] **R3.3.3** 跑 `python tools/scaffold_skills.py` 生成 17 个骨架
- [ ] **R3.3.4** 验证：重启后端 → 调 `/api/skills/list` 看到 `count: 17`

### R3.5 · `core/brain.py` 多 provider 入口（0.5h）

> 现状：brain.py 只有 `chat()` / `generate_push()` 走 LLM；缺 image_sdxl / voice_tts / vision_llava / shell_safe 4 个 provider 的统一入口

- [ ] **R3.5.1** 加 `_load_ai_options()` 读 `persona_behavior.yaml → ai_options`
  ```python
  def _load_ai_options(self) -> list[dict]:
      try:
          from config.persona_loader import load_behavior_config
          cfg = load_behavior_config()
          return cfg.get("ai_options", []) or []
      except Exception:
          return []
  ```
- [ ] **R3.5.2** 加 `get_ai_options()` 公开方法
- [ ] **R3.5.3** 加 4 个 provider 入口（全部 stub + 路由占位）：
  - `generate_image(prompt: str) -> dict`：返 `{"status": "stub", "provider": "image_sdxl", "model": "sdxl"}`
  - `speak_text(text: str) -> dict`：返 `{"status": "stub", "provider": "voice_tts", "model": "qwen3-tts", "text": text[:30]}`
  - `see_image(img_path: str, question: str) -> dict`：返 `{"status": "stub", "provider": "vision_llava"}`
  - `safe_shell(command: str, args: list) -> dict`：白名单检查（`dir` / `echo` / `type` / `where` / `python --version` 5 个）→ 通过返 `{"status": "ok", "stdout": "..."}`；否则 `{"error": "command_not_whitelisted"}`
- [ ] **R3.5.4** 不删 `chat()` / `generate_push()` 现有签名；`safe_shell` 走白名单确保 R3 后续不破主程序

### R3.6 · 复跑 6 脚本（0.2h）

- [ ] 跑：
  ```bash
  cd e:\Agent_reply
  python -X utf8 verify_pacing_persistence.py
  python -X utf8 verify_zero_regression.py
  python -X utf8 verify_emotion_history.py
  python -X utf8 verify_self_evolve.py
  python -X utf8 e2e_pacing.py
  python -X utf8 e2e_self_evolve.py
  ```
- [ ] 预期：229/229 全过（**特别关注 verify_self_evolve.py 调 `tool_registry.register()` 的路径必须用新签名**）
- [ ] 任何红 → 立即修；不堆到最后

### R3.7 · TRAE-security-review + 三原则（0.3h）

- [ ] **R3.7.1** TRAE-security-review 表格（追加到本计划文件附录 A）：
  | 类别 | 触及点 | 处理 |
  | --- | --- | --- |
  | path_traversal | `skills/{local,data}/<name>/run.py` | `_ALLOWED_BASES = (_LOCAL_SKILLS_DIR.resolve(), _DATA_SKILLS_DIR.resolve())` + `rp.resolve()` 前缀检查（已实现于 [skill_loader.py:32-32](file:///e:/Agent_reply/core/skill_loader.py#L32-L32)） |
  | unsafe_deserialization | `SKILL.md` frontmatter | `yaml.safe_load`（禁 `yaml.load` / `pickle`） |
  | prompt_injection | skill 描述进入 LLM | 描述末尾 `[provider=...]` 元数据不进入 LLM prompt（仅 OpenAI schema 字段） |
  | ssrf / shell exec | skill `subprocess.run` | `shell=False` + list args + 30s timeout + 白名单（`safe_shell` 入口） |
  | xss | daily-brief.html | iframe 同源 file://；textContent 渲染，不注入 HTML |
  | 频繁触发 | desire 5min tick | `tick_seconds >= 30` 下限；`_loop` 异常不破主循环 |
  | 主动推送 | desire `idle_care` | `cooldown_hours=12` 防止被拒后狂推 |
  | 配置注入 | behavior_cfg 集中 | `yaml.safe_load` + `_DEFAULT_BEHAVIOR_CONFIG` fallback |
  | 沙箱 | skill `run.py` 动态加载 | `importlib.util.spec_from_file_location` 隔离模块命名空间；`sys.modules` 注入限定命名 |
- [ ] **R3.7.2** 三原则自检：
  1. 零回归：6 脚本 229/229 全过；R0–R2 已实现模块（emotion / brief / desire）API 签名不变
  2. 伊塔人格：skill 名称中英双语（"name: tts" / "description: 文字转语音 / Text to speech"）；禁词列表不变（"主人/您" → "你"）
  3. 设计美学：5 主题色走 CSS var()；不引 emoji；用 SVG；iframe 同源 file://
- [ ] **R3.7.3** 写 `.trae/documents/phase-r3-finalize-self-review.md` 汇总

---

## 二、用户新增需求映射（vs 上轮已确认）

| 用户原话 | 已落点 | 本轮是否动 |
| --- | --- | --- |
| 「启动后弹出日报，方框单独弹出，HTML，内置显示器」 | R1.5 boot hook + R1.6 托盘菜单 + iframe | 不动 |
| 「日志含 AI/IT/国际/国家/天气 + 反馈调次日」 | R1.1 5 源 + `save_feedback` | 不动 |
| 「不能设主动发消息，轮询让伊塔想发才发」 | R2.1 5min tick + 5 变量 | 不动 |
| 「70+ skills 全部封装让 AI 调用」 | 用户确认 = **17 个（12+5）**，70+ 留后续 | **R3.3 落 17 骨架** |
| 「按 skill 特性对接模型（图像/多模态/生成）」 | R3.1 PROVIDER_HINTS + R3.2 tool_registry provider_hint | **R3.2 落实** |
| 「AI 选项要多」 | `persona_behavior.yaml → ai_options` 5 个 | **R3.5 brain 多 provider 入口** |
| 「行为/情绪/思维集中化」 | R0 集中化 | 不动 |
| 「行为思维集中化的文件控制」 | R0 + 行为集中化 | 不动 |

**70+ 后续批次规划**（不在本次范围）：
- 内容创作 12：algorithmic-art / canvas-design / frontend-design / frontend-skill / gsap / hyperframes(-media,-registry) / shadcn / slides / theme-factory / vercel-{composition,react,react-native} / writing-plans
- 文档报告 8：chart-visualization / consulting-analysis / dashboard-page / data-analysis / doc-coauthoring / doc-page / ppt-page / report-page
- 云服务 / 平台 20：天眼一下 / alipay-payment / douyinpay-payment / byted-{bp-cdn-pagesdeploy,mediakit-shared,seedance-video,seedream-image} / iga-pages / figma / notion-{cli,research,knowledge,meeting,spec} / obsidian-{markdown,cli,bases} / redis-development / mcp-builder / gh-cli / electron / screenshot / defuddle / shadcn / brainstorming / test-driven-development / executing-plans / hook-analyzer / report-generator / security-best-practices / local-* (12 个本地已落)
- 平台部署 3：byted-bp-cdn-pagesdeploy / iga-pages / gh-cli

---

## 三、依赖确认

- [x] `feedparser>=6.0.10`（R1 必装）— 已装
- [x] `markitdown[all]>=0.0.1`（Block-3 已装）— 已装
- [x] `pyyaml>=6.0`（R3 SKILL.md frontmatter）— 默认已装
- [ ] 17 skill 各自依赖（whisper / sdxl / llava / openvino / mineru / wmi / markitdown）按需装 .venv；本次**全走 stub 兜底**

---

## 四、验收标准

- [ ] 6 脚本 229/229 全过
- [ ] 三原则自检：零回归 / 伊塔人格 / 设计美学
- [ ] TRAE-security-review 表格所有类别过完
- [ ] 冒烟测试：
  - `curl http://127.0.0.1:7890/api/skills/list` → `count: 17`
  - `curl http://127.0.0.1:7890/api/skills/tts` → SKILL.md 原文
  - `curl -X POST http://127.0.0.1:7890/api/skills/tts/call -d '{"args":{"text":"hi"}}' -H "Content-Type: application/json"` → `{"status": "stub", ...}` 或真 wav
  - `curl http://127.0.0.1:7890/api/brief/today` → 5 段 + markdown
  - `curl http://127.0.0.1:7890/api/desire/state` → score + 5 变量

---

## 五、执行顺序与时间盒

```
R3.2 tool_registry provider_hint   0.3h
R3.3 17 skill 骨架                 2.0h
R3.5 brain 多 provider             0.5h
R3.6 复跑 6 脚本                   0.2h
R3.7 安全审查 + 三原则             0.3h
──────────────────────────────────
合计                              3.3h
```

---

## 六、风险与回退

| 风险 | 兜底 |
| --- | --- |
| R3.2 改 tool_registry.register 签名 → 破坏 3 个内置 tool | 保留旧签名 + 追加 `provider_hint="text"` 默认值 |
| R3.3 skill 骨架依赖缺失导致 ImportError | run.py 全用 `try/except ImportError → {"status": "stub"}` |
| R3.5 brain 加 4 个 provider 入口影响现有 `chat()` | 全是**新方法**，不删不重命名 |
| 任何脚本红 | 立即回到上一段 R2 状态（git 已提交） |

---

## 七、完成后通知用户

R3 全部完成 + 6 脚本 229/229 + 三原则 + TRAE-security-review 全过 + 17 skill 骨架已落 + 70+ skills 留作后续批次。
