"use strict";

/**
 * Panels renderer - relationship / memory / growth panels.
 *
 * Security rules (mirrors chat.js):
 *   - All user-controlled text goes through _escapeHtml (DOM textContent round-trip).
 *   - Any text that may contain filesystem paths or credentials (e.g. memory
 *     content, source-derived strings) additionally goes through _redactSensitive
 *     so that local paths / tokens / secrets are never rendered.
 *   - Model-internal scores are NEVER shown as raw floats; they are mapped to
 *     short Chinese tier labels.
 */
class PanelManager {
  constructor(options) {
    this.options = options || {};
    this._onDeleteMemory = typeof this.options.onDeleteMemory === "function"
      ? this.options.onDeleteMemory
      : null;
    this._bindRootHandlers();
  }

  // ---- public render methods ------------------------------------------------

  renderRelationshipPanel(state) {
    const s = state || {};
    const stageLabel = this._relationshipStageLabel(s.relationship_stage);
    const famTier = this._scoreTier(s.familiarity);
    const trustTier = this._scoreTier(s.trust);
    const affTier = this._scoreTier(s.affection, true); // positive axis
    const grudgeTier = this._scoreTier(s.grudge, false, true); // negative axis
    const emo = s.immediate_emotion || {};
    const emoLabel = this._escapeHtml(emo.label || "平静");
    const delta = s.today_delta || {};
    const deltaFmt = this._formatDelta(delta);

    return `<section class="panel panel--relationship" data-panel-type="relationship">
  <header class="panel__header"><h3 class="panel__title">关系</h3><span class="panel__stage">${this._escapeHtml(stageLabel)}</span></header>
  <ul class="panel__metrics">
    <li class="panel__metric"><span class="panel__metric-label">熟悉度</span><span class="panel__metric-value">${this._escapeHtml(famTier)}</span></li>
    <li class="panel__metric"><span class="panel__metric-label">信任感</span><span class="panel__metric-value">${this._escapeHtml(trustTier)}</span></li>
    <li class="panel__metric"><span class="panel__metric-label">好感度</span><span class="panel__metric-value">${this._escapeHtml(affTier)}</span></li>
    <li class="panel__metric"><span class="panel__metric-label">芥蒂感</span><span class="panel__metric-value">${this._escapeHtml(grudgeTier)}</span></li>
    <li class="panel__metric"><span class="panel__metric-label">即时情绪</span><span class="panel__metric-value">${emoLabel}</span></li>
    <li class="panel__metric"><span class="panel__metric-label">今日变化</span><span class="panel__metric-value">${this._escapeHtml(deltaFmt)}</span></li>
  </ul>
</section>`;
  }

  renderMemoryPanel(state) {
    const s = state || {};
    const memories = Array.isArray(s.memories) ? s.memories : [];
    let body;
    if (memories.length === 0) {
      body = `<div class="panel__empty" data-panel-empty="memory">还没有记忆，多聊几句会慢慢记住关于你的事。</div>`;
    } else {
      const items = memories.map((m) => this._renderMemoryItem(m)).join("");
      body = `<ul class="panel__list" data-panel-list="memory">${items}</ul>`;
    }
    return `<section class="panel panel--memory" data-panel-type="memory">
  <header class="panel__header"><h3 class="panel__title">记忆</h3><span class="panel__count">${this._escapeHtml(String(memories.length))}</span></header>
  ${body}
</section>`;
  }

  renderGrowthPanel(state) {
    const s = state || {};
    const events = Array.isArray(s.events) ? s.events.slice() : [];
    // Reverse chronological.
    events.sort((a, b) => (b.ts || b.created_at || 0) - (a.ts || a.created_at || 0));
    let body;
    if (events.length === 0) {
      body = `<div class="panel__empty" data-panel-empty="growth">成长轨迹暂时为空，经历新的时刻会在这里留下记录。</div>`;
    } else {
      const items = events.map((e) => this._renderGrowthItem(e)).join("");
      body = `<ol class="panel__timeline" data-panel-list="growth">${items}</ol>`;
    }
    return `<section class="panel panel--growth" data-panel-type="growth">
  <header class="panel__header"><h3 class="panel__title">成长</h3><span class="panel__count">${this._escapeHtml(String(events.length))}</span></header>
  ${body}
</section>`;
  }

  // ---- event wiring (safe: uses event delegation on the document body) ----

  _bindRootHandlers() {
    if (this._handlersBound) return;
    if (typeof document === "undefined" || typeof document.addEventListener !== "function") {
      this._handlersBound = true;
      return;
    }
    document.addEventListener("click", (ev) => {
      const target = ev.target;
      if (!target || typeof target.getAttribute !== "function") return;
      const delId = target.getAttribute("data-memory-delete");
      if (delId && this._onDeleteMemory) {
        ev.preventDefault();
        this._onDeleteMemory(delId);
      }
    });
    this._handlersBound = true;
  }

  /**
   * Programmatically invoke the delete callback. Exposed so tests (and
   * host code that does not have a real DOM) can trigger the same path
   * the click handler would.
   */
  _handleDeleteMemory(id) {
    if (this._onDeleteMemory) this._onDeleteMemory(id);
  }

  // ---- per-item renderers ---------------------------------------------------

