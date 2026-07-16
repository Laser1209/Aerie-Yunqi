# Phase 9 续批 · E2E 验收清单

> [!info] 文档定位
> 本清单用于 Phase 9 续批（B4-B7 + E2E 阶段）落地后的全链路验收。
> 全部 18 项可由 4 套 `verify_*.py` + 2 套 `e2e_*.py` 覆盖；任一项未勾选即视为未验收。
> 验收人：Aerie · 云栖 主理人 / 落地执行人自动审。
>
> 版本 v1.0 · 2026-07-17

---

## 一、表与 schema（4 项）

- [ ] **1.1 9 张老表齐全**：`messages / conversations / users / cognition_log / tool_calls / tool_results / decisions / emotion_state / recall_log` 在 `data/aerie.db` 中存在且 schema 与 Phase 1-8 一致。
  - 如何验证：`python -X utf8 verify_zero_regression.py` 末段"9 张老表存在性"全过。
- [ ] **1.2 4 张新表齐全**：`pacing_decisions / emotion_state_store / self_evolve_log / tool_registry` 已建索引。
  - 如何验证：`verify_zero_regression.py` 末段"4 张新表 + 3 索引"全过。
- [ ] **1.3 PRAGMA integrity_check 通过**：DB 文件未损坏。
  - 如何验证：`python -c "import sqlite3; print(sqlite3.connect('data/aerie.db').execute('PRAGMA integrity_check').fetchone())"` 输出 `('ok',)`。
- [ ] **1.4 pacing_decisions 落库结构正确**：每条记录含 `cognition_id / seg_idx / style / interval_sec / emotion_label` 字段。
  - 如何验证：`verify_pacing_persistence.py` 27/27 全过；`DESCRIBE pacing_decisions` 输出含上述字段。

---

## 二、API 健康（3 项）

- [ ] **2.1 `/api/health` 返回 200 + `status="ok"`**：后端启动完毕。
  - 如何验证：`curl http://127.0.0.1:7890/api/health` 或 `verify_self_evolve.py` 阶段 1。
- [ ] **2.2 `/api/cognition/recent` 与 `/api/cognition/stats` 返回非 500**：B6 cognition 中心接口可用。
  - 如何验证：`curl http://127.0.0.1:7890/api/cognition/recent?limit=5` 返回 list；`/api/cognition/stats` 返回 dict。
- [ ] **2.3 `/api/emotion/history` 与 `/api/emotion/state` 可读**：B5 情绪历史曲线 + 当前状态。
  - 如何验证：`verify_emotion_history.py` 阶段 2（曲线数据非空 + 状态字段齐全）。

---

## 三、UI 渲染（4 项）

- [ ] **3.1 聊天面板可发可收**：发消息后 3s 内在 Electron 窗口看到气泡。
  - 如何验证：启动 `npm start` → 主面板 chat tab → 输入文字 → 点发送 → 气泡出现。
- [ ] **3.2 5 主题切换生效**：`yita-pink / midnight-purple / sakura-white / ocean-blue / forest-green` 实时切换。
  - 如何验证：settings → 主题下拉 → 5 个值各切一次，背景色明显变化且文字仍可读。
- [ ] **3.3 大脑中枢 tab 可见且能流式接收事件**：SSE → IPC 桥接工作。
  - 如何验证：切到「大脑中枢 / Brain Center」tab → 触发一次消息发送 → 看到 `cognition.received` / `decision.made` / `emotion.transition` 事件。
- [ ] **3.4 自进化卡片可见（pending 状态）**：`verify_self_evolve.py` 写入的测试行能渲染到卡片。
  - 如何验证：跑 `verify_self_evolve.py` → 切到「自进化 / Self-Evolve」tab → 看到 1 张 pending 卡片（测试结束后已清理）。

---

## 四、pacing 落库（2 项）

- [ ] **4.1 5 段喷发决策数组非空**：连续对话中每段均产生 1 行 `pacing_decisions`。
  - 如何验证：`verify_pacing_persistence.py` 阶段 1（>=5 行）。
- [ ] **4.2 首段 `interval_sec=0.0` 且 `style='immediate'`**：决策树首要判定正确。
  - 如何验证：`e2e_pacing.py` 6 个 SCENARIOS 第一行均 `interval=0.0 [immediate]`。

---

## 五、自进化闭环（3 项）

- [ ] **5.1 能力缺口可生成提案**：`maybe_propose()` 在 `react_trace.thought` 含"无法"时返回非 0 row_id。
  - 如何验证：`e2e_self_evolve.py` 阶段 3。
- [ ] **5.2 沙箱试运行返回 `ok=true` + `safety_check` 字段**：提案经过 `SandboxRunner.preview` 不破。
  - 如何验证：`e2e_self_evolve.py` 阶段 6。
- [ ] **5.3 批准后工具真注册**：`approve(row_id)` 后 `tool_registry` 多 1 个 tool_name，`user_decision='approved'`。
  - 如何验证：`e2e_self_evolve.py` 阶段 7（同时阶段 8 验证幂等）。

---

## 六、文档与规范（2 项）

- [ ] **6.1 persona 文案无禁词**：config/persona.yaml + UI 文案不出现"主人 / 您"（"您能/请问"）。
  - 如何验证：
    ```bash
    grep -nE "主人|您" config/persona.yaml || echo "OK no forbidden word"
    ```
    期望 `OK no forbidden word`。
- [ ] **6.2 代码层纯英文**：核心 Python/JS 文件变量/函数/日志/SQL 字段名为英文（注释可中英混）。
  - 如何验证：抽查 `core/persona_pacing.py` / `electron/src/main.js` → 函数/常量名为英文；UI 文案（中英双语）走 `index.html` 的 `aria-label`/`<span class="i18n-en">` 双语标记。

---

## 七、验收签字

- [ ] **18/18 全部勾选 → 验收通过**。

> [!warning] 不通过处理
> 任何一项未勾选 → 回滚对应子项 → 自我怀疑 review → 再跑 6 脚本。
> 三原则铁律（不破坏现有功能 / 不破坏伊塔人格 / 设计美学统一）必须每次自检。

---

> 维护：Aerie · 云栖 落地组
> 最后更新：2026-07-17（基于 verify_pacing_persistence 27/27 + e2e_pacing 96/96 + e2e_self_evolve 10 段全过）
