"use strict";
/* Cognition Panel — Phase 9 Batch 4 (brain center)
 *
 * Responsibilities:
 *   1) Subscribe to the in-process SSE event stream and render live events.
 *   2) When a cognition_committed event fires, light up the 9-stage timeline
 *      + replay the decision race chart.
 *   3) Keep a rolling buffer of the last 50 events (live stream pane).
 *   4) Fetch and render the historical trace list (with filter + search).
 *   5) Open a detail modal when a history row is clicked.
 *   6) Pulse the live indicator so the user can see the stream is alive.
 *
 * Defensive notes:
 *   - All SSE payloads are wrapped in try/catch — a malformed frame must
 *     never kill the panel.
 *   - API responses may use {data: {…}} wrapping or the unwrapped form.
 *     We always read via r.data with a safety net.
 *   - B6 will mount self-evolution proposal cards into #cog-proposal-card;
 *     this module only owns the slot, not the content.
 */

const STAGE_NAMES_ZH = {
  route: "路由",
  emotion: "情绪",
  threshold: "阈值",
  context: "上下文",
  brain: "大脑",
  tools: "工具",
  split: "切分",
  postprocess: "后处理",
  output: "输出",
};

const STAGE_ORDER = [
  "route", "emotion", "threshold", "context",
  "brain", "tools", "split", "postprocess", "output",
];

const DECISION_CANDIDATES = ["reply", "tool_call", "recall", "silence"];

const DECISION_LABELS_ZH = {
  reply: "回复",
  tool_call: "调工具",
  recall: "撤回",
  silence: "沉默",
};

const LIVE_BUFFER_MAX = 50;
const SEARCH_DEBOUNCE_MS = 250;

class CognitionPanel {
  constructor() {
    this._unsubscribeSse = null;
    this._visible = false;
    this._paused = false;
    this._liveBuffer = [];     // newest first
    this._pendingDecision = null;
    this._pendingTimelineTrace = null;
    this._currentTrace = null; // last committed trace (used for modal)
    this._searchTimer = null;
    this._pulseTimer = null;
  }

  // ── Public lifecycle ─────────────────────────────
  init() {
    this._bindToolbar();
    this._bindModal();
    this._bindSse();
    this._bindV2Tabs();        // v2: 5 tab navigation
    this._bindV2Refresh();     // v2: refresh buttons on capability tabs
    this._bindQQWhitelist();   // v13.9: QQ whitelist management
    this._bindCCLevelButtons(); // v13.9: computer control permission level buttons
    this._loadHistory();
    this._loadStats();
    this._loadPendingProposals();
    this._loadV2DemoData();    // v2: seed demo data for capability tabs
    this._loadQQWhitelist();   // v13.9: load whitelist on init
    setInterval(() => this._loadStats(), 8000);
  }

  setVisible(v) {
    this._visible = !!v;
    if (v) {
      // Re-fetch history + stats when the panel becomes visible so the
      // user doesn't stare at a stale list.
      this._loadHistory();
      this._loadStats();
      // Also seed the timeline with the most recent trace so the user
      // sees something useful even before the next message arrives.
      this._seedTimelineFromLatestHistory();
    }
  }

