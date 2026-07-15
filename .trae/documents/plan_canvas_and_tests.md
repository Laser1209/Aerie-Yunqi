# Aerie · 云栖 v9.0 — 系统架构海报 + 单元测试补全计划

> **生成时间**: 2026-07-16
> **输入文件**: checklist.md / spec.md / tasks.md
> **范围**: canvas-design 架构海报 + Python 后端单元测试补全

---

## 1. 当前状态总结

### 1.1 已完成 (v9.0.0 + DLC Phase A + Provider 补全)

| 层级 | 状态 |
| --- | --- |
| Python 后端核心 (companion/brain/pipeline) | ✅ 已完成 |
| LLM Provider ×7 (qwen/deepseek/minimax/bigmodel/siliconflow/gemini/openai_proxy) | ✅ 已完成 |
| 情感引擎 (PAD + 4 槽累积阈值 + 5 态状态机) | ✅ 已完成 |
| 消息通信层 (+ MarkDown/Poke/声聊 DLC) | ✅ 已完成 |
| 主动推送系统 (9 场景 + Cron + 频控) | ✅ 已完成 |
| 工具系统 (16 工具) | ✅ 已完成 |
| Electron 前端 + 打包 (176MB exe) | ✅ 已完成 |
| 安全审查 (70 文件，无高危漏洞) | ✅ 已完成 |
| 文档 (Ita.md v3.1 / Roadmap v2.0 / Plan v9_next) | ✅ 已完成 |

### 1.2 缺口

| 项 | 说明 |
| --- | --- |
| **单元测试** | `tests/` 目录不存在，所有模块的单元测试脚本缺失 |
| **系统架构海报** | 无品牌/架构视觉物料 |
| **Electron UI 交互测试** | 需在桌面环境手动验证（用户将配合进行） |

---

## 2. 实施计划

### Part A: Canvas-Design — 系统架构海报

#### A.1 设计哲学 (design philosophy .md)

**运动名称**: "Frozen Blueprint" (冻结蓝图)

灵感来源：伊塔的冰蓝瞳孔 + 闷骚人格的双层结构（表面冷静/内里滚烫）+ 系统架构的模块化严密性。

**哲学核心**:
- 色域：冰蓝色轴（#88B5D8 → #1A3A4C）为主色谱，暗红（#8B2252）为唯一强调色
- 形式：几何分割，模块化区块，细线连接
- 排版：极简临床字体，稀疏标注
- 氛围：技术架构图的美学化——用建筑蓝图的视觉语言承载软件架构的信息密度

#### A.2 画布产出 (canvas .png)

- 尺寸：A2 横向 (1684×1190px, 300dpi)
- 内容：Aerie 系统架构全览（Python 后端 + Electron 前端 + NapCat + LLM 层）
- 元素：8 大功能模块卡片 + 数据流箭头 + 连接线 + 标题/版本标注
- 色板：冰蓝主色 + 暗红强调 + 深灰底

#### A.3 产出文件
- `e:\Agent_reply\documents\aerie_architecture_poster_philosophy.md` — 设计哲学
- `e:\Agent_reply\documents\aerie_architecture_poster.png` — 海报 PNG

---

### Part B: 单元测试补全

#### B.1 新建 tests/ 目录 + 测试配置

- `tests/__init__.py`
- `tests/conftest.py` — pytest fixtures (Database, EmotionEngine, etc.)

#### B.2 情感引擎测试 `tests/test_emotion.py`

测试文件覆盖:
- **`core/emotion_engine.py`** — `EmotionEngine`：
  - `trigger(event_type, intensity)` → PAD 增量正确
  - `get_label()` → 五类分类正确（joy/sad/anger/fear/neutral）
  - 连续事件累积效果
  - 衰减逻辑

- **`core/emotion_threshold.py`** — `CumulativeEmotionEngine`：
  - 4 槽位初始化正确（patience/anxiety/desire/tenderness）
  - `add(slot, value)` → 数值累加
  - `daily_decay()` → 衰减正确
  - 阈值突破 → 触发爆发
  - `_erupt()` → 阈值永久降低（角色磨损）

#### B.3 通信层测试 `tests/test_communication.py`

- **`communication/recall_manager.py`** — `RecallManager`：
  - `handle_user_negative()` → 2 分钟内触发撤回
  - 2 分钟外 → 不触发
  - 否定关键词匹配正确
  - `maybe_poke_on_silence()` → 5 分钟无回应触发 poke

- **`communication/router.py`** — `Router`：
  - 主账号 → FULL
  - 朋友 → AUTO
  - 陌生人 → BASIC

- **`communication/splitter.py`** — `SemanticMessageSplitter`：
  - 长文本 → 多段
  - 短文本 → 单段
  - 句末补全

#### B.4 消息处理测试 `tests/test_pipeline.py`

- **`core/pipeline.py`** — `Pipeline`：
  - `_color_reply()` → MarkDown 自动检测
  - `_handle_full()` → 5 阶段流程

#### B.5 工具系统测试 `tests/test_tools.py`

- **`tools/__init__.py`** — 工具注册：
  - 16 工具全部注册
  - `registry.get(name)` 返回正确函数
  - Function Calling schema 格式正确

---

### Part C: 验证清单

- [ ] 设计哲学 .md 文件完成
- [ ] 架构海报 .png 生成
- [ ] `pytest tests/` 所有测试通过
- [ ] 测试覆盖: emotion_engine / emotion_threshold / recall / router / splitter / pipeline / tools

---

## 3. 实施注意事项

- 单元测试使用 `pytest` + `pytest-asyncio`，如未安装需 `pip install pytest pytest-asyncio`
- `EmotionEngine` 和 `CumulativeEmotionEngine` 在 companion 启动时被创建，测试中需要独立实例化
- `RecallManager` 依赖 `QQClient` 实例，测试需 mock
- canvas-design 使用 `reportlab` 生成 PDF 或 `Pillow` 生成 PNG，确保依赖已安装
- 架构海报参考现有代码结构（core/communication/proactive/emotion/voice/electron 等 8 大模块）