  _renderMemoryItem(m) {
    const id = m.id || m.memory_id || "";
    const rawContent = m.content || m.summary || "";
    // Redact paths/secrets BEFORE escaping so that placeholders remain visible.
    const safeContent = this._escapeHtml(this._redactSensitive(rawContent));
    const confidence = this._formatConfidence(m.confidence);
    const source = this._formatSourceId(m.source_message_id);
    const confirmed = m.user_confirmed
      ? '<span class="panel__tag panel__tag--confirmed">已确认</span>'
      : '<span class="panel__tag panel__tag--tentative">待确认</span>';
    const deleteBtn = id
      ? `<button type="button" class="panel__delete" data-memory-delete="${this._escapeHtml(id)}" title="删除此记忆">删除</button>`
      : "";
    return `<li class="panel__item panel__item--memory" data-memory-id="${this._escapeHtml(id)}">
  <p class="panel__memory-content">${safeContent}</p>
  <div class="panel__memory-meta">
    <span class="panel__memory-confidence" title="置信度">${this._escapeHtml(confidence)}</span>
    <span class="panel__memory-source" title="来源">${this._escapeHtml(source)}</span>
    ${confirmed}
    ${deleteBtn}
  </div>
</li>`;
  }

  _renderGrowthItem(e) {
    const id = e.id || "";
    const typeLabel = this._growthTypeLabel(e.type);
    const desc = this._escapeHtml(this._redactSensitive(e.description || ""));
    const when = this._formatTime(e.ts || e.created_at);
    return `<li class="panel__item panel__item--growth" data-growth-id="${this._escapeHtml(id)}">
  <span class="panel__growth-type">${this._escapeHtml(typeLabel)}</span>
  <span class="panel__growth-when">${this._escapeHtml(when)}</span>
  <p class="panel__growth-desc">${desc}</p>
</li>`;
  }

  // ---- mapping helpers ------------------------------------------------------

  _relationshipStageLabel(stage) {
    switch (String(stage || "stranger").toLowerCase()) {
      case "beloved": return "挚爱";
      case "close": return "亲密";
      case "familiar": return "熟悉";
      case "acquaintance": return "认识";
      case "stranger":
      default:
        return "陌生人";
    }
  }

  /**
   * Map a 0..1 score onto a short Chinese tier. `positive=true` means higher
   * is warmer (familiarity/affection/trust); `negative=true` means higher is
   * colder (grudge). Never expose the raw float.
   */
  _scoreTier(value, positive, negative) {
    const n = Number(value);
    if (!Number.isFinite(n)) return "未知";
    if (negative) {
      if (n >= 0.6) return "很深";
      if (n >= 0.35) return "在意";
      if (n >= 0.15) return "轻微";
      return "无";
    }
    if (positive !== false) {
      if (n >= 0.85) return "亲密";
      if (n >= 0.65) return "很熟";
      if (n >= 0.4) return "熟悉";
      if (n >= 0.15) return "认识";
      return "陌生";
    }
    // generic (shouldn't reach here)
    if (n >= 0.75) return "高";
    if (n >= 0.4) return "中";
    return "低";
  }

  _formatDelta(delta) {
    if (!delta || typeof delta !== "object") return "—";
    const parts = [];
    const labels = {
      familiarity: "熟悉", trust: "信任", affection: "好感", grudge: "芥蒂",
    };
    for (const key of Object.keys(labels)) {
      const v = Number(delta[key]);
      if (!Number.isFinite(v) || v === 0) continue;
      const sign = v > 0 ? "+" : "";
      parts.push(`${labels[key]}${sign}${Math.round(v * 100)}%`);
    }
    return parts.length ? parts.join(" / ") : "—";
  }

  _formatConfidence(c) {
    const n = Number(c);
    if (!Number.isFinite(n)) return "—";
    const pct = Math.max(0, Math.min(100, Math.round(n * 100)));
    return `${pct}%`;
  }

  _formatSourceId(src) {
    if (!src) return "来源：—";
    const s = String(src);
    // Never expose the full source id; show a short stable prefix+suffix.
    if (s.length <= 8) return `来源：${s}`;
    return `来源：${s.slice(0, 4)}…${s.slice(-4)}`;
  }

  _growthTypeLabel(type) {
    switch (String(type || "").toLowerCase()) {
      case "milestone": return "里程碑";
      case "bond": return "联结";
      case "reflection": return "反思";
      case "conflict": return "冲突";
      case "reconciliation": return "和解";
      case "first_meeting": return "初遇";
      default: return "事件";
    }
  }

  _formatTime(ts) {
    if (ts === null || ts === undefined || ts === "") return "";
    let d;
    try {
      d = typeof ts === "number"
        ? new Date(ts < 1e12 ? ts * 1000 : ts)
        : new Date(ts);
    } catch (_) {
      return "";
    }
    if (isNaN(d.getTime())) return "";
    const y = d.getFullYear();
    const mo = String(d.getMonth() + 1).padStart(2, "0");
    const da = String(d.getDate()).padStart(2, "0");
    const hh = String(d.getHours()).padStart(2, "0");
    const mm = String(d.getMinutes()).padStart(2, "0");
    return `${y}-${mo}-${da} ${hh}:${mm}`;
  }

  // ---- security helpers (mirror chat.js) -----------------------------------

  _redactSensitive(text) {
    let s = String(text || "");
    s = s.replace(/[A-Za-z]:\\[^\s"'<>]*/g, "<path>");
    s = s.replace(/\/(?:home|Users|root|var|opt|tmp)\/[^\s"'<>]*/g, "<path>");
    s = s.replace(/(?:api[_-]?key|token|secret|bearer|ghp_)[^\s"'<>]*/gi, "<redacted>");
    return s;
  }

  _escapeHtml(text) {
    if (typeof document !== "undefined" && document.createElement) {
      const d = document.createElement("div");
      d.textContent = text;
      return d.innerHTML.replace(/\n/g, "<br>");
    }
    // Server/test fallback (no DOM): minimal entity escape.
    return String(text ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;")
      .replace(/\n/g, "<br>");
  }
}

if (typeof window !== "undefined") {
  window.PanelManager = PanelManager;
}
