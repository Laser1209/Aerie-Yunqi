"use strict";
/* Emotion History — Phase 9 Batch 5
 *
 * Three self-drawn SVG charts:
 *   1) PAD line chart  (3 polylines, P/A/D, -1..1)
 *   2) Threshold area chart (4 stacked series, 0..100 %)
 *   3) Radar heatmap (label × time-bucket, color-coded by frequency)
 *
 * Window selector: 1h / 24h / 7d / 30d. The backend already filters by
 * the time window and may downsample for 7d/30d. When fewer than 2
 * points are present, the chart shows an explicit empty state instead
 * of a degenerate polyline.
 *
 * All rendering is hand-rolled SVG so the panel works without
 * internet access (Phase 7 rule: no CDN libs).
 */

const WINDOWS = ["1h", "24h", "7d", "30d"];

const PAD_LABELS = [
  { key: "pleasure",  zh: "愉悦度 P", color: "#ff5b9c" },
  { key: "arousal",   zh: "唤醒度 A", color: "#7e6bff" },
  { key: "dominance", zh: "支配度 D", color: "#3acfd5" },
];

const THRESHOLD_SLOTS = [
  { key: "patience_value",   zh: "忍耐",   color: "#ff5b9c" },
  { key: "anxiety_value",    zh: "不安",   color: "#ffb74d" },
  { key: "desire_value",     zh: "渴望",   color: "#7e6bff" },
  { key: "tenderness_value", zh: "温柔",   color: "#3acfd5" },
];

const LABEL_KEYS = ["joy", "sad", "anger", "fear", "neutral", "missing", "curiosity", "love", "affection"];

class EmotionHistory {
  constructor() {
    // R7.0: default window is now 24h instead of 1h. The 1h window
    // almost never has ≥2 points (snapshots fire only on user_msg,
    // not on a timer), so the chart would perpetually show
    // "数据不足 / need at least 2 points" — a bad first impression
    // for a fresh user. 24h covers a full day of typical usage.
    this._window = "24h";
    this._data = null;
    this._timer = null;
    this._visible = false;
    this._initialized = false;
    this._requestInFlight = false;
    this._latestState = null;
  }

  init() {
    if (this._initialized) return;
    this._initialized = true;
    this._bindToolbar();
    this._renderError("等待数据 / waiting for samples");
    if (this._visible) this._startPolling();
  }