  async _seedTimelineFromLatestHistory() {
    // Only seed if we don't already have a live trace in flight.
    if (this._pendingTimelineTrace) return;
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/cognition/recent?limit=1",
      });
      const top = (r.data && r.data.traces && r.data.traces[0]) || null;
      if (!top) return;
      const detail = await window.aerie.api.request({
        method: "GET",
        path: "/api/cognition/" + top.id,
      });
      const row = detail.data;
      if (!row || row.error) return;
      this._currentTrace = {
        id: row.id,
        user_id: row.user_id,
        duration_ms: row.duration_ms,
        ts: row.ts,
      };
      this._lastFullTrace = row;
      // Reconstruct stages from row columns
      const stages = {};
      for (const s of STAGE_ORDER) {
        const raw = row["stage_" + s];
        if (raw) {
          try { stages[s] = JSON.parse(raw); } catch (_) { stages[s] = raw; }
        }
      }
      this._pendingTimelineTrace = {
        user_id: row.user_id,
        ts: row.ts,
        stages,
        trace_id: row.id,
      };
      // Mark all stages as done (no active highlight since trace is committed)
      this._renderTimeline(this._pendingTimelineTrace, null);
      // Also seed the decision race if available
      if (row.decision_trace) {
        try {
          this._renderDecisionRace(JSON.parse(row.decision_trace));
        } catch (_) {}
      }
    } catch (e) {
      // Non-fatal — the empty state is acceptable.
    }
  }

  // ── Toolbar wiring ──────────────────────────────
  _bindToolbar() {
    const src = document.getElementById("cog-source-filter");
    if (src) src.addEventListener("change", () => this._loadHistory());

    const search = document.getElementById("cog-search");
    if (search) {
      search.addEventListener("input", () => {
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(
          () => this._loadHistory(), SEARCH_DEBOUNCE_MS
        );
      });
    }

    const refresh = document.getElementById("cog-refresh");
    if (refresh) refresh.addEventListener("click", () => this._loadHistory());

    const pause = document.getElementById("cog-pause");
    if (pause) {
      pause.addEventListener("click", () => {
        this._paused = !this._paused;
        pause.setAttribute("data-paused", this._paused ? "true" : "false");
        pause.innerHTML = this._paused
          ? '<svg class="icon icon--12" aria-hidden="true"><use href="#icon-ui-play"/></svg> 继续'
          : '<svg class="icon icon--12" aria-hidden="true"><use href="#icon-ui-pause"/></svg> 暂停';
      });
    }

    const clear = document.getElementById("cog-clear");
    if (clear) clear.addEventListener("click", () => {
      this._liveBuffer = [];
      this._renderLive();
    });
  }

  // ── Modal wiring ────────────────────────────────
  _bindModal() {
    const modal = document.getElementById("cog-modal");
    if (!modal) return;
    modal.querySelectorAll("[data-close]").forEach((el) => {
      el.addEventListener("click", () => this._closeModal());
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && !modal.classList.contains("hidden")) {
        this._closeModal();
      }
    });
  }

  // ── SSE subscription ────────────────────────────
  _bindSse() {
    if (!window.aerie || !window.aerie.sse) {
      console.warn("[cog-panel] aerie.sse not available — events disabled");
      return;
    }
    try {
      this._unsubscribeSse = window.aerie.sse.subscribe((raw) => {
        if (this._paused) return;
        let payload;
        try { payload = JSON.parse(raw); } catch (_) { return; }
        if (!payload || typeof payload !== "object") return;
        this._handleSseEvent(payload);
      });
    } catch (e) {
      console.warn("[cog-panel] sse subscribe failed", e);
    }
  }

  _handleSseEvent(payload) {
    // Pulse the live dot so the user sees liveness.
    this._pulse();

    // Push into the live buffer (most recent first, capped).
    this._liveBuffer.unshift(payload);
    if (this._liveBuffer.length > LIVE_BUFFER_MAX) {
      this._liveBuffer.length = LIVE_BUFFER_MAX;
    }
    this._renderLive();

    // Special-cased events.
    switch (payload.type) {
      case "cognition_stage":
        this._handleStageEvent(payload);
        break;
      case "decision_made":
        this._handleDecisionEvent(payload);
        break;
      case "cognition_committed":
        this._handleCommittedEvent(payload);
        break;
      case "self_evolve_proposed":
        this._handleSelfEvolveProposed(payload);
        break;
      case "self_evolve_decided":
        this._handleSelfEvolveDecided(payload);
        break;
      default:
        break;
    }
  }

  // ── Self-evolution proposal cards (B6) ───────────
  _handleSelfEvolveProposed(payload) {
    // The new proposal just landed. Re-fetch the list so the card stays
    // in sync with the DB (avoids ordering / dedup issues).
    this._loadPendingProposals();
  }

  _handleSelfEvolveDecided(payload) {
    // Approve/reject happened. Re-fetch so the card flips to the
    // post-decision state.
    this._loadPendingProposals();
  }

  async _loadPendingProposals() {
    const root = document.getElementById("cog-proposal-card");
    if (!root) return;
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/self_evolve/list?status=pending&limit=10",
      });
      const data = r.data || {};
      const items = data.items || [];
      if (!items.length) {
        root.classList.add("hidden");
        root.innerHTML = "";
        return;
      }
      root.classList.remove("hidden");
      root.innerHTML = items.map((it) => this._renderProposalCard(it)).join("");
      this._bindProposalActions(root);
    } catch (e) {
      // Non-fatal: hide the slot.
      root.classList.add("hidden");
    }
  }

  _renderProposalCard(item) {
    const id = this._escape(String(item.id));
    const desc = this._truncate(item.description || "(无描述)", 100);
    const safety = this._escape(item.safety_check || "unknown");
    const decision = this._escape(item.user_decision || "pending");
    const ts = this._fmtTime(item.ts);
    const schema = item.proposed_tool_schema || {};
    const toolName = this._escape(schema.name || "ita_unnamed_tool");
    const decisionCls = decision === "pending" ? "cog-proposal-decision--pending"
      : decision === "approved" ? "cog-proposal-decision--approved"
      : "cog-proposal-decision--rejected";
    const disabled = decision !== "pending" ? "disabled" : "";
    const stateText = decision === "pending" ? "待你决定 / Awaiting you"
      : decision === "approved" ? "已升级 · Approved"
      : "已拒绝 · Rejected";
    return (
      '<div class="cog-proposal-item" data-proposal-id="' + id + '" data-decision="' + decision + '">'
      + '<div class="cog-proposal-head">'
      + '<span class="cog-proposal-id">#' + id + "</span>"
      + '<span class="cog-proposal-time">' + ts + "</span>"
      + '<span class="cog-proposal-safety cog-proposal-safety--' + safety + '">'
      + safety + "</span>"
      + '<span class="cog-proposal-decision ' + decisionCls + '">'
      + this._escape(stateText) + "</span>"
      + "</div>"
      + '<div class="cog-proposal-body">'
      + '<div class="cog-proposal-tool">提议工具 · proposed tool: '
      + '<code>' + toolName + "</code></div>"
      + '<div class="cog-proposal-desc">' + this._escape(desc) + "</div>"
      + "</div>"
      + '<div class="cog-proposal-actions">'
      + '<button class="btn btn-secondary btn-sm cog-proposal-preview" ' + disabled + '>查看预演 · Preview</button>'
      + '<button class="btn btn-primary btn-sm cog-proposal-approve" ' + disabled + '>批准 · Approve</button>'
      + '<button class="btn btn-secondary btn-sm cog-proposal-reject" ' + disabled + '>拒绝 · Reject</button>'
      + "</div>"
      + '<div class="cog-proposal-preview-box"></div>'
      + "</div>"
    );
  }

  _bindProposalActions(root) {
    root.querySelectorAll(".cog-proposal-item").forEach((el) => {
      const id = el.getAttribute("data-proposal-id");
      const previewBtn = el.querySelector(".cog-proposal-preview");
      const approveBtn = el.querySelector(".cog-proposal-approve");
      const rejectBtn = el.querySelector(".cog-proposal-reject");
      const box = el.querySelector(".cog-proposal-preview-box");
      if (previewBtn) {
        previewBtn.addEventListener("click", () => this._previewProposal(id, box));
      }
      if (approveBtn) {
        approveBtn.addEventListener("click", () => this._decideProposal(id, "approve", el));
      }
      if (rejectBtn) {
        rejectBtn.addEventListener("click", () => this._decideProposal(id, "reject", el));
      }
    });
  }

  async _previewProposal(id, box) {
    if (!box) return;
    box.innerHTML = '<div class="cog-proposal-loading">预演中… / Previewing…</div>';
    try {
      const r = await window.aerie.api.request({
        method: "POST",
        path: "/api/self_evolve/" + id + "/preview",
      });
      const data = r.data || {};
      if (!data.ok) {
        box.innerHTML = '<div class="cog-proposal-error">预演暂不可用 / '
          + this._escape(data.error || "unknown") + "</div>";
        return;
      }
      const risks = (data.risk_points || []).map((r) => "<li>" + this._escape(r) + "</li>").join("");
      const simOut = this._escape(data.simulated_output || "");
      const simArgs = this._escape(JSON.stringify(
        (data.simulated_input && data.simulated_input.arguments) || {},
        null, 2
      ));
      box.innerHTML = (
        '<div class="cog-proposal-preview-grid">'
        + '<div class="cog-proposal-preview-col">'
        + '<h5>输入 · simulated input</h5>'
        + '<pre>' + simArgs + "</pre>"
        + "</div>"
        + '<div class="cog-proposal-preview-col">'
        + '<h5>预计输出 · simulated output</h5>'
        + '<pre>' + simOut + "</pre>"
        + "</div>"
        + '<div class="cog-proposal-preview-col">'
        + "<h5>风险 · risk_points</h5>"
        + (risks ? "<ul>" + risks + "</ul>" : '<div class="cog-proposal-empty">无</div>')
        + "<div>safety: <b>" + this._escape(data.safety_check || "unknown") + "</b></div>"
        + "</div>"
        + "</div>"
      );
    } catch (e) {
      box.innerHTML = '<div class="cog-proposal-error">'
        + this._escape(e.message) + "</div>";
    }
  }

  async _decideProposal(id, kind, itemEl) {
    const path = "/api/self_evolve/" + id + "/" + kind;
    try {
      // Disable buttons while in flight.
      const buttons = itemEl.querySelectorAll("button");
      buttons.forEach((b) => { b.disabled = true; });
      const r = await window.aerie.api.request({ method: "POST", path });
      const data = r.data || {};
      if (data.status !== "ok") {
        // Re-enable on failure.
        buttons.forEach((b) => { b.disabled = false; });
        return;
      }
      // Refresh the list (or remove this card if there are no more pending).
      this._loadPendingProposals();
    } catch (_) {
      // Re-enable on failure.
      const buttons = itemEl.querySelectorAll("button");
      buttons.forEach((b) => { b.disabled = false; });
    }
  }

  // ── Stage events: light up the timeline progressively ──
  _handleStageEvent(payload) {
    const stage = payload.stage;
    if (!stage) return;
    // Initialise the timeline slot if we haven't yet for this trace.
    if (!this._pendingTimelineTrace
        || this._pendingTimelineTrace.user_id !== payload.user_id) {
      this._pendingTimelineTrace = {
        user_id: payload.user_id,
        ts: payload.ts,
        stages: {},
        trace_id: null,
      };
      this._renderTimeline(this._pendingTimelineTrace, /*activeStage*/ stage);
    } else {
      this._pendingTimelineTrace.stages[stage] = payload.payload;
      this._renderTimeline(this._pendingTimelineTrace, stage);
    }
  }

  _handleDecisionEvent(payload) {
    this._pendingDecision = payload;
    this._renderDecisionRace(payload);
  }

  _handleCommittedEvent(payload) {
    // When a trace is committed, remember it for the modal preview
    // and refresh the history list.
    if (payload && payload.id) {
      this._currentTrace = {
        id: payload.id,
        user_id: payload.user_id,
        duration_ms: payload.duration_ms,
        ts: payload.ts,
      };
    }
    this._loadHistory();
    this._loadStats();
  }

  // ── Live stream rendering ───────────────────────
  _renderLive() {
    const root = document.getElementById("cog-stream");
    if (!root) return;
    if (!this._liveBuffer.length) {
      root.innerHTML = '<div class="cog-timeline-empty">等待事件 / Waiting for events…</div>';
      return;
    }
    const rows = this._liveBuffer.map((p) => {
      const time = this._fmtTime(p.ts);
      const type = this._escape(p.type || "event");
      let detail = "";
      if (p.type === "cognition_stage" && p.stage) {
        detail = '<span class="cog-live-stage">stage=' + this._escape(p.stage) + "</span>";
      } else if (p.type === "decision_made") {
        detail = '<span class="cog-live-chosen">→ ' + this._escape(p.chosen || "?") + "</span>";
      } else if (p.type === "cognition_committed") {
        detail = '<span class="cog-live-id">#' + this._escape(String(p.id || "?")) + "</span>"
          + ' <span class="cog-live-dur">' + this._escape(String(p.duration_ms || 0)) + "ms</span>";
      } else if (p.user_id) {
        detail = '<span class="cog-live-uid">uid=' + this._escape(String(p.user_id)) + "</span>";
      }
      return (
        '<div class="cog-live-row cog-live-row--' + this._escape(type) + '">'
        + '<span class="cog-live-time">' + time + "</span>"
        + '<span class="cog-live-type">' + type + "</span>"
        + detail
        + "</div>"
      );
    });
    root.innerHTML = rows.join("");
  }

  // ── 9-stage timeline ────────────────────────────
  _renderTimeline(trace, activeStage) {
    const root = document.getElementById("cog-timeline");
    if (!root) return;
    if (!trace) {
      root.innerHTML = '<div class="cog-timeline-empty">还没有任何 trace。/ No trace yet.</div>';
      return;
    }
    const stages = trace.stages || {};
    const cells = STAGE_ORDER.map((s, idx) => {
      const has = Object.prototype.hasOwnProperty.call(stages, s);
      const isActive = activeStage === s;
      const cls = [
        "cog-tl-cell",
        has ? "cog-tl-cell--done" : "",
        isActive ? "cog-tl-cell--active" : "",
      ].filter(Boolean).join(" ");
      const preview = has ? this._stagePreview(s, stages[s]) : "";
      return (
        '<div class="' + cls + '" data-stage="' + s + '">'
        + '<div class="cog-tl-num">' + (idx + 1) + "</div>"
        + '<div class="cog-tl-name">' + STAGE_NAMES_ZH[s] + "</div>"
        + '<div class="cog-tl-en">' + s + "</div>"
        + '<div class="cog-tl-preview">' + preview + "</div>"
        + "</div>"
      );
    });
    const meta = trace.trace_id
      ? '<span class="cog-tl-meta">trace #' + this._escape(String(trace.trace_id))
        + " · uid " + this._escape(String(trace.user_id || "?")) + "</span>"
      : '<span class="cog-tl-meta">uid ' + this._escape(String(trace.user_id || "?"))
        + " · in flight</span>";
    root.innerHTML = (
      '<div class="cog-tl-meta-row">' + meta + "</div>"
      + '<div class="cog-tl-grid">' + cells.join("") + "</div>"
    );
  }

  _stagePreview(stage, payload) {
    if (!payload) return "";
    try {
      let s = "";
      switch (stage) {
        case "route":
          s = (payload.mode || payload.route_mode || "?") + "";
          break;
        case "emotion":
          s = (payload.label || payload.emotion || "neutral") + "";
          break;
        case "threshold": {
          const slots = payload.slots || payload;
          const active = Object.entries(slots || {})
            .filter(([, v]) => v && v.active)
            .map(([k]) => k).join(",");
          if (active) {
            s = '<svg class="icon icon--10" aria-hidden="true"><use href="#icon-ui-bolt"/></svg> ' + active;
          } else {
            s = "idle";
          }
          break;
        }
        case "context":
          s = payload.intent || payload.summary || "—";
          break;
        case "brain":
          s = (payload.summary || payload.note || "").slice(0, 40);
          break;
        case "tools":
          s = (payload.tools_called && payload.tools_called.length)
            ? payload.tools_called.join(",")
            : "none";
          break;
        case "split":
          s = (payload.segments != null) ? (payload.segments + " 段") : "";
          break;
        case "postprocess":
          s = payload.note || "—";
          break;
        case "output":
          s = payload.text ? ("「" + payload.text.slice(0, 20) + "…」") : "—";
          break;
        default:
          s = JSON.stringify(payload).slice(0, 40);
      }
      return this._escape(s || "");
    } catch (_) {
      return "";
    }
  }

  // ── Decision race ───────────────────────────────
  _renderDecisionRace(payload) {
    const root = document.getElementById("cog-decision-race");
    if (!root) return;
    // Three cases:
    //   A) full decision (scores + layers) → render full race
    //   B) SSE-only chosen (no scores)     → show "chosen: X, awaiting full trace"
    //   C) nothing → empty state
    if (payload && payload.scores) {
      root.innerHTML = this._buildDecisionRaceHtml(payload, payload.chosen);
      return;
    }
    if (payload && payload.chosen) {
      root.innerHTML = this._buildDecisionRaceHtml(
        { scores: { [payload.chosen]: 1.0 }, layers: {}, context_snapshot: {} },
        payload.chosen
      );
      return;
    }
    // Try the last full trace from the modal preview, if any.
    if (this._lastFullTrace && this._lastFullTrace.decision_trace) {
      try {
        root.innerHTML = this._buildDecisionRaceHtml(
          JSON.parse(this._lastFullTrace.decision_trace)
        );
      } catch (_) {
        root.innerHTML = '<div class="cog-timeline-empty">等待决策 / Awaiting decision</div>';
      }
      return;
    }
    root.innerHTML = '<div class="cog-timeline-empty">等待决策 / Awaiting decision</div>';
  }

  _buildDecisionRaceHtml(decisionTrace, overrideChosen) {
    if (!decisionTrace) {
      return '<div class="cog-timeline-empty">无决策数据 / No decision data</div>';
    }
    const chosen = overrideChosen
      || decisionTrace.chosen
      || (decisionTrace.decision_trace && decisionTrace.decision_trace.chosen)
      || null;
    // Normalise: scores may live at top level or under decision_trace.
    const trace = decisionTrace.decision_trace || decisionTrace;
    const scores = trace.scores || {};
    const layers = trace.layers || {};
    const cands = DECISION_CANDIDATES.filter((c) => scores[c] != null);
    // Add any unexpected candidate (e.g. self_evolve) at the end.
    Object.keys(scores).forEach((c) => {
      if (!cands.includes(c)) cands.push(c);
    });
    if (!cands.length) {
      return '<div class="cog-timeline-empty">无决策数据 / No decision data</div>';
    }
    // Sort by score desc.
    cands.sort((a, b) => (scores[b] || 0) - (scores[a] || 0));
    const maxScore = Math.max(...cands.map((c) => scores[c] || 0), 0.0001);

    const rows = cands.map((c) => {
      const score = scores[c] || 0;
      const pct = Math.max(0, Math.min(100, (score / maxScore) * 100));
      const isChosen = c === chosen;
      const layerInfo = layers[c] || {};
      const breakdown = ["L1", "L2", "L3", "L4"]
        .map((k) => k + ":" + (layerInfo[k] != null ? layerInfo[k].toFixed(2) : "—"))
        .join(" · ");
      return (
        '<div class="cog-race-row' + (isChosen ? " cog-race-row--chosen" : "") + '">'
        + '<div class="cog-race-label">'
        + (isChosen ? '<svg class="icon icon--10 cog-race-crown" aria-hidden="true"><use href="#icon-crown"/></svg>' : '<span class="cog-race-crown">·</span>')
        + '<span class="cog-race-name">' + this._escape(DECISION_LABELS_ZH[c] || c) + "</span>"
        + '<span class="cog-race-name-en">' + this._escape(c) + "</span>"
        + "</div>"
        + '<div class="cog-race-bar">'
        + '<div class="cog-race-bar-fill" style="width:' + pct.toFixed(1) + '%"></div>'
        + '<span class="cog-race-score">' + score.toFixed(3) + "</span>"
        + "</div>"
        + '<div class="cog-race-breakdown">' + this._escape(breakdown) + "</div>"
        + "</div>"
      );
    });

    const headerMeta = (() => {
      try {
        const ctx = trace.context_snapshot || trace.context || {};
        const bits = [];
        if (ctx.emotion_label) bits.push("emo:" + ctx.emotion_label);
        if (ctx.route_mode) bits.push("route:" + ctx.route_mode);
        if (ctx.active_eruption) bits.push("erupt:" + ctx.active_eruption);
        return bits.length
          ? '<span class="cog-race-context">' + this._escape(bits.join(" · ")) + "</span>"
          : "";
      } catch (_) { return ""; }
    })();

    return (
      '<div class="cog-race-header">'
      + '<span class="cog-race-title">4-Layer Decision · 权重赛马</span>'
      + headerMeta
      + "</div>"
      + '<div class="cog-race-rows">' + rows.join("") + "</div>"
    );
  }

  // ── History list ────────────────────────────────
  async _loadHistory() {
    const root = document.getElementById("cog-list");
    if (!root) return;
    const source = (document.getElementById("cog-source-filter") || {}).value || "";
    const search = (document.getElementById("cog-search") || {}).value || "";
    const qs = [];
    if (source) qs.push("source=" + encodeURIComponent(source));
    if (search) qs.push("search=" + encodeURIComponent(search));
    qs.push("limit=30");
    const path = "/api/cognition/recent?" + qs.join("&");
    try {
      const r = await window.aerie.api.request({ method: "GET", path });
      const traces = (r.data && r.data.traces) || [];
      if (!traces.length) {
        root.innerHTML = '<li class="cog-list-empty">暂无历史 / No history yet.</li>';
        return;
      }
      // Server-side doesn't currently support search; do a client filter
      // on user_message so the search box is still useful.
      const filtered = search
        ? traces.filter((t) => (t.user_message || "").toLowerCase().includes(search.toLowerCase()))
        : traces;
      if (!filtered.length) {
        root.innerHTML = '<li class="cog-list-empty">无匹配结果 / No match.</li>';
        return;
      }
      root.innerHTML = filtered.map((t) => this._renderHistoryRow(t)).join("");
      root.querySelectorAll("[data-trace-id]").forEach((el) => {
        el.addEventListener("click", () => {
          const id = el.getAttribute("data-trace-id");
          this._openModal(parseInt(id, 10));
        });
      });
    } catch (e) {
      root.innerHTML = '<li class="cog-list-empty">加载失败: ' + this._escape(e.message) + "</li>";
    }
  }

  _renderHistoryRow(t) {
    const ts = this._fmtTime(t.ts);
    const src = this._escape(t.source || "?");
    const route = this._escape(t.route_mode || "AUTO");
    const dur = (t.duration_ms || 0) + "ms";
    const msg = this._truncate(t.user_message || "(empty)", 50);
    const isCmd = t.is_command ? '<span class="cog-row-cmd">cmd</span>' : "";
    return (
      '<li class="cog-row" data-trace-id="' + t.id + '">'
      + '<span class="cog-row-id">#' + t.id + "</span>"
      + '<span class="cog-row-time">' + ts + "</span>"
      + '<span class="cog-row-src cog-row-src--' + src + '">' + src + "</span>"
      + isCmd
      + '<span class="cog-row-route">' + route + "</span>"
      + '<span class="cog-row-msg">' + this._escape(msg) + "</span>"
      + '<span class="cog-row-dur">' + dur + "</span>"
      + "</li>"
    );
  }

  // ── Stats ───────────────────────────────────────
  async _loadStats() {
    try {
      const r = await window.aerie.api.request({ method: "GET", path: "/api/cognition/stats" });
      const d = r.data || {};
      const set = (id, v) => {
        const el = document.getElementById(id);
        if (el) el.textContent = v;
      };
      set("cog-stat-today", d.today != null ? d.today : 0);
      set("cog-stat-total", d.total != null ? d.total : 0);
      set("cog-stat-avg", d.avg_duration_ms != null ? Math.round(d.avg_duration_ms) : 0);
    } catch (_) { /* noop */ }
  }

  // ── Modal ───────────────────────────────────────
  async _openModal(traceId) {
    const modal = document.getElementById("cog-modal");
    const body = document.getElementById("cog-modal-body");
    const title = document.getElementById("cog-modal-title");
    if (!modal || !body) return;
    title.textContent = "Trace #" + traceId + " · 详情";
    body.innerHTML = '<div class="cog-modal-loading">加载中…</div>';
    modal.classList.remove("hidden");
    try {
      const r = await window.aerie.api.request({
        method: "GET", path: "/api/cognition/" + traceId,
      });
      const row = r.data;
      if (!row || row.error) {
        body.innerHTML = '<div class="cog-modal-error">'
          + this._escape((row && row.error) || "未找到 / not found") + "</div>";
        return;
      }
      this._lastFullTrace = row;
      this._renderModalBody(row);
    } catch (e) {
      body.innerHTML = '<div class="cog-modal-error">'
        + this._escape(e.message) + "</div>";
    }
  }

  _closeModal() {
    const modal = document.getElementById("cog-modal");
    if (modal) modal.classList.add("hidden");
  }

  _renderModalBody(row) {
    const body = document.getElementById("cog-modal-body");
    if (!body) return;
    // Build a per-stage list with raw JSON dump.
    const stages = STAGE_ORDER.map((s) => {
      const raw = row["stage_" + s];
      let parsed = null;
      let text = "(empty)";
      if (raw) {
        try {
          parsed = JSON.parse(raw);
          text = JSON.stringify(parsed, null, 2);
        } catch (_) {
          text = raw;
        }
      }
      return (
        '<div class="cog-modal-stage">'
        + '<div class="cog-modal-stage-head">'
        + '<span class="cog-modal-stage-num">' + (STAGE_ORDER.indexOf(s) + 1) + "</span>"
        + '<span class="cog-modal-stage-name">' + STAGE_NAMES_ZH[s]
        + '<span class="cog-modal-stage-en">' + s + "</span></span>"
        + "</div>"
        + '<pre class="cog-modal-stage-json">' + this._escape(text) + "</pre>"
        + "</div>"
      );
    }).join("");

    const decision = (() => {
      try {
        if (!row.decision_trace) return "";
        return this._buildDecisionRaceHtml(JSON.parse(row.decision_trace));
      } catch (_) { return ""; }
    })();
    const react = (() => {
      try {
        if (!row.react_trace) return "";
        return '<div class="cog-modal-react">'
          + '<h4>ReAct Trace</h4>'
          + '<pre class="cog-modal-stage-json">' + this._escape(
            JSON.stringify(JSON.parse(row.react_trace), null, 2)
          ) + "</pre></div>";
      } catch (_) { return ""; }
    })();

    const meta = (
      '<div class="cog-modal-meta">'
      + '<span>id #' + this._escape(String(row.id)) + "</span>"
      + '<span>uid ' + this._escape(String(row.user_id || "—")) + "</span>"
      + '<span>src ' + this._escape(row.source || "—") + "</span>"
      + '<span>route ' + this._escape(row.route_mode || "—") + "</span>"
      + '<span>dur ' + this._escape(String(row.duration_ms || 0)) + "ms</span>"
      + '<span>cmd ' + (row.is_command ? "yes" : "no") + "</span>"
      + "</div>"
    );

    const userMsg = (
      '<div class="cog-modal-usermsg">'
      + '<span class="cog-modal-label">user message</span>'
      + '<pre class="cog-modal-msg">' + this._escape(row.user_message || "(empty)") + "</pre>"
      + "</div>"
    );

    body.innerHTML = (
      meta + userMsg
      + '<h4>9 阶段原始数据 · 9 stages</h4>'
      + '<div class="cog-modal-stages">' + stages + "</div>"
      + (decision
          ? '<h4>决策权重 · Decision</h4><div class="cog-modal-decision">' + decision + '</div>'
          : "")
      + react
    );
  }

  // ── Pulse ───────────────────────────────────────
  _pulse() {
    const dot = document.getElementById("cog-stat-pulse");
    if (!dot) return;
    dot.classList.add("cog-stat-pulse--on");
    clearTimeout(this._pulseTimer);
    this._pulseTimer = setTimeout(() => {
      dot.classList.remove("cog-stat-pulse--on");
    }, 350);
  }

  // ── Helpers ─────────────────────────────────────
  _escape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  _truncate(s, n) {
    if (!s) return "";
    return s.length > n ? (s.slice(0, n - 1) + "…") : s;
  }

  _fmtTime(ms) {
    if (!ms) return "--:--:--";
    const d = new Date(ms);
    const pad = (n) => (n < 10 ? "0" + n : "" + n);
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  // ── v2: Tab 导航 ──────────────────────────────
  _bindV2Tabs() {
    const tabs = document.querySelectorAll(".cog-tab");
    const panes = document.querySelectorAll(".cog-tab-pane");
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        const target = tab.dataset.cogTab;
        tabs.forEach((t) => t.classList.remove("active"));
        panes.forEach((p) => p.classList.remove("active"));
        tab.classList.add("active");
        const pane = document.getElementById("cog-pane-" + target);
        if (pane) pane.classList.add("active");
      });
    });
  }

  // ── v2: 刷新按钮绑定 ──────────────────────────
  _bindV2Refresh() {
    const refreshMap = {
      "cog-se-refresh": () => this._loadSelfEvolveData(),
      "cog-cc-refresh": () => this._loadComputerControlData(),
      "cog-fo-refresh": () => this._loadFileOrganizerData(),
      "cog-dw-refresh": () => this._loadDocWriterData(),
    };
    Object.entries(refreshMap).forEach(([id, fn]) => {
      const btn = document.getElementById(id);
      if (btn) btn.addEventListener("click", fn.bind(this));
    });
  }

  // ── v2: 加载演示数据 ──────────────────────────
  _loadV2DemoData() {
    this._loadSelfEvolveData();
    this._loadComputerControlData();
    this._loadFileOrganizerData();
    this._loadDocWriterData();
  }

  _loadSelfEvolveData() {
    const totalEl = document.getElementById("cog-se-total");
    const appliedEl = document.getElementById("cog-se-applied");
    const rolledEl = document.getElementById("cog-se-rolled");
    const listEl = document.getElementById("cog-se-list");
    const journalEl = document.getElementById("cog-se-journal");
    const gatesEl = document.getElementById("cog-se-gates");
    if (!totalEl || !listEl) return;

    Promise.all([
      window.aerie.api.request({ method: "GET", path: "/api/self_evolve/stats" }).catch(() => null),
      window.aerie.api.request({ method: "GET", path: "/api/self_evolve/list?limit=20" }).catch(() => null),
    ]).then(([statsRes, listRes]) => {
      const stats = (statsRes && statsRes.data) || {};
      const items = (listRes && listRes.data && listRes.data.items) || [];

      totalEl.textContent = stats.total != null ? stats.total : 0;
      appliedEl.textContent = stats.approved != null ? stats.approved : 0;
      rolledEl.textContent = stats.rolled_back != null ? stats.rolled_back : 0;

      if (!items.length) {
        listEl.innerHTML = '<div class="cog-list-empty">暂无自我进化提案</div>';
      } else {
        const badgeMap = {
          pending: { cls: "pending", text: "待决定" },
          approved: { cls: "applied", text: "已应用" },
          rejected: { cls: "rejected", text: "已拒绝" },
          rolled_back: { cls: "rolled", text: "已回滚" },
        };
        listEl.innerHTML = items.slice(0, 5).map((p) => {
          const schema = p.proposed_tool_schema || {};
          const toolName = schema.name || "unnamed_tool";
          const badge = badgeMap[p.user_decision] || badgeMap.pending;
          const ts = p.ts ? new Date(p.ts).toLocaleString() : "";
          return `
            <div class="cog-se-item">
              <span class="cog-se-item-icon"><svg class="icon icon--18" style="color: var(--color-primary, #ff7eb6);"><use href="#icon-ui-dna"/></svg></span>
              <div class="cog-se-item-body">
                <div class="cog-se-item-title">${this._escape(p.description || toolName)}</div>
                <div class="cog-se-item-meta">${this._escape(ts)} · ${this._escape(toolName)}</div>
              </div>
              <span class="cog-se-item-badge cog-se-item-badge--${badge.cls}">${badge.text}</span>
            </div>
          `;
        }).join("");
      }

      if (journalEl && items.length) {
        const first = items[0];
        const ts = first.ts ? new Date(first.ts).toLocaleTimeString() : "";
        journalEl.innerHTML = `
          <div class="cog-cc-item">
            <span class="cog-cc-time">${ts}</span>
            <span class="cog-cc-type cog-cc-type--shell">提案创建</span>
            <span class="cog-cc-desc">${this._escape(first.description || "")}</span>
          </div>
        `;
      }
    });
  }

  _loadComputerControlData() {
    const levelEl = document.getElementById("cog-cc-level");
    const todayEl = document.getElementById("cog-cc-today");
    const blockedEl = document.getElementById("cog-cc-blocked");
    const logEl = document.getElementById("cog-cc-log");
    if (!levelEl || !logEl) return;

    this._bindCCLevelButtons();

    Promise.all([
      window.aerie.api.request({ method: "GET", path: "/api/computer_control/stats" }).catch(() => null),
      window.aerie.api.request({ method: "GET", path: "/api/computer_control/logs?limit=20" }).catch(() => null),
    ]).then(([statsRes, logsRes]) => {
      const stats = (statsRes && statsRes.data) || {};
      const logs = (logsRes && logsRes.data && logsRes.data.logs) || [];

      const level = stats.permission_level || "view_only";
      levelEl.textContent = level.toUpperCase();
      todayEl.textContent = stats.today_operations != null ? stats.today_operations : 0;
      blockedEl.textContent = stats.blocked_operations != null ? stats.blocked_operations : 0;

      this._updateCCLevelUI(level);

      if (!logs.length) {
        logEl.innerHTML = '<div class="cog-list-empty">暂无操作记录</div>';
      } else {
        const typeMap = {
          screenshot: { label: "截图", cls: "screenshot" },
          mouse_move: { label: "鼠标", cls: "mouse" },
          mouse_click: { label: "点击", cls: "mouse" },
          key_press: { label: "按键", cls: "keyboard" },
          key_type: { label: "输入", cls: "keyboard" },
          shell_cmd: { label: "命令", cls: "shell" },
          window_info: { label: "窗口", cls: "screenshot" },
          uia_action: { label: "UIA", cls: "shell" },
        };
        logEl.innerHTML = logs.map((l) => {
          const t = typeMap[l.action] || { label: l.action || "?", cls: "shell" };
          const status = l.status || "success";
          const time = l.ts ? new Date(l.ts).toLocaleTimeString() : "";
          const desc = l.details ? (typeof l.details === "string" ? l.details : JSON.stringify(l.details)) : "";
          const isBlocked = status === "blocked";
          return `
            <div class="cog-cc-item">
              <span class="cog-cc-time">${time}</span>
              <span class="cog-cc-type cog-cc-type--${isBlocked ? "blocked" : t.cls}">${isBlocked ? "拦截" : t.label}</span>
              <span class="cog-cc-desc">${this._escape(desc.slice(0, 60))}</span>
            </div>
          `;
        }).join("");
      }
    });
  }

  _bindCCLevelButtons() {
    if (this._ccLevelBound) return;
    this._ccLevelBound = true;
    const levels = document.querySelectorAll(".cog-cc-level");
    levels.forEach((el) => {
      el.addEventListener("click", () => {
        const level = el.dataset.level;
        if (!level) return;
        this._updateCCLevelUI(level);
        this._setCCLevel(level.toLowerCase());
      });
    });
  }

  _updateCCLevelUI(level) {
    const levels = document.querySelectorAll(".cog-cc-level");
    const levelUp = level.toUpperCase();
    levels.forEach((el) => {
      if (el.dataset.level === levelUp) {
        el.classList.add("active");
      } else {
        el.classList.remove("active");
      }
    });
    const levelEl = document.getElementById("cog-cc-level");
    if (levelEl) levelEl.textContent = levelUp;
  }

  async _setCCLevel(level) {
    try {
      const r = await window.aerie.api.request({
        method: "PUT",
        path: "/api/computer_control/level",
        body: { level },
      });
      if (r.data && r.data.status === "ok") {
        this._updateCCLevelUI(r.data.level || level);
      }
    } catch (e) {
      console.warn("[cog-panel] set cc level failed", e);
    }
  }

  _loadFileOrganizerData() {
    const organizedEl = document.getElementById("cog-fo-organized");
    const undoableEl = document.getElementById("cog-fo-undoable");
    const savedEl = document.getElementById("cog-fo-saved");
    const historyEl = document.getElementById("cog-fo-history");
    const undoEl = document.getElementById("cog-fo-undo");
    if (!organizedEl || !historyEl) return;

    Promise.all([
      window.aerie.api.request({ method: "GET", path: "/api/file_organizer/stats" }).catch(() => null),
      window.aerie.api.request({ method: "GET", path: "/api/file_organizer/history?limit=20" }).catch(() => null),
      window.aerie.api.request({ method: "GET", path: "/api/file_organizer/undo_list?limit=10" }).catch(() => null),
    ]).then(([statsRes, historyRes, undoRes]) => {
      const stats = (statsRes && statsRes.data) || {};
      const history = (historyRes && historyRes.data && historyRes.data.records) || [];
      const undos = (undoRes && undoRes.data && undoRes.data.records) || [];

      organizedEl.textContent = stats.total_organized != null ? stats.total_organized : 0;
      undoableEl.textContent = stats.undoable != null ? stats.undoable : 0;
      const savedMB = stats.saved_space_bytes ? (stats.saved_space_bytes / 1024 / 1024).toFixed(1) + " MB" : "0 MB";
      savedEl.textContent = savedMB;

      if (!history.length) {
        historyEl.innerHTML = '<div class="cog-list-empty">暂无整理记录</div>';
      } else {
        historyEl.innerHTML = history.slice(0, 5).map((h) => {
          const ts = h.ts ? new Date(h.ts).toLocaleString() : "";
          const fileCount = h.file_count || 0;
          const title = h.description || h.undo_id || "文件整理";
          const icon = h.category === "images" ? '<svg class="icon icon--18" style="color: #ec4899;"><use href="#icon-ui-image"/></svg>' : h.category === "documents" ? '<svg class="icon icon--18" style="color: #3b82f6;"><use href="#icon-ui-file-text"/></svg>' : '<svg class="icon icon--18" style="color: #f59e0b;"><use href="#icon-ui-package"/></svg>';
          return `
            <div class="cog-fo-item">
              <span class="cog-fo-item-icon">${icon}</span>
              <div class="cog-fo-item-body">
                <div class="cog-fo-item-title">${this._escape(title)}</div>
                <div class="cog-fo-item-meta">${this._escape(ts)} · ${fileCount} 个文件</div>
              </div>
              <span class="cog-fo-item-count">${fileCount}</span>
            </div>
          `;
        }).join("");
      }

      if (undoEl) {
        if (!undos.length) {
          undoEl.innerHTML = '<div class="cog-list-empty">暂无可撤销操作</div>';
        } else {
          undoEl.innerHTML = undos.map((u) => {
            const ts = u.ts ? new Date(u.ts).toLocaleString() : "";
            const title = u.description || u.undo_id || "文件整理";
            return `
              <div class="cog-fo-item">
                <span class="cog-fo-item-icon">↩️</span>
                <div class="cog-fo-item-body">
                  <div class="cog-fo-item-title">${this._escape(title)}</div>
                  <div class="cog-fo-item-meta">${this._escape(ts)}</div>
                </div>
              </div>
            `;
          }).join("");
        }
      }
    });
  }

  _loadDocWriterData() {
    const countEl = document.getElementById("cog-dw-count");
    const listEl = document.getElementById("cog-dw-list");
    if (!countEl || !listEl) return;

    Promise.all([
      window.aerie.api.request({ method: "GET", path: "/api/doc_writer/stats" }).catch(() => null),
      window.aerie.api.request({ method: "GET", path: "/api/doc_writer/list?limit=20" }).catch(() => null),
    ]).then(([statsRes, listRes]) => {
      const stats = (statsRes && statsRes.data) || {};
      const docs = (listRes && listRes.data && listRes.data.documents) || [];

      countEl.textContent = stats.total_documents != null ? stats.total_documents : 0;

      if (!docs.length) {
        listEl.innerHTML = '<div class="cog-list-empty">暂无文档</div>';
      } else {
        const iconMap = {
          MD: '<svg class="icon icon--18" style="color: #f59e0b;"><use href="#icon-ui-book"/></svg>',
          PDF: '<svg class="icon icon--18" style="color: #ef4444;"><use href="#icon-ui-book-open"/></svg>',
          HTML: '<svg class="icon icon--18" style="color: #0ea5e9;"><use href="#icon-ui-globe"/></svg>',
          DOCX: '<svg class="icon icon--18" style="color: #2563eb;"><use href="#icon-ui-book-blue"/></svg>',
          TXT: '<svg class="icon icon--18" style="color: #64748b;"><use href="#icon-ui-file-text"/></svg>',
        };
        listEl.innerHTML = docs.slice(0, 5).map((d) => {
          const fmt = d.format || "MD";
          const icon = iconMap[fmt] || '<svg class="icon icon--18" style="color: #64748b;"><use href="#icon-ui-file-text"/></svg>';
          const modified = d.modified ? new Date(d.modified * 1000).toLocaleDateString() : "";
          const title = d.name || "未命名文档";
          return `
            <div class="cog-dw-item">
              <span class="cog-dw-item-icon">${icon}</span>
              <div class="cog-dw-item-body">
                <div class="cog-dw-item-title">${this._escape(title)}</div>
                <div class="cog-dw-item-meta">${this._escape(modified)}</div>
              </div>
              <span class="cog-dw-item-format">${fmt}</span>
            </div>
          `;
        }).join("");
      }
    });
  }

  // ── QQ Whitelist (v13.9) ────────────────────────
  _bindQQWhitelist() {
    const addBtn = document.getElementById("qq-wl-add-btn");
    if (addBtn) {
      addBtn.addEventListener("click", () => this._addQQWhitelist());
    }
    const numberInput = document.getElementById("qq-wl-add-number");
    if (numberInput) {
      numberInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter") this._addQQWhitelist();
      });
    }
    const enabledSwitch = document.getElementById("qq-wl-enabled");
    if (enabledSwitch) {
      enabledSwitch.addEventListener("change", (e) => this._toggleQQWhitelistEnabled(e.target.checked));
    }
    const refreshBtn = document.getElementById("qq-wl-refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", () => this._loadQQWhitelist());
    }
    const clearBtn = document.getElementById("qq-wl-clear-btn");
    if (clearBtn) {
      clearBtn.addEventListener("click", () => this._clearQQWhitelist());
    }
    const bulkBtn = document.getElementById("qq-wl-bulk-btn");
    if (bulkBtn) {
      bulkBtn.addEventListener("click", () => this._bulkAddQQWhitelist());
    }
  }

  _loadQQWhitelist() {
    window.aerie.api.request({ method: "GET", path: "/api/qq/whitelist" }).then((res) => {
      if (!res || !res.data) return;
      const { items, stats } = res.data;

      const totalEl = document.getElementById("qq-wl-total");
      const activeEl = document.getElementById("qq-wl-active");
      const modeEl = document.getElementById("qq-wl-mode");
      const enabledEl = document.getElementById("qq-wl-enabled");
      const listEl = document.getElementById("qq-wl-list");

      if (totalEl) totalEl.textContent = stats.total || 0;
      if (activeEl) activeEl.textContent = stats.active || 0;
      if (modeEl) modeEl.textContent = stats.mode === "strict" ? "严格" : "兼容";
      if (enabledEl) enabledEl.checked = !!stats.enabled;

      if (!listEl) return;
      if (!items || !items.length) {
        listEl.innerHTML = '<div class="cog-timeline-empty">暂无白名单用户，添加后会显示在这里</div>';
        return;
      }

      listEl.innerHTML = items.map((item) => {
        const qq = item.qq_number || "";
        const remark = item.remark || "";
        const enabled = item.enabled === 1 || item.enabled === true;
        const lastMsg = item.last_message_at || "暂无消息";
        const avatar = remark ? remark.charAt(0).toUpperCase() : (qq.toString().slice(-1));
        return `
          <div class="qq-wl-item ${enabled ? "" : "disabled"}" data-qq="${qq}">
            <div class="qq-wl-item-avatar">${this._escape(avatar)}</div>
            <div class="qq-wl-item-info">
              <div class="qq-wl-item-number">${this._escape(qq)}</div>
              <div class="qq-wl-item-remark">${this._escape(remark || "未设置备注")}</div>
              <div class="qq-wl-item-meta">最后消息：${this._escape(lastMsg)}</div>
            </div>
            <div class="qq-wl-status-dot ${enabled ? "" : "off"}" title="${enabled ? "已启用" : "已禁用"}"></div>
            <div class="qq-wl-item-actions">
              <button class="qq-wl-item-btn" data-action="toggle" data-qq="${qq}">${enabled ? "禁用" : "启用"}</button>
              <button class="qq-wl-item-btn danger" data-action="delete" data-qq="${qq}">删除</button>
            </div>
          </div>
        `;
      }).join("");

      // Bind item actions
      listEl.querySelectorAll(".qq-wl-item-btn").forEach((btn) => {
        btn.addEventListener("click", (e) => {
          const action = e.currentTarget.getAttribute("data-action");
          const qq = e.currentTarget.getAttribute("data-qq");
          if (action === "toggle") {
            this._toggleQQWhitelistItem(qq);
          } else if (action === "delete") {
            this._removeQQWhitelistItem(qq);
          }
        });
      });
    }).catch(() => null);
  }

  _addQQWhitelist() {
    const numberInput = document.getElementById("qq-wl-add-number");
    const remarkInput = document.getElementById("qq-wl-add-remark");
    const qqNumber = numberInput ? numberInput.value.trim() : "";
    const remark = remarkInput ? remarkInput.value.trim() : "";

    if (!qqNumber || !/^\d+$/.test(qqNumber)) {
      alert("请输入有效的 QQ 号");
      return;
    }

    window.aerie.api.request({
      method: "POST",
      path: "/api/qq/whitelist",
      body: { qq_number: qqNumber, remark },
    }).then(() => {
      if (numberInput) numberInput.value = "";
      if (remarkInput) remarkInput.value = "";
      this._loadQQWhitelist();
    }).catch((e) => {
      alert("添加失败：" + (e.message || e));
    });
  }

  _removeQQWhitelistItem(qq) {
    if (!confirm(`确定要从白名单中移除 ${qq} 吗？`)) return;
    window.aerie.api.request({
      method: "DELETE",
      path: `/api/qq/whitelist/${qq}`,
    }).then(() => {
      this._loadQQWhitelist();
    }).catch((e) => {
      alert("删除失败：" + (e.message || e));
    });
  }

  _toggleQQWhitelistItem(qq) {
    const item = document.querySelector(`.qq-wl-item[data-qq="${qq}"]`);
    const isEnabled = item ? !item.classList.contains("disabled") : true;
    window.aerie.api.request({
      method: "PUT",
      path: `/api/qq/whitelist/${qq}/toggle`,
      body: { enabled: !isEnabled },
    }).then(() => {
      this._loadQQWhitelist();
    }).catch((e) => {
      alert("操作失败：" + (e.message || e));
    });
  }

  _toggleQQWhitelistEnabled(enabled) {
    window.aerie.api.request({
      method: "PUT",
      path: "/api/qq/whitelist/enabled",
      body: { enabled },
    }).then(() => {
      this._loadQQWhitelist();
    }).catch((e) => {
      alert("操作失败：" + (e.message || e));
    });
  }

  _clearQQWhitelist() {
    if (!confirm("确定要清空所有白名单吗？清空后将恢复兼容模式（全部放行）。")) return;
    window.aerie.api.request({
      method: "DELETE",
      path: "/api/qq/whitelist",
    }).then(() => {
      this._loadQQWhitelist();
    }).catch((e) => {
      alert("清空失败：" + (e.message || e));
    });
  }

  _bulkAddQQWhitelist() {
    const input = prompt("批量添加白名单，每行一个 QQ 号，可带备注（QQ号 备注，空格分隔）：", "");
    if (!input) return;
    const lines = input.split("\n").map((l) => l.trim()).filter((l) => l);
    const qqNumbers = [];
    lines.forEach((line) => {
      const parts = line.split(/\s+/);
      if (parts[0] && /^\d+$/.test(parts[0])) {
        qqNumbers.push(parts[0]);
      }
    });
    if (!qqNumbers.length) {
      alert("未识别到有效的 QQ 号");
      return;
    }
    window.aerie.api.request({
      method: "POST",
      path: "/api/qq/whitelist/bulk",
      body: { qq_numbers: qqNumbers },
    }).then((res) => {
      const data = (res && res.data) || {};
      alert(`批量添加完成：成功 ${data.added_count || 0} / ${data.total || 0}`);
      this._loadQQWhitelist();
    }).catch((e) => {
      alert("批量添加失败：" + (e.message || e));
    });
  }
}

window.CognitionPanel = CognitionPanel;
window.cognitionPanel = new CognitionPanel();
