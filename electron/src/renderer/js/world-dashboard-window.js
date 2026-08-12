"use strict";

// aerie.world 独立仪表盘窗口渲染逻辑（10 页，B3.2 + P4 统计）。
// 仅通过专用 preload（window.world）获取数据，绝不触碰通用 API。

(function () {
  const els = {};
  const POLL_MS = 3000;
  let pollTimer = null;
  let visible = true;
  let lastState = null;
  let b3 = { internal: {}, trends: [], cognition: [], permissions: {}, decisionLog: [] };
  let eventFilter = "all";

  // 与主程序主题一致的品牌色（与 CSS --wdw-pad-* 对应）
  const PAD_COLORS = { P: "#007aff", A: "#5e5ce6", D: "#34c759" };
  const NEURO_COLORS = { vitality: "#007aff", calm: "#34c759", strain: "#ff3b30" };
  const REL_COLORS = { attachment: "#007aff", trust: "#34c759", security: "#5e5ce6", conflict: "#ff3b30" };
  // 区域 id → 中文名（房间级定位：楼层竖条上的区域展示）
  const ZONE_LABELS = {
    living: "客厅", studio: "工作室", master_bedroom: "主卧", dining: "餐厅",
    kitchen: "厨房", entrance: "玄关", balcony: "阳台", guest_bath: "客卫",
    stair: "楼梯", corridor: "走廊", bridge: "连廊", closet: "衣帽间", master_bath: "主卫",
  };
  // zone → 平面图 SVG（viewBox 1400×980）上的百分比坐标（光球锚点）。
  // 依据设计图 floor_plan_level*.svg 各区域文本/边界换算：
  //   level1: 玄关(226,323) 厨房(486,294) 客卫(802,244) 餐厅(514,460) 客厅(536,640) 阳台(954,798) 楼梯(183,510)
  //   level2: 走廊(183,438) 工作室(486,352) 主卫(802,244) 桥廊(442,474) 衣帽间(752,582) 主卧(802,755)
  const ZONE_POS = {
    level1: {
      entrance: { x: 16.2, y: 33.0 },
      kitchen: { x: 34.7, y: 30.0 },
      guest_bath: { x: 57.3, y: 24.9 },
      dining: { x: 36.7, y: 47.0 },
      living: { x: 38.3, y: 65.3 },
      balcony: { x: 68.1, y: 81.4 },
      stair: { x: 13.1, y: 52.0 },
    },
    level2: {
      corridor: { x: 13.1, y: 44.7 },
      studio: { x: 34.7, y: 35.9 },
      master_bath: { x: 57.3, y: 24.9 },
      bridge: { x: 31.6, y: 48.4 },
      closet: { x: 53.7, y: 59.4 },
      master_bedroom: { x: 57.3, y: 77.0 },
    },
  };
  // activity → 中文作息描述（世界预设表：sleeping/planning/dining/working/relaxing/idle）
  const ACTIVITY_LABELS = {
    sleeping: "在休息（睡觉）",
    planning: "在规划一天",
    dining: "在用餐",
    working: "在专注工作",
    relaxing: "在放松休息",
    idle: "空闲中",
  };
  // phase → 中文时段（世界阶段展示用）
  const PHASE_LABELS = {
    night: "深夜", morning: "清晨", noon: "正午", afternoon: "下午", evening: "傍晚",
  };

  function $(id) { return document.getElementById(id); }

  function init() {
    els.status = $("wdw-status");
    els.worldTime = $("wdw-world-time");
    els.location = $("wdw-location");
    els.activity = $("wdw-activity");
    els.energy = $("wdw-energy");
    els.phase = $("wdw-phase");
    els.weather = $("wdw-weather");
    els.generated = $("wdw-generated");
    els.scene = $("wdw-world-scene");
    els.floor = $("wdw-floor");
    els.locIndicator = $("wdw-loc-indicator");
    els.locPos = $("wdw-loc-pos");
    els.locCells = els.locIndicator ? els.locIndicator.querySelectorAll(".wdw-loc-floor-cell") : [];
    els.mapBox = $("wdw-map");
    els.mapImg = $("wdw-map-img");
    els.mapOrb = $("wdw-map-orb");
    els.mapZoneLabel = $("wdw-map-zone-label");
    els.mapPath = $("wdw-map-path");
    els.mapPathLine = $("wdw-map-path-line");
    els.mapPathDot = $("wdw-map-path-dot");
    els.emotionLabel = $("wdw-emotion-label");
    els.padVal = { P: $("wdw-pad-P-val"), A: $("wdw-pad-A-val"), D: $("wdw-pad-D-val") };
    els.padBar = { P: $("wdw-pad-P"), A: $("wdw-pad-A"), D: $("wdw-pad-D") };
    els.events = $("wdw-events");
    els.relationshipBars = $("wdw-relationship-bars");
    els.relationshipLabel = $("wdw-relationship-label");
    els.relationshipHistory = $("wdw-relationship-history");
    els.memoryGroups = $("wdw-memory-groups");
    els.consoleStatus = $("wdw-console-status");
    els.consoleMsg = $("wdw-console-msg");
    els.timeline = $("wdw-timeline");
    els.internal = $("wdw-internal");
    els.decision = $("wdw-decision");
    els.imageCandidates = $("wdw-image-candidates");
    els.settings = $("wdw-settings");
    els.statsKpis = $("wdw-stats-kpis");
    els.statsWindow = $("wdw-stats-window");
    els.statsEmpty = $("wdw-stats-empty");
    els.statsCharts = {
      tokens: $("wdw-chart-tokens"),
      topics: $("wdw-chart-topics"),
      decisions: $("wdw-chart-decisions"),
    };

    // 10 页导航
    document.querySelectorAll(".wdw-nav-btn").forEach((btn) => {
      btn.addEventListener("click", () => switchPage(btn.getAttribute("data-page")));
    });
    // 事件过滤
    document.querySelectorAll(".wdw-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        eventFilter = chip.getAttribute("data-cat") || "all";
        document.querySelectorAll(".wdw-chip").forEach((c) => c.classList.toggle("is-active", c === chip));
        renderEvents(lastState);
      });
    });
    $("wdw-events-refresh").addEventListener("click", () => { refresh(); });
    $("wdw-memory-refresh").addEventListener("click", () => { loadMemory(); });
    document.querySelectorAll("[data-action]").forEach((btn) => {
      btn.addEventListener("click", () => runControl(btn.getAttribute("data-action"), btn));
    });
    // 统计窗口切换时重拉数据
    if (els.statsWindow) {
      els.statsWindow.addEventListener("change", () => renderStats());
    }
    // 无外壳窗口控制
    $("wdw-min").addEventListener("click", () => { const b = api(); if (b && b.minimize) b.minimize(); });
    $("wdw-close").addEventListener("click", () => { const b = api(); if (b && b.close) b.close(); });
    // 窗口尺寸变化时重绘趋势图（若内在状态页可见），并同步调整统计页 ECharts。
    window.addEventListener("resize", () => {
      const panel = document.querySelector('[data-page-panel="internal"]');
      if (panel && !panel.hidden) requestAnimationFrame(() => drawTrends());
      resizeStatsCharts();
    });
    document.addEventListener("visibilitychange", () => {
      visible = !document.hidden;
      if (visible) { refresh(); loadB3(); } else { stopPolling(); }
    });
    refresh();
    loadMemory();
    loadB3();
    startPolling();
  }

  function switchPage(page) {
    document.querySelectorAll(".wdw-nav-btn").forEach((b) => {
      b.classList.toggle("is-active", b.getAttribute("data-page") === page);
    });
    document.querySelectorAll(".wdw-page").forEach((p) => {
      p.hidden = p.getAttribute("data-page-panel") !== page;
    });
    // 内在状态页变为可见后，等布局完成再绘制趋势图，保证 canvas 使用真实渲染宽度。
    if (page === "internal") requestAnimationFrame(() => drawTrends());
    if (page === "stats") requestAnimationFrame(() => renderStats());
  }

  function api() { return window.world || null; }

  async function refresh() {
    const bridge = api();
    if (!bridge || typeof bridge.getState !== "function") {
      renderUnavailable();
      return;
    }
    try {
      const state = await bridge.getState();
      lastState = state && typeof state === "object" ? state : {};
      render(state);
      renderTimeline(state);
      renderImageCandidates(state);
    } catch (_) {
      renderUnavailable();
    }
  }

  async function loadB3() {
    const bridge = api();
    if (!bridge || typeof bridge.getB3 !== "function") return;
    try {
      const data = await bridge.getB3();
      b3 = data && typeof data === "object" ? data : b3;
      b3.decisionLog = Array.isArray(data.decision_log) ? data.decision_log : b3.decisionLog;
    } catch (_) {}
    renderInternal();
    renderDecision();
    renderSettings();
    renderRelationshipHistory();
    drawTrends();
  }

  function render(state) {
    const status = String(state.status || "unknown");
    setStatus(status);
    setText(els.worldTime, formatWorldTime(state));

    const summary = obj(state.worldSummary);
    // 顶部"地点"优先展示房间级位置描述（如"二层·工作室"），城市作为辅助；
    // 无房间定位时回退到用户设置的城市 / 时段地点(home/study)。
    const posDesc = str(summary.positionDesc);
    const city = str(summary.city);
    const legacyLoc = str(summary.location);
    setText(els.location, posDesc
      ? (city ? posDesc + " · " + city : posDesc)
      : (city || legacyLoc || "--"));
    setText(els.floor, floorLabel(summary.floor));
    setText(els.activity, ACTIVITY_LABELS[str(summary.activity)] || str(summary.activity) || "--");
    setText(els.energy, formatEnergy(summary.energy));
    setText(els.phase, PHASE_LABELS[str(summary.phase)] || str(summary.phase) || "--");
    setText(els.generated, formatTs(summary.generatedAt));

    const phase = normPhase(str(summary.phase));
    const weather = normWeather(str(summary.weather) || str(summary.weather_mood));
    els.scene.setAttribute("data-phase", phase);
    els.scene.setAttribute("data-weather", weather);
    setText(els.weather, weatherLabel(weather));
    renderLocation(summary);

    const pad = (state.emotion && obj(state.emotion.pad)) || {};
    renderPad(pad);
    const label = (state.emotion && str(state.emotion.label)) || "neutral";
    els.emotionLabel.textContent = label;

    renderRelationship(state);
    renderEvents(state);
  }

  // ── 当前位置指示器 + 平面图光球（房间级定位） ───────────────
  // 依据 worldSummary.floor / zone / positionDesc 更新场景区右上角的光圈、
  // 位置描述、1F/2F 楼层竖条，以及在平面图底图上叠加呼吸光球；
  // 无 position_desc 时整块隐藏（绝不显示 undefined）。
  function renderLocation(summary) {
    const posDesc = str(summary.positionDesc);
    if (!posDesc) {
      if (els.locIndicator) els.locIndicator.hidden = true;
      if (els.mapBox) els.mapBox.hidden = true;
      if (els.scene) els.scene.classList.remove("has-loc");
      return;
    }
    if (els.locIndicator) {
      els.locIndicator.hidden = false;
      els.scene.classList.add("has-loc");
      setText(els.locPos, posDesc);
    }
    const floor = Number(summary.floor);
    const zoneId = str(summary.zone);
    const zoneLabel = ZONE_LABELS[zoneId] || zoneId;
    if (els.locCells) {
      els.locCells.forEach((cell) => {
        const active = Number(cell.getAttribute("data-floor")) === floor;
        cell.classList.toggle("is-active", active);
        const zoneEl = cell.querySelector(".wdw-loc-floor-zone");
        if (zoneEl) zoneEl.textContent = active ? zoneLabel : "";
      });
    }
    renderMap(floor, zoneId, zoneLabel);
    renderMovementPath(summary);
  }

  // P2: 米制坐标 → SVG 像素（viewBox 1400×980，与平面图同坐标系）。
  function toSvg(level, x, y) {
    return { x: 140 + Number(x) * 72, y: 150 + Number(y) * 72 };
  }

  function pathLength(pts) {
    let len = 0;
    for (let i = 1; i < pts.length; i++) {
      len += Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
    }
    return len;
  }

  function pointAtLength(pts, target) {
    let acc = 0;
    for (let i = 1; i < pts.length; i++) {
      const seg = Math.hypot(pts[i].x - pts[i - 1].x, pts[i].y - pts[i - 1].y);
      if (acc + seg >= target || i === pts.length - 1) {
        const t = seg === 0 ? 0 : Math.max(0, Math.min(1, (target - acc) / seg));
        return {
          x: pts[i - 1].x + (pts[i].x - pts[i - 1].x) * t,
          y: pts[i - 1].y + (pts[i].y - pts[i - 1].y) * t,
        };
      }
      acc += seg;
    }
    return pts[pts.length - 1];
  }

  // P2: 移动中 → 渲染避障路径折线 + 蓝点沿路径按 progress 插值；
  // 未移动/无数据 → 隐藏 overlay（不影响原有光球锚点逻辑）。
  function renderMovementPath(summary) {
    if (!els.mapPath || !els.mapPathLine || !els.mapPathDot) return;
    const mv = obj(summary.movement);
    const waypoints = Array.isArray(mv.waypoints) ? mv.waypoints : [];
    if (mv.status !== "moving" || waypoints.length < 2) {
      els.mapPath.hidden = true;
      return;
    }
    els.mapPath.hidden = false;
    const pts = waypoints.map((w) => toSvg(Number(w.level) || 1, Number(w.x) || 0, Number(w.y) || 0));
    const d = "M" + pts.map((p) => p.x.toFixed(1) + " " + p.y.toFixed(1)).join(" L");
    els.mapPathLine.setAttribute("d", d);
    const total = pathLength(pts);
    const progress = Math.max(0, Math.min(1, Number(mv.progress) || 0));
    const pos = pointAtLength(pts, total * progress);
    if (pos) {
      els.mapPathDot.setAttribute("cx", pos.x.toFixed(1));
      els.mapPathDot.setAttribute("cy", pos.y.toFixed(1));
    }
  }

  // 平面图底图 + 光球：切换当前楼层 SVG，把光球锚定到 zone 百分比坐标。
  function renderMap(floor, zoneId, zoneLabel) {
    if (!els.mapBox || !els.mapImg || !els.mapOrb) return;
    const layer = floor === 2 ? "level2" : "level1";
    const anchor = (ZONE_POS[layer] && ZONE_POS[layer][zoneId]) || null;
    if (!anchor) {
      els.mapBox.hidden = true;
      return;
    }
    els.mapBox.hidden = false;
    const imgSrc = layer === "level2"
      ? "assets/floor_plan_level2.svg"
      : "assets/floor_plan_level1.svg";
    if (str(els.mapImg.getAttribute("src")) !== imgSrc) {
      els.mapImg.setAttribute("src", imgSrc);
    }
    els.mapOrb.hidden = false;
    els.mapOrb.style.left = anchor.x + "%";
    els.mapOrb.style.top = anchor.y + "%";
    setText(els.mapZoneLabel, zoneLabel);
  }

  function renderRelationship(state) {
    const rel = obj(state.relationshipState);
    const hasData = Object.keys(rel).length > 0;
    els.relationshipLabel.textContent = str(rel.userEmotionLabel) || (hasData ? "已建立" : "--");
    els.relationshipBars.textContent = "";
    if (!hasData) {
      els.relationshipBars.appendChild(p("暂无关系数据", "wdw-events-empty"));
      return;
    }
    const metrics = [
      ["亲密度", rel.attachment],
      ["信任度", rel.trust],
      ["安全感", rel.security],
      ["温暖", rel.warmth],
      ["冲突度", rel.conflict],
    ];
    let any = false;
    for (const [name, value] of metrics) {
      const n = Number(value);
      if (!Number.isFinite(n)) continue;
      any = true;
      const row = document.createElement("div");
      row.className = "wdw-rel";
      const title = document.createElement("span");
      title.className = "wdw-rel-name";
      title.textContent = name;
      const bar = document.createElement("div");
      bar.className = "wdw-bar";
      const fill = document.createElement("div");
      fill.className = "wdw-bar-fill wdw-bar-fill--rel";
      fill.style.width = clampPct(n) + "%";
      bar.appendChild(fill);
      row.appendChild(title);
      row.appendChild(bar);
      els.relationshipBars.appendChild(row);
    }
    if (!any) {
      els.relationshipBars.appendChild(p("暂无关系数据", "wdw-events-empty"));
    }
  }

  function renderRelationshipHistory() {
    const rel = obj(lastState && lastState.relationshipState);
    els.relationshipHistory.textContent = "";
    const history = Array.isArray(rel.repairHistory) ? rel.repairHistory : [];
    if (!history.length) {
      els.relationshipHistory.appendChild(p("暂无修复历史", "wdw-events-empty"));
      return;
    }
    history.slice(0, 20).forEach((h) => {
      const row = document.createElement("div");
      row.className = "wdw-row";
      const main = document.createElement("span");
      main.className = "wdw-row-main";
      main.textContent = str(h.summary) || str(h.reason) || "--";
      const meta = document.createElement("span");
      meta.className = "wdw-row-meta";
      meta.textContent = formatTs(h.createdAt) || formatTs(h.ts);
      row.appendChild(main);
      row.appendChild(meta);
      els.relationshipHistory.appendChild(row);
    });
  }

  async function loadMemory() {
    const bridge = api();
    if (!bridge || typeof bridge.getMemory !== "function") return;
    els.memoryGroups.textContent = "";
    els.memoryGroups.appendChild(p("加载中…", "wdw-events-empty"));
    let data;
    try {
      data = await bridge.getMemory();
    } catch (_) {
      data = null;
    }
    els.memoryGroups.textContent = "";
    const groups = (data && obj(data.layers)) || {};
    const layerNames = Object.keys(groups);
    if (!layerNames.length) {
      els.memoryGroups.appendChild(p("暂无记忆", "wdw-events-empty"));
      return;
    }
    const order = ["working", "long_term", "permanent"];
    const labels = { working: "短期", long_term: "长期", permanent: "永久", situational: "情景" };
    order.concat(layerNames.filter((n) => !order.includes(n))).forEach((name) => {
      const rows = Array.isArray(groups[name]) ? groups[name] : [];
      if (!rows.length) return;
      const head = document.createElement("h3");
      head.className = "wdw-memory-group-title";
      head.textContent = (labels[name] || name) + "（" + rows.length + "）";
      els.memoryGroups.appendChild(head);
      const list = document.createElement("ul");
      list.className = "wdw-memory-list";
      rows.slice(0, 10).forEach((row) => {
        const li = document.createElement("li");
        const content = document.createElement("span");
        content.className = "wdw-memory-content";
        content.textContent = str(row.content) || "(空)";
        const imp = Number(row.importance);
        const badge = document.createElement("span");
        badge.className = "wdw-memory-imp";
        badge.textContent = Number.isFinite(imp) ? "重要度 " + imp.toFixed(1) : str(row.memory_type);
        li.appendChild(content);
        li.appendChild(badge);
        list.appendChild(li);
      });
      els.memoryGroups.appendChild(list);
    });
    if (!els.memoryGroups.childNodes.length) {
      els.memoryGroups.appendChild(p("暂无记忆", "wdw-events-empty"));
    }
  }

  async function runControl(action, btn) {
    const bridge = api();
    const msg = els.consoleMsg;
    if (!bridge || typeof bridge.control !== "function") {
      msg.textContent = "控制接口不可用";
      return;
    }
    if (btn) btn.disabled = true;
    msg.textContent = "执行 " + action + " …";
    try {
      const result = await bridge.control(action);
      const r = result && typeof result === "object" ? result : {};
      if (r.accepted === true) {
        msg.textContent = "已执行：" + action;
      } else {
        const code = String(r.errorCode || r.error_code || "rejected");
        msg.textContent = "未执行：" + action + "（" + code + "）";
      }
      refresh();
    } catch (_) {
      msg.textContent = "执行失败：" + action;
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ── P2 时间线聚合 ──────────────────────────────────────────────
  function renderTimeline(state) {
    const timeline = Array.isArray(state && state.actionTimeline) ? state.actionTimeline : [];
    els.timeline.textContent = "";
    if (!timeline.length) {
      els.timeline.appendChild(p("等待数据…", "wdw-events-empty"));
      return;
    }
    // 按 daypart 聚合（睡眠→晨间→工作→休息→夜间）
    const buckets = [
      { key: "sleep", label: "睡眠" },
      { key: "breakfast", label: "晨间" },
      { key: "work", label: "工作" },
      { key: "rest", label: "休息" },
      { key: "evening", label: "晚间" },
    ];
    const counts = {};
    buckets.forEach((b) => { counts[b.key] = 0; });
    timeline.forEach((ev) => {
      const t = (str(ev.topic) + " " + str(ev.eventType) + " " + str(ev.event_type)).toLowerCase();
      let key = "work";
      if (/sleep|sleeping|rest|nap/.test(t)) key = "sleep";
      else if (/breakfast|morning|wake/.test(t)) key = "breakfast";
      else if (/evening|night|dinner/.test(t)) key = "evening";
      else if (/walk|leisure|coffee|relax/.test(t)) key = "rest";
      counts[key] += 1;
    });
    const max = Math.max(1, ...Object.values(counts));
    buckets.forEach((b) => {
      const n = counts[b.key];
      const row = document.createElement("div");
      row.className = "wdw-tl-row";
      const dot = document.createElement("span");
      dot.className = "wdw-tl-dot";
      const label = document.createElement("span");
      label.className = "wdw-tl-label";
      label.textContent = b.label;
      const bar = document.createElement("div");
      bar.className = "wdw-tl-bar";
      const fill = document.createElement("div");
      fill.className = "wdw-tl-fill";
      fill.style.width = (n / max * 100) + "%";
      bar.appendChild(fill);
      const time = document.createElement("span");
      time.className = "wdw-tl-time";
      time.textContent = n + " 事件";
      row.appendChild(dot);
      row.appendChild(label);
      row.appendChild(bar);
      row.appendChild(time);
      els.timeline.appendChild(row);
    });
  }

  // ── P3 内在状态 ────────────────────────────────────────────────
  function renderInternal() {
    const internal = obj(b3.internal);
    els.internal.textContent = "";
    if (!internal.needs && !internal.fatigue && !internal.neurochemicals) {
      els.internal.appendChild(p("等待数据…", "wdw-events-empty"));
      return;
    }
    const needsLabels = { social: "社交", companion: "陪伴", exploration: "探索", rest: "休息" };
    if (internal.needs) {
      els.internal.appendChild(groupTitle("需求"));
      els.internal.appendChild(metricList(internal.needs, needsLabels, "needs"));
    }
    if (internal.fatigue) {
      els.internal.appendChild(groupTitle("疲劳"));
      const row = document.createElement("div");
      row.className = "wdw-metric-row";
      row.appendChild(metricName("疲劳度"));
      row.appendChild(barFill(clamp01(internal.fatigue.value) * 100));
      row.appendChild(metricVal(internal.fatigue.value.toFixed(2)));
      row.appendChild(metricSrc(internal.fatigue.source));
      els.internal.appendChild(row);
    }
    if (internal.neurochemicals) {
      const neuroLabels = { vitality: "活力", calm: "平静", strain: "压力" };
      els.internal.appendChild(groupTitle("类神经化学（计算指标）"));
      els.internal.appendChild(metricList(internal.neurochemicals, neuroLabels, "neuro"));
    }
  }

  function groupTitle(text) {
    const h = document.createElement("h3");
    h.className = "wdw-metric-group-title";
    h.textContent = text;
    return h;
  }
  function metricName(text) {
    const span = document.createElement("span");
    span.className = "wdw-metric-name";
    span.textContent = text;
    return span;
  }
  function metricVal(text) {
    const span = document.createElement("span");
    span.className = "wdw-pad-val";
    span.textContent = text;
    return span;
  }
  function metricSrc(text) {
    const span = document.createElement("span");
    span.className = "wdw-metric-src";
    span.textContent = text ? "来源 " + text : "";
    return span;
  }
  function barFill(pct) {
    const bar = document.createElement("div");
    bar.className = "wdw-bar";
    const fill = document.createElement("div");
    fill.className = "wdw-bar-fill wdw-bar-fill--rel";
    fill.style.width = Math.max(0, Math.min(100, pct)) + "%";
    bar.appendChild(fill);
    return bar;
  }
  function metricList(metrics, labels, _group) {
    const list = document.createElement("div");
    list.className = "wdw-metric-list";
    Object.keys(metrics).forEach((key) => {
      const m = metrics[key];
      const row = document.createElement("div");
      row.className = "wdw-metric-row";
      row.appendChild(metricName(labels[key] || key));
      row.appendChild(barFill(clamp01(m.value) * 100));
      row.appendChild(metricVal(Number(m.value).toFixed(2)));
      row.appendChild(metricSrc(m.source));
      list.appendChild(row);
    });
    return list;
  }

  // ── P5 决策观察器 ──────────────────────────────────────────────
  function renderDecision() {
    const traces = Array.isArray(b3.cognition) ? b3.cognition : [];
    els.decision.textContent = "";
    if (!traces.length) {
      els.decision.appendChild(p("暂无决策轨迹", "wdw-events-empty"));
      return;
    }
    traces.slice(0, 30).forEach((t) => {
      const row = document.createElement("div");
      row.className = "wdw-row";
      const main = document.createElement("span");
      main.className = "wdw-row-main";
      main.textContent = str(t.goal) || str(t.topic) || str(t.source) || "决策";
      const meta = document.createElement("span");
      meta.className = "wdw-row-meta";
      meta.textContent = (str(t.source) ? str(t.source) + " · " : "") + formatTs(t.createdAt);
      row.appendChild(main);
      row.appendChild(meta);
      els.decision.appendChild(row);
    });
    // P4: 候选决策日志（伪主观性证据：候选→选择→动机句）。
    const logs = Array.isArray(b3.decisionLog) ? b3.decisionLog : [];
    if (logs.length) {
      const head = document.createElement("div");
      head.className = "wdw-section-title";
      head.textContent = "候选决策日志";
      els.decision.appendChild(head);
      logs.slice(0, 30).forEach((log) => {
        const chosen = obj(log.chosen) || {};
        const chosenTopic = str(chosen.topic) || str(chosen.to_zone) || str(chosen.mode) || "选择";
        const row = document.createElement("div");
        row.className = "wdw-row";
        const main = document.createElement("span");
        main.className = "wdw-row-main";
        main.textContent = str(log.kind) + " → " + chosenTopic;
        const meta = document.createElement("span");
        meta.className = "wdw-row-meta";
        meta.textContent = (log.fallback ? "兜底 · " : "") + formatTs(log.ts);
        row.appendChild(main);
        row.appendChild(meta);
        els.decision.appendChild(row);
      });
    }
  }

  // ── P7 图片工作台 ──────────────────────────────────────────────
  function renderImageCandidates(state) {
    const candidates = Array.isArray(state && state.imageCandidates) ? state.imageCandidates : [];
    els.imageCandidates.textContent = "";
    if (!candidates.length) {
      els.imageCandidates.appendChild(p("暂无候选图片", "wdw-events-empty"));
      return;
    }
    candidates.forEach((c) => {
      const row = document.createElement("div");
      row.className = "wdw-row";
      const main = document.createElement("span");
      main.className = "wdw-row-main";
      main.textContent = str(c.scene) || str(c.promptKey) || "候选图片";
      const meta = document.createElement("span");
      meta.className = "wdw-row-meta";
      meta.textContent = "场景 " + (str(c.scene) || "--") + " · 得分 " + fmtNum(c.score);
      row.appendChild(main);
      row.appendChild(meta);
      els.imageCandidates.appendChild(row);
    });
  }

  // ── P9 插件设置 ────────────────────────────────────────────────
  function renderSettings() {
    const cfg = obj(b3.permissions);
    els.settings.textContent = "";
    if (!Object.keys(cfg).length) {
      els.settings.appendChild(p("等待数据…", "wdw-events-empty"));
      return;
    }
    appendSettingRow("默认行为", str(cfg.defaultAction) || str(cfg.default_action) || "--");
    appendSettingRow("联网策略", str(cfg.networking) || str(cfg.network) || "--");
    const resources = cfg.resources && typeof cfg.resources === "object" ? cfg.resources : null;
    if (resources) {
      Object.keys(resources).forEach((k) => appendSettingRow("资源·" + k, String(resources[k])));
    }
    const dirs = Array.isArray(cfg.allowedDirs) ? cfg.allowedDirs : (Array.isArray(cfg.dirs) ? cfg.dirs : []);
    if (dirs.length) appendSettingRow("允许目录", dirs.length + " 项");
    appendSettingRow("Persona 映射", str(cfg.personaMapping) || str(cfg.persona_mapping) || str(cfg.persona) || "--");
    appendWorldLocationEditor();
    if (!els.settings.childNodes.length) {
      els.settings.appendChild(p("等待数据…", "wdw-events-empty"));
    }
  }
  function appendWorldLocationEditor() {
    // 世界独立位置（城市）：驱动真实天气 / 附近地点 / 实时事件。
    const current = str(obj(b3.worldSummary).city) || "";
    const row = document.createElement("div");
    row.className = "wdw-row wdw-row--loc";
    const main = document.createElement("span");
    main.className = "wdw-row-main";
    main.textContent = "世界所在位置（城市）";
    const edit = document.createElement("span");
    edit.className = "wdw-row-meta wdw-row-meta--edit";
    const input = document.createElement("input");
    input.className = "wdw-loc-input";
    input.type = "text";
    input.placeholder = "如：上海 / 巴黎";
    input.value = current;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "wdw-loc-save";
    btn.textContent = "保存";
    btn.addEventListener("click", async () => {
      const bridge = api();
      const city = String(input.value || "").trim();
      if (!bridge || typeof bridge.setWorldLocation !== "function") {
        btn.textContent = "不可用";
        return;
      }
      btn.disabled = true;
      btn.textContent = "保存中…";
      try {
        const res = await bridge.setWorldLocation(city);
        const status = res && res.status;
        if (status === "ok") {
          const w = (res && res.weather) || {};
          const temp = str(w.temp);
          const desc = str(w.desc);
          btn.textContent = temp && desc && temp !== "—"
            ? `已保存 · ${city} ${temp}° ${desc}` : "已保存 ✓";
          refresh();
        } else {
          btn.textContent = "保存失败";
        }
      } catch (_) {
        btn.textContent = "保存失败";
      }
      setTimeout(() => { btn.disabled = false; btn.textContent = "保存"; }, 1500);
    });
    edit.appendChild(input);
    edit.appendChild(btn);
    row.appendChild(main);
    row.appendChild(edit);
    els.settings.appendChild(row);
  }
  function appendSettingRow(label, value) {
    const row = document.createElement("div");
    row.className = "wdw-row";
    const main = document.createElement("span");
    main.className = "wdw-row-main";
    main.textContent = label;
    const meta = document.createElement("span");
    meta.className = "wdw-row-meta";
    meta.textContent = str(value) || "--";
    row.appendChild(main);
    row.appendChild(meta);
    els.settings.appendChild(row);
  }

  // ── 趋势图（本地 canvas，无 CDN） ──────────────────────────────
  function drawTrends() {
    const canvases = [$("wdw-chart-pad"), $("wdw-chart-neuro"), $("wdw-chart-rel")];
    // 内在状态页未渲染（hidden 或尚未布局）时跳过，等可见后再画，
    // 避免用 0/300px 回退宽度绘制导致画布被拉伸、比例失真。
    if (canvases.some((c) => c && c.clientWidth <= 0)) return;

    const trends = Array.isArray(b3.trends) ? b3.trends : [];
    const padSeries = { P: [], A: [], D: [] };
    const neuroSeries = { vitality: [], calm: [], strain: [] };
    const relSeries = { attachment: [], trust: [], security: [], conflict: [] };
    trends.forEach((s) => {
      const pad = obj(s.pad);
      if (pad.P !== undefined || pad.A !== undefined || pad.D !== undefined) {
        padSeries.P.push(numAny(pad.P));
        padSeries.A.push(numAny(pad.A));
        padSeries.D.push(numAny(pad.D));
      }
      const neuro = obj(s.neurochemicals);
      if (neuro.vitality || neuro.calm || neuro.strain) {
        neuroSeries.vitality.push(numAny(neuro.vitality && neuro.vitality.value));
        neuroSeries.calm.push(numAny(neuro.calm && neuro.calm.value));
        neuroSeries.strain.push(numAny(neuro.strain && neuro.strain.value));
      }
      const rel = obj(s.relationship);
      if (Object.keys(rel).length) {
        relSeries.attachment.push(numAny(rel.attachment));
        relSeries.trust.push(numAny(rel.trust));
        relSeries.security.push(numAny(rel.security));
        relSeries.conflict.push(numAny(rel.conflict));
      }
    });
    // PAD 取值范围为 [-1,1]，需按 [-1,1] 域绘制，否则负值塌缩到底部、比例失真。
    drawChart($("wdw-chart-pad"), [
      { label: "愉悦 P", color: PAD_COLORS.P, values: padSeries.P },
      { label: "唤醒 A", color: PAD_COLORS.A, values: padSeries.A },
      { label: "支配 D", color: PAD_COLORS.D, values: padSeries.D },
    ], { min: -1, max: 1 });
    drawChart($("wdw-chart-neuro"), [
      { label: "活力", color: NEURO_COLORS.vitality, values: neuroSeries.vitality },
      { label: "平静", color: NEURO_COLORS.calm, values: neuroSeries.calm },
      { label: "压力", color: NEURO_COLORS.strain, values: neuroSeries.strain },
    ]);
    drawChart($("wdw-chart-rel"), [
      { label: "亲密度", color: REL_COLORS.attachment, values: relSeries.attachment },
      { label: "信任", color: REL_COLORS.trust, values: relSeries.trust },
      { label: "安全感", color: REL_COLORS.security, values: relSeries.security },
      { label: "冲突", color: REL_COLORS.conflict, values: relSeries.conflict },
    ]);
  }

  function drawChart(canvas, series, opts) {
    if (!canvas || !canvas.getContext) return;
    const ctx = canvas.getContext("2d");
    const cfg = opts && typeof opts === "object" ? opts : {};
    const lo = Number.isFinite(cfg.min) ? cfg.min : 0;
    const hi = Number.isFinite(cfg.max) ? cfg.max : 1;
    const span = hi - lo || 1;
    const dpr = window.devicePixelRatio || 1;
    const cssW = canvas.clientWidth || 300;
    const cssH = canvas.clientHeight || 120;
    canvas.width = Math.max(1, Math.round(cssW * dpr));
    canvas.height = Math.max(1, Math.round(cssH * dpr));
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssW, cssH);
    // 主题色：从 CSS 变量读取，随主程序明暗主题自适应。
    const cs = getComputedStyle(document.documentElement);
    const gridColor = (cs.getPropertyValue("--wdw-bar") || "").trim() || "#e5e5ea";
    const textColor = (cs.getPropertyValue("--wdw-text") || "").trim() || "#1d1d1f";
    const mutedColor = (cs.getPropertyValue("--wdw-muted") || "").trim() || "#8e8e93";
    const padX = 8, padY = 8;
    const w = cssW - padX * 2;
    const h = cssH - padY * 2;
    // 网格
    ctx.strokeStyle = gridColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    for (let i = 0; i <= 4; i++) {
      const y = padY + h * i / 4;
      ctx.moveTo(padX, y);
      ctx.lineTo(cssW - padX, y);
    }
    ctx.stroke();
    // 数据线
    const maxLen = Math.max(1, ...series.map((s) => s.values.length));
    let hasData = false;
    series.forEach((s) => {
      const vals = s.values.filter((v) => Number.isFinite(v));
      if (vals.length < 2) return;
      hasData = true;
      ctx.strokeStyle = s.color;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      vals.forEach((v, i) => {
        const x = padX + (maxLen <= 1 ? 0 : w * i / (maxLen - 1));
        const t = (v - lo) / span;
        const y = padY + h - Math.max(0, Math.min(1, t)) * h;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      });
      ctx.stroke();
    });
    if (!hasData) {
      ctx.fillStyle = mutedColor;
      ctx.font = "11px sans-serif";
      ctx.textAlign = "center";
      ctx.fillText("暂无趋势数据", cssW / 2, cssH / 2 + 4);
    }
    // 图例（右上）
    let lx = cssW - padX;
    ctx.font = "10px sans-serif";
    ctx.textAlign = "right";
    series.forEach((s, i) => {
      if (!s.values.some((v) => Number.isFinite(v))) return;
      const ly = padY + 8 + i * 12;
      ctx.fillStyle = s.color;
      ctx.fillRect(lx - 34, ly - 7, 8, 8);
      ctx.fillStyle = textColor;
      ctx.fillText(s.label, lx - 8, ly);
    });
  }

  function p(text, cls) {
    const el = document.createElement("p");
    el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }

  // ── P4 数据统计看板（ECharts，完整版本地 vendor） ─────────────
  // 结构对应 /api/stats/dashboard：tokens.daily_series/by_provider、
  // topics.top、decisions.total/by_kind。切换页签/窗口时按需拉取。
  const statsCharts = { tokens: null, topics: null, decisions: null };

  async function renderStats() {
    const bridge = api();
    if (!bridge || typeof bridge.getStats !== "function") return;
    const win = els.statsWindow ? els.statsWindow.value : "7d";
    let data;
    try {
      data = await bridge.getStats(win);
    } catch (_) {
      data = null;
    }
    data = data && typeof data === "object" ? data : {};
    renderStatsKpis(data);
    renderTokensChart(data);
    renderTopicsChart(data);
    renderDecisionsChart(data);
    const hasAny = (Array.isArray(data.tokens && data.tokens.daily_series) && data.tokens.daily_series.length)
      || (Array.isArray(data.topics && data.topics.top) && data.topics.top.length)
      || Number(data.decisions && data.decisions.total) > 0;
    if (els.statsEmpty) els.statsEmpty.hidden = !!hasAny;
  }

  function renderStatsKpis(data) {
    if (!els.statsKpis) return;
    els.statsKpis.textContent = "";
    const series = Array.isArray(data.tokens && data.tokens.daily_series) ? data.tokens.daily_series : [];
    // 后端按 date('now')（UTC 日）聚合，今日比对也用 UTC 日期。
    const today = new Date();
    const pad = (n) => String(n).padStart(2, "0");
    const todayStr = today.getUTCFullYear() + "-" + pad(today.getUTCMonth() + 1) + "-" + pad(today.getUTCDate());
    let todayTokens = 0, totalTokens = 0, totalCalls = 0;
    series.forEach((s) => {
      const tokens = Number(s.total_tokens) || 0;
      const calls = Number(s.calls) || 0;
      totalTokens += tokens;
      totalCalls += calls;
      if (String(s.date) === todayStr) todayTokens = tokens;
    });
    // 数据未含今日（早于当日入库）时回退到最近一天
    const last = series[series.length - 1];
    if (todayTokens === 0 && last) todayTokens = Number(last.total_tokens) || 0;
    const dec = obj(data.decisions);
    const decTotal = Number(dec.total) || 0;
    const rate = Number(dec.chosen_rate);
    const rateTxt = Number.isFinite(rate) ? Math.round(rate * 100) + "%" : "--";
    els.statsKpis.appendChild(kpiCard("今日 Token", fmtInt(todayTokens)));
    els.statsKpis.appendChild(kpiCard("窗口 Token", fmtInt(totalTokens)));
    els.statsKpis.appendChild(kpiCard("调用次数", fmtInt(totalCalls)));
    els.statsKpis.appendChild(kpiCard("决策记录", fmtInt(decTotal), "命中率 " + rateTxt));
  }

  function kpiCard(label, value, suffix) {
    const card = document.createElement("div");
    card.className = "wdw-kpi";
    const l = document.createElement("span");
    l.className = "wdw-kpi-label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "wdw-kpi-value";
    v.textContent = value;
    if (suffix) {
      const s = document.createElement("small");
      s.textContent = suffix;
      v.appendChild(s);
    }
    card.appendChild(l);
    card.appendChild(v);
    return card;
  }

  function fmtInt(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "--";
    return n >= 10000 ? (n / 10000).toFixed(1) + "w" : String(Math.round(n));
  }

  function statsTheme() {
    const cs = getComputedStyle(document.documentElement);
    const v = (name, fallback) => (cs.getPropertyValue(name) || "").trim() || fallback;
    return {
      text: v("--wdw-text", "#1d1d1f"),
      muted: v("--wdw-muted", "#8e8e93"),
      bar: v("--wdw-bar", "#e5e5ea"),
      accent: v("--wdw-accent", "#007aff"),
      bg: v("--wdw-list", "#f2f2f7"),
    };
  }

  function hasECharts() {
    return typeof window.echarts !== "undefined" && typeof window.echarts.init === "function";
  }

  function setStatsOption(key, option) {
    const el = els.statsCharts[key];
    if (!el) return;
    if (!hasECharts()) { el.textContent = "图表引擎不可用"; return; }
    if (!option) {
      if (statsCharts[key]) { statsCharts[key].dispose(); statsCharts[key] = null; }
      el.textContent = "暂无数据";
      return;
    }
    if (!statsCharts[key]) {
      statsCharts[key] = window.echarts.init(el, null, { renderer: "canvas" });
    }
    statsCharts[key].setOption(option, true);
    el.textContent = "";
  }

  function resizeStatsCharts() {
    Object.keys(statsCharts).forEach((k) => { if (statsCharts[k]) statsCharts[k].resize(); });
  }

  function renderTokensChart(data) {
    const series = Array.isArray(data.tokens && data.tokens.daily_series) ? data.tokens.daily_series : [];
    if (!series.length) { setStatsOption("tokens", null); return; }
    const th = statsTheme();
    setStatsOption("tokens", {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis" },
      legend: { top: 0, right: 0, textStyle: { color: th.muted, fontSize: 10 }, itemWidth: 12, itemHeight: 8 },
      grid: { left: 8, right: 8, top: 28, bottom: 8, containLabel: true },
      xAxis: {
        type: "category",
        data: series.map((s) => String(s.date).slice(5)),
        axisLabel: { color: th.muted, fontSize: 10 },
        axisLine: { lineStyle: { color: th.bar } },
        axisTick: { show: false },
      },
      yAxis: [
        { type: "value", name: "Token", nameTextStyle: { color: th.muted, fontSize: 10 }, axisLabel: { color: th.muted, fontSize: 10 }, splitLine: { lineStyle: { color: th.bar } } },
        { type: "value", name: "调用", nameTextStyle: { color: th.muted, fontSize: 10 }, axisLabel: { color: th.muted, fontSize: 10 }, splitLine: { show: false } },
      ],
      series: [
        { name: "Token", type: "line", smooth: true, data: series.map((s) => Number(s.total_tokens) || 0), itemStyle: { color: th.accent }, lineStyle: { width: 2 }, areaStyle: { opacity: 0.12 } },
        { name: "调用", type: "line", yAxisIndex: 1, data: series.map((s) => Number(s.calls) || 0), itemStyle: { color: "#34c759" }, lineStyle: { width: 1.5 } },
      ],
    });
  }

  function renderTopicsChart(data) {
    const topics = Array.isArray(data.topics && data.topics.top) ? data.topics.top : [];
    if (!topics.length) { setStatsOption("topics", null); return; }
    const th = statsTheme();
    setStatsOption("topics", {
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", axisPointer: { type: "shadow" } },
      grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
      xAxis: { type: "value", minInterval: 1, axisLabel: { color: th.muted, fontSize: 10 }, splitLine: { lineStyle: { color: th.bar } } },
      yAxis: { type: "category", inverse: true, data: topics.map((t) => str(t.topic) || "--"), axisLabel: { color: th.text, fontSize: 11 }, axisLine: { lineStyle: { color: th.bar } }, axisTick: { show: false } },
      series: [{ type: "bar", data: topics.map((t) => Number(t.count) || 0), itemStyle: { color: th.accent, borderRadius: [0, 4, 4, 0] }, barWidth: 12 }],
    });
  }

  function renderDecisionsChart(data) {
    const byKind = obj(data.decisions && data.decisions.by_kind);
    const kindNames = { topic_motive: "话题动机", behavior: "行为决策", movement: "移动决策", unknown: "未知" };
    const pieData = Object.keys(byKind).map((k) => ({ name: kindNames[k] || k, value: Number(byKind[k]) || 0 }));
    if (!pieData.length) { setStatsOption("decisions", null); return; }
    const th = statsTheme();
    setStatsOption("decisions", {
      backgroundColor: "transparent",
      tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
      legend: { bottom: 0, textStyle: { color: th.muted, fontSize: 10 }, itemWidth: 12, itemHeight: 8 },
      color: ["#007aff", "#34c759", "#5e5ce6", "#ff9500", "#ff3b30", "#8e8e93"],
      series: [{
        type: "pie",
        radius: ["42%", "68%"],
        center: ["50%", "44%"],
        label: { color: th.text, fontSize: 11, formatter: "{b}\n{c}" },
        itemStyle: { borderRadius: 4, borderColor: th.bg, borderWidth: 2 },
        data: pieData,
      }],
    });
  }

  function renderPad(pad) {
    const P = num(pad, ["P", "pleasure"]);
    const A = num(pad, ["A", "arousal"]);
    const D = num(pad, ["D", "dominance"]);
    setPad("P", P);
    setPad("A", A);
    setPad("D", D);
  }

  function setPad(key, value) {
    if (!Number.isFinite(value)) { value = 0; }
    const pct = Math.max(0, Math.min(100, (value + 1) / 2 * 100));
    els.padBar[key].style.width = pct + "%";
    els.padVal[key].textContent = value.toFixed(2);
  }

  // ── 事件流（带过滤） ───────────────────────────────────────────
  function eventCategory(ev) {
    const t = (str(ev.eventType) + " " + str(ev.event_type) + " " + str(ev.topic) + " " + str(ev.category) + " " + str(ev.source)).toLowerCase();
    if (/image|picture|photo|img|画|图/.test(t)) return "image";
    if (/memory|记忆|recall|remember/.test(t)) return "memory";
    if (/relationship|relation|repair|关系|修复|trust|亲密/.test(t)) return "relationship";
    if (/system|plugin|config|系统|配置|restart|error|异常/.test(t)) return "system";
    return "world";
  }

  function renderEvents(state) {
    const timeline = Array.isArray(state.actionTimeline) ? state.actionTimeline : [];
    els.events.textContent = "";
    if (!timeline.length) {
      els.events.appendChild(li("等待数据…", "wdw-events-empty"));
      return;
    }
    const recent = timeline.slice(0, 20).filter((ev) => {
      if (eventFilter === "all") return true;
      return eventCategory(ev) === eventFilter;
    });
    if (!recent.length) {
      els.events.appendChild(li("该分类暂无事件", "wdw-events-empty"));
      return;
    }
    for (const ev of recent) {
      const item = document.createElement("li");
      const topic = document.createElement("span");
      topic.textContent = str(ev.topic) || str(ev.eventType) || str(ev.event_type) || "--";
      const seq = document.createElement("span");
      seq.className = "wdw-events-seq";
      seq.textContent = str(ev.sequence);
      item.appendChild(topic);
      item.appendChild(seq);
      els.events.appendChild(item);
    }
  }

  function li(text, cls) {
    const el = document.createElement("li");
    el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }

  function renderUnavailable() {
    setStatus("offline");
    setText(els.worldTime, "--:--:--");
    if (els.locIndicator) els.locIndicator.hidden = true;
    if (els.mapBox) els.mapBox.hidden = true;
    if (els.scene) els.scene.classList.remove("has-loc");
  }

  function setStatus(status) {
    const key = mapStatus(status);
    els.status.textContent = statusLabel(key);
    els.status.className = "wdw-status wdw-status--" + key;
    els.status.setAttribute("data-status", key);
  }

  function mapStatus(status) {
    const s = str(status).toLowerCase();
    if (s === "running" || s === "ready") return "running";
    if (s === "paused") return "paused";
    if (s === "disabled" || s === "unknown") return "idle";
    if (s === "recovering" || s === "booting" || s === "starting") return "recovering";
    if (s === "permission_denied" || s === "denied") return "denied";
    if (s === "diff" || s === "out_of_sync") return "diff";
    return "offline";
  }

  function statusLabel(key) {
    const map = {
      running: "运行中",
      paused: "已暂停",
      idle: "未启用",
      recovering: "恢复中",
      denied: "权限受限",
      diff: "数据不同步",
      offline: "离线",
    };
    return map[key] || "未知";
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(() => { if (visible) { refresh(); loadB3(); } }, POLL_MS);
  }
  function stopPolling() {
    if (!pollTimer) return;
    clearInterval(pollTimer);
    pollTimer = null;
  }

  // ── 工具 ──
  function obj(v) { return v && typeof v === "object" ? v : {}; }
  function str(v) { return String(v || "").replace(/\0/g, "").trim().slice(0, 200); }
  function num(v, keys) {
    for (const k of keys) {
      const n = Number(v && v[k]);
      if (Number.isFinite(n)) return n;
    }
    return NaN;
  }
  function numAny(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n : NaN;
  }
  function fmtNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toFixed(2) : "--";
  }
  function clamp01(n) {
    const v = Number(n);
    if (!Number.isFinite(v)) return 0;
    return Math.max(0, Math.min(1, v));
  }
  function setText(el, text) { if (el) el.textContent = text; }
  function formatEnergy(v) {
    if (v === undefined || v === null || v === "") return "--";
    const n = Number(v);
    if (Number.isFinite(n) && n > 0 && n <= 1) return Math.round(n * 100) + "%";
    return str(v);
  }
  function floorLabel(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "--";
    const names = { 1: "一层 / 1F", 2: "二层 / 2F" };
    return names[n] || n + " 层 / " + n + "F";
  }
  function formatWorldTime(state) {
    const ts = Number(state && state.updatedAt) || Number(obj(state.worldSummary).generatedAt);
    if (!ts) return "--:--:--";
    try {
      const d = new Date(ts);
      const p = (n) => String(n).padStart(2, "0");
      return p(d.getHours()) + ":" + p(d.getMinutes()) + ":" + p(d.getSeconds());
    } catch (_) { return "--:--:--"; }
  }
  function formatTs(v) {
    if (!v) return "--";
    try {
      const d = new Date(v);
      const p = (n) => String(n).padStart(2, "0");
      return p(d.getHours()) + ":" + p(d.getMinutes());
    } catch (_) { return "--"; }
  }
  function normPhase(v) {
    const s = v.toLowerCase();
    if (["night", "evening"].includes(s)) return s === "evening" ? "evening" : "night";
    if (["morning"].includes(s)) return "morning";
    return "day";
  }
  function normWeather(v) {
    const s = v.toLowerCase();
    if (["rain", "snow", "cloudy", "fog", "windy", "partly_cloudy"].includes(s)) return s;
    return "neutral";
  }
  function weatherLabel(v) {
    const map = {
      clear: "晴", partly_cloudy: "多云", cloudy: "阴", rain: "雨",
      windy: "风", fog: "雾", snow: "雪", neutral: "—",
    };
    return map[v] || "—";
  }
  function clampPct(n) {
    const value = Number(n);
    if (!Number.isFinite(value)) return 0;
    return Math.max(0, Math.min(100, value * 100));
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