  destroy() {
    if (this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
    if (this._pendingRefresh) clearTimeout(this._pendingRefresh);
    this._pendingRefresh = null;
    this._initialized = false;
  }

  setVisible(v) {
    const visible = Boolean(v);
    if (this._visible === visible) return;
    this._visible = visible;
    if (visible && this._initialized) this._startPolling();
    if (!visible && this._timer) {
      clearInterval(this._timer);
      this._timer = null;
    }
  }

  _startPolling() {
    if (this._timer) clearInterval(this._timer);
    this._timer = setInterval(() => this.refresh(), 15000);
    this.refresh(true);
  }

  onStateUpdate(data) {
    this._latestState = data || null;
    if (this._visible && this._data) {
      this._data.items = this._mergeLivePoint(this._data.items || []);
      if (data && data.serverNow) this._data.serverNow = data.serverNow;
      this._renderAll();
    }
    // Hook for EmotionDashboard to push fresh state. The dashboard
    // already handles its own redraw, so here we just optionally
    // schedule a small follow-up refresh so the chart's right edge
    // catches the new sample within ~3s.
    if (!this._visible) return;
    clearTimeout(this._pendingRefresh);
    this._pendingRefresh = setTimeout(() => this.refresh(), 3000);
  }

  refresh(force) {
    if ((!this._visible && !force) || this._requestInFlight) return;
    this._requestInFlight = true;
    this._fetch().then((data) => {
      this._data = data;
      this._renderAll();
    }).catch(() => {
      this._renderError("加载失败 / load failed");
      this._setUpdatedStatus("连接中断", true);
    }).finally(() => {
      this._requestInFlight = false;
    });
  }

  async _fetch() {
    const r = await window.aerie.api.request({
      method: "GET",
      path: "/api/emotion/history?window=" + encodeURIComponent(this._window),
    });
    if (!r || (Number.isInteger(r.status) && (r.status < 200 || r.status >= 300))
        || !r.data || r.data.error) {
      throw new Error(r.data && r.data.error || "no data");
    }
    const data = { ...r.data };
    data.items = this._mergeLivePoint(Array.isArray(data.items) ? data.items : []);
    return data;
  }

  // ── Toolbar ─────────────────────────────────────
  _bindToolbar() {
    document.querySelectorAll(".emh-window").forEach((btn) => {
      btn.classList.toggle("active", btn.getAttribute("data-window") === this._window);
      btn.addEventListener("click", () => {
        const w = btn.getAttribute("data-window");
        if (!w || !WINDOWS.includes(w)) return;
        this._window = w;
        document.querySelectorAll(".emh-window").forEach((b) => {
          b.classList.toggle("active", b === btn);
        });
        this.refresh(true);
      });
    });
    const refresh = document.getElementById("emh-refresh");
    if (refresh) refresh.addEventListener("click", () => this.refresh(true));
  }

  // ── Render dispatch ─────────────────────────────
  _renderAll() {
    this._renderPad();
    this._renderThresholds();
    this._renderRadar();
    const data = this._data || {};
    const latest = data.sampledAt || data.latestPersistedAt
      || (data.items && data.items.length && data.items[data.items.length - 1].ts);
    const text = latest ? "更新于 " + this._fmtClock(latest) : "等待数据";
    this._setUpdatedStatus(text, Boolean(data.stale));
  }

  _renderError(msg) {
    const set = (id) => {
      const el = document.getElementById(id);
      if (el) el.innerHTML = '<div class="emh-empty">' + this._escape(msg) + "</div>";
    };
    set("emh-pad-chart");
    set("emh-threshold-chart");
    set("emh-radar-chart");
  }

  // ── PAD line chart ──────────────────────────────
  _renderPad() {
    const root = document.getElementById("emh-pad-chart");
    if (!root) return;
    const items = (this._data && this._data.items) || [];
    if (items.length < 2) {
      root.innerHTML = '<div class="emh-empty">数据不足 / need at least 2 points</div>';
      return;
    }
    const W = root.clientWidth || 560;
    const H = 180;
    const padL = 32, padR = 12, padT = 14, padB = 22;
    const innerW = W - padL - padR;
    const innerH = H - padT - padB;
    const { t0, t1 } = this._timeBounds(items);
    const tspan = Math.max(1, t1 - t0);
    const xOf = (t) => padL + ((t - t0) / tspan) * innerW;
    const yOf = (v) => padT + (1 - (Number(v) + 1) / 2) * innerH; // -1..1 → top..bottom

    const lines = PAD_LABELS.map((p) => {
      const pts = items.map((it) => {
        const v = it[p.key];
        return v == null ? null : (xOf(it.ts).toFixed(1) + "," + yOf(v).toFixed(1));
      }).filter(Boolean);
      if (pts.length < 2) return "";
      return '<polyline class="emh-line emh-line--' + p.key
        + '" points="' + pts.join(" ") + '" stroke="' + p.color + '"></polyline>';
    }).join("");

    // Y axis ticks
    const yTicks = [-1, -0.5, 0, 0.5, 1].map((v) => {
      const y = yOf(v).toFixed(1);
      return '<line class="emh-grid" x1="' + padL + '" x2="' + (W - padR)
        + '" y1="' + y + '" y2="' + y + '"></line>'
        + '<text class="emh-axis-text" x="' + (padL - 4) + '" y="' + y
        + '" text-anchor="end" dominant-baseline="middle">' + v.toFixed(1) + "</text>";
    }).join("");

    // X axis labels (start, mid, end)
    const xLabels = [t0, (t0 + t1) / 2, t1].map((t, i) => {
      const x = xOf(t).toFixed(1);
      return '<text class="emh-axis-text" x="' + x + '" y="' + (H - 6)
        + '" text-anchor="' + (i === 0 ? "start" : (i === 1 ? "middle" : "end"))
        + '">' + this._fmtTick(t, this._window) + "</text>";
    }).join("");

    // Last-point dots
    const dots = PAD_LABELS.map((p) => {
      const last = items[items.length - 1];
      const v = last[p.key];
      if (v == null) return "";
      return '<circle class="emh-dot emh-dot--' + p.key
        + '" cx="' + xOf(last.ts).toFixed(1) + '" cy="' + yOf(v).toFixed(1)
        + '" r="2.5" fill="' + p.color + '"></circle>';
    }).join("");

    root.innerHTML = (
      '<svg class="emh-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none">'
      + yTicks + lines + dots + xLabels
      + "</svg>"
    );
  }

  // ── Threshold area chart ────────────────────────
  _renderThresholds() {
    const root = document.getElementById("emh-threshold-chart");
    if (!root) return;
    const items = (this._data && this._data.items) || [];
    if (items.length < 2) {
      root.innerHTML = '<div class="emh-empty">数据不足 / need at least 2 points</div>';
      return;
    }
    const W = root.clientWidth || 560;
    const H = 180;
    const padL = 32, padR = 12, padT = 14, padB = 22;
    const innerW = W - padL - padR;
    const innerH = H - padT - padB;
    const { t0, t1 } = this._timeBounds(items);
    const tspan = Math.max(1, t1 - t0);
    const xOf = (t) => padL + ((t - t0) / tspan) * innerW;
    const yOf = (v) => padT + (1 - Math.max(0, Math.min(100, Number(v) || 0)) / 100) * innerH;

    // Areas: filled path from baseline to the line.
    const areas = THRESHOLD_SLOTS.map((s) => {
      const pts = items.map((it) => {
        const v = it[s.key];
        return v == null ? null : xOf(it.ts).toFixed(1) + "," + yOf(v).toFixed(1);
      }).filter(Boolean);
      if (pts.length < 2) return "";
      // Close the path down to baseline.
      const lastX = pts[pts.length - 1].split(",")[0];
      const firstX = pts[0].split(",")[0];
      const baselineY = (H - padB).toFixed(1);
      const d = "M " + firstX + "," + baselineY
        + " L " + pts.join(" L ")
        + " L " + lastX + "," + baselineY + " Z";
      return '<path class="emh-area emh-area--' + s.key
        + '" d="' + d + '" fill="' + s.color + '" fill-opacity="0.18" stroke="none"></path>'
        + '<polyline class="emh-line emh-line--' + s.key
        + '" points="' + pts.join(" ") + '" stroke="' + s.color
        + '" fill="none"></polyline>';
    }).join("");

    // Y axis: 0/50/100
    const yTicks = [0, 50, 100].map((v) => {
      const y = yOf(v).toFixed(1);
      return '<line class="emh-grid" x1="' + padL + '" x2="' + (W - padR)
        + '" y1="' + y + '" y2="' + y + '"></line>'
        + '<text class="emh-axis-text" x="' + (padL - 4) + '" y="' + y
        + '" text-anchor="end" dominant-baseline="middle">' + v + "%</text>";
    }).join("");

    const xLabels = [t0, (t0 + t1) / 2, t1].map((t, i) => {
      const x = xOf(t).toFixed(1);
      return '<text class="emh-axis-text" x="' + x + '" y="' + (H - 6)
        + '" text-anchor="' + (i === 0 ? "start" : (i === 1 ? "middle" : "end"))
        + '">' + this._fmtTick(t, this._window) + "</text>";
    }).join("");

    root.innerHTML = (
      '<svg class="emh-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="none">'
      + yTicks + areas + xLabels
      + "</svg>"
    );
  }

  // ── Radar heatmap ───────────────────────────────
  _renderRadar() {
    const root = document.getElementById("emh-radar-chart");
    if (!root) return;
    const items = (this._data && this._data.items) || [];
    if (items.length < 2) {
      root.innerHTML = '<div class="emh-empty">数据不足 / need at least 2 points</div>';
      return;
    }
    // Bucket count depends on window length. 8 buckets is plenty for
    // visualization and keeps the heatmap readable.
    const N_BUCKETS = 8;
    const labels = Array.from(new Set(items.map((it) => it.label || "neutral")));
    const allLabels = LABEL_KEYS.filter((k) => labels.includes(k));
    // Add any unexpected label so the heatmap still covers all data.
    labels.forEach((l) => {
      if (l && !allLabels.includes(l)) allLabels.push(l);
    });
    if (allLabels.length === 0) allLabels.push("neutral");

    const { t0, t1 } = this._timeBounds(items);
    const tspan = Math.max(1, t1 - t0);
    const bucketSize = tspan / N_BUCKETS;

    // Tally cells
    const matrix = allLabels.map(() => new Array(N_BUCKETS).fill(0));
    items.forEach((it) => {
      const li = allLabels.indexOf(it.label);
      if (li < 0) return;
      const b = Math.min(N_BUCKETS - 1, Math.floor((it.ts - t0) / bucketSize));
      matrix[li][b] += 1;
    });
    let maxCell = 1;
    matrix.forEach((row) => row.forEach((v) => { if (v > maxCell) maxCell = v; }));

    // Draw grid
    const cellW = 32, cellH = 22, labelW = 64, headerH = 18;
    const W = labelW + N_BUCKETS * cellW + 4;
    const H = headerH + allLabels.length * cellH + 4;
    const cellColor = (n) => {
      if (n === 0) return "rgba(255,255,255,0.05)";
      const intensity = Math.min(1, n / maxCell);
      // Pink-magenta gradient palette to match the panel.
      const r = Math.round(255 * intensity);
      const g = Math.round(91 + (60 - 91) * intensity);
      const b = Math.round(156 + (180 - 156) * intensity);
      return "rgba(" + r + "," + g + "," + b + "," + (0.25 + 0.65 * intensity).toFixed(2) + ")";
    };

    // X axis (bucket index) — show start, mid, end time
    const xLabels = [0, Math.floor(N_BUCKETS / 2), N_BUCKETS - 1].map((bi, i) => {
      const t = t0 + bucketSize * (bi + 0.5);
      const x = labelW + bi * cellW + cellW / 2;
      return '<text class="emh-axis-text" x="' + x + '" y="' + (headerH - 4)
        + '" text-anchor="' + (i === 0 ? "start" : (i === 1 ? "middle" : "end"))
        + '">' + this._fmtTick(t, this._window) + "</text>";
    }).join("");

    // Y axis (labels)
    const yLabels = allLabels.map((l, i) => {
      const y = headerH + i * cellH + cellH / 2;
      return '<text class="emh-axis-text emh-radar-label" x="' + (labelW - 6) + '" y="' + y
        + '" text-anchor="end" dominant-baseline="middle">' + this._escape(l) + "</text>";
    }).join("");

    // Cells
    const cells = [];
    for (let li = 0; li < allLabels.length; li++) {
      for (let bi = 0; bi < N_BUCKETS; bi++) {
        const n = matrix[li][bi];
        const x = labelW + bi * cellW;
        const y = headerH + li * cellH;
        cells.push('<rect x="' + x + '" y="' + y + '" width="' + cellW
          + '" height="' + cellH + '" fill="' + cellColor(n)
          + '" stroke="rgba(255,255,255,0.06)"></rect>');
        if (n > 0) {
          cells.push('<text class="emh-cell-text" x="' + (x + cellW / 2)
            + '" y="' + (y + cellH / 2 + 3) + '" text-anchor="middle">'
            + n + "</text>");
        }
      }
    }

    root.innerHTML = (
      '<svg class="emh-svg" viewBox="0 0 ' + W + " " + H + '" preserveAspectRatio="xMinYMin meet">'
      + xLabels + yLabels + cells.join("") + "</svg>"
    );
  }

  // ── Helpers ─────────────────────────────────────
  _windowMs() {
    return {
      "1h": 3_600_000,
      "24h": 86_400_000,
      "7d": 604_800_000,
      "30d": 2_592_000_000,
    }[this._window] || 86_400_000;
  }

  _timeBounds(items) {
    const data = this._data || {};
    let t1 = Number(data.serverNow || data.server_now);
    if (!Number.isFinite(t1) || t1 <= 0) t1 = Date.now();
    let t0 = Number(data.since_ts || data.sinceTs);
    if (!Number.isFinite(t0) || t0 <= 0 || t0 >= t1) {
      t0 = t1 - this._windowMs();
    }
    return { t0, t1 };
  }

  _mergeLivePoint(items) {
    const state = this._latestState;
    const base = Array.isArray(items) ? items.slice() : [];
    if (!state || !state.pad) return base.sort((a, b) => Number(a.ts) - Number(b.ts));
    const ts = Number(state.sampledAt || state.sampled_at);
    const serverNow = Number(
      state.serverNow || state.server_now
      || (this._data && (this._data.serverNow || this._data.server_now))
      || Date.now(),
    );
    if (!Number.isFinite(ts) || ts <= 0 || ts < serverNow - this._windowMs()) {
      return base.sort((a, b) => Number(a.ts) - Number(b.ts));
    }
    const pad = state.pad || {};
    const thresholds = state.thresholds || {};
    const point = {
      ts,
      pleasure: Number.isFinite(Number(pad.P)) ? Number(pad.P) : Number(pad.pleasure),
      arousal: Number.isFinite(Number(pad.A)) ? Number(pad.A) : Number(pad.arousal),
      dominance: Number.isFinite(Number(pad.D)) ? Number(pad.D) : Number(pad.dominance),
      label: state.label || "neutral",
      trigger_event: "live_state",
    };
    for (const slot of ["patience", "anxiety", "desire", "tenderness"]) {
      const info = thresholds[slot] || {};
      point[slot + "_value"] = Number(info.value) || 0;
    }
    const withoutSameSample = base.filter((item) => Number(item.ts) !== ts);
    withoutSameSample.push(point);
    withoutSameSample.sort((a, b) => Number(a.ts) - Number(b.ts));
    return withoutSameSample.slice(-5000);
  }

  _setUpdatedStatus(message, stale) {
    let el = document.getElementById("emh-updated");
    if (!el && document.createElement) {
      const refresh = document.getElementById("emh-refresh");
      const host = refresh && refresh.parentNode;
      if (host && host.appendChild) {
        el = document.createElement("span");
        el.id = "emh-updated";
        el.className = "emh-updated";
        host.appendChild(el);
      }
    }
    if (el) {
      el.textContent = message;
      if (el.classList && el.classList.toggle) {
        el.classList.toggle("is-stale", Boolean(stale));
      }
    }
  }

  _fmtClock(ts) {
    const d = new Date(Number(ts));
    if (Number.isNaN(d.getTime())) return "--:--:--";
    const pad = (n) => String(n).padStart(2, "0");
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  _fmtTick(ts, win) {
    const d = new Date(ts);
    if (win === "1h" || win === "24h") {
      const pad = (n) => (n < 10 ? "0" + n : "" + n);
      return pad(d.getHours()) + ":" + pad(d.getMinutes());
    }
    if (win === "7d" || win === "30d") {
      const pad = (n) => (n < 10 ? "0" + n : "" + n);
      return (d.getMonth() + 1) + "/" + pad(d.getDate());
    }
    return "";
  }

  _escape(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }
}

window.EmotionHistory = EmotionHistory;
window.emotionHistory = new EmotionHistory();
