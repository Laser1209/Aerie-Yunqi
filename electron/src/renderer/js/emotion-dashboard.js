"use strict";
/* Emotion Dashboard — real-time PAD + cumulative threshold display
 *
 * R6.4: Persona-derived defaults. When the API is unreachable (e.g. backend
 * not yet up, network blip), the dashboard still renders a recognisable
 * baseline so the user can verify the system is wired up. The defaults are
 * derived from config/persona.yaml at startup and refreshed whenever the
 * persona document is reloaded.
 *
 * PAD baseline (pleasure / arousal / dominance) is in
 * config/persona_behavior.yaml → emotion.baseline. Threshold initial
 * values are in the same file under emotion.thresholds.*.initial_value.
 * The defaults baked here MUST stay in sync with those config files.
 */

class EmotionDashboard {
  constructor() {
    this.pollInterval = null;
    this._visible = false;
    this._initialized = false;
    this._requestInFlight = false;
    this._hasLiveData = false;
    this._padHistory = null;   // Phase 9 Batch 5: cached history series
    this._persona = null;      // R6.4: cached persona for fallback defaults
    this._hasRendered = false; // R6.4: render fallback once before first fetch
    // R7.5: track the previous tick's PAD so the flow bars can show
    // dP/dt, dA/dt, dD/dt as derivatives of the live state.
    this._prevPad = null;
  }

  init() {
    if (this._initialized) return;
    this._initialized = true;
    this._renderWaiting("等待数据");
    if (this._visible) this._startPolling();
  }

  // ── R6.4: Persona → defaults (Big Five + archetype) ──
  async _loadPersonaForDefaults() {
    try {
      if (!window.aerie || !window.aerie.api) return;
      const r = await window.aerie.api.request({ method: "GET", path: "/api/persona" });
      if (r && r.data && !r.data.error) {
        this._persona = r.data;
      }
    } catch (_) {
      // Non-fatal — keep using baked-in defaults.
    }
  }

  _baselinePad() {
    // Mirrors config/persona_behavior.yaml → emotion.baseline.
    // If persona big_five is available, lightly re-derive:
    //   P   = 0.10  + (A - 0.5) * 0.3  + (E - 0.5) * 0.1
    //   A   = 0.20  + (O - 0.5) * 0.2  + (N - 0.5) * 0.2
    //   D   = 0.80  + (C - 0.5) * 0.1  + (E - 0.5) * 0.1
    // Clamp to [-1, 1].
    const bf = (this._persona && this._persona.profile
      && this._persona.profile.big_five) || {};
    const O = Number(bf.openness) || 0.70;
    const C = Number(bf.conscientiousness) || 0.85;
    const E = Number(bf.extraversion) || 0.45;
    const A = Number(bf.agreeableness) || 0.70;
    const N = Number(bf.neuroticism) || 0.45;
    const clamp = (v) => Math.max(-1, Math.min(1, v));
    return {
      P: clamp(0.10 + (A - 0.5) * 0.3 + (E - 0.5) * 0.1),
      A: clamp(0.20 + (O - 0.5) * 0.2 + (N - 0.5) * 0.2),
      D: clamp(0.80 + (C - 0.5) * 0.1 + (E - 0.5) * 0.1),
    };
  }

  _baselineThresholds() {
    // Mirrors config/persona_behavior.yaml → emotion.thresholds.*
    return {
      patience:    { value: 60, threshold: 100, label: "忍耐值" },
      anxiety:     { value: 15, threshold: 100, label: "不安值" },
      desire:      { value: 35, threshold: 80,  label: "渴望值" },
      tenderness:  { value: 25, threshold: 60,  label: "温柔透支值" },
    };
  }

  _renderFallback() {
    // Kept as a compatibility hook for settings.js. Defaults are not live
    // telemetry and must never overwrite a successfully sampled state.
    if (!this._hasLiveData) this._renderWaiting("等待数据");
  }

  _renderWaiting(message) {
    this._hasRendered = true;
    this._prevPad = null;
    for (const id of ["pad-p", "pad-a", "pad-d"]) {
      const el = document.getElementById(id);
      if (!el) continue;
      const ring = el.querySelector(".pad-card-ring");
      if (ring) ring.style.setProperty("--pad-pct", "0%");
      const value = el.querySelector(".pad-card-value");
      if (value) value.textContent = "--";
      const raw = el.querySelector(".pad-card-raw");
      if (raw) raw.textContent = (raw.getAttribute("data-raw") || "") + "=--";
    }
    for (const slot of ["patience", "anxiety", "desire", "tenderness"]) {
      const el = document.getElementById("threshold-" + slot);
      if (!el) continue;
      const fill = el.querySelector(".threshold-bar-fill");
      if (fill) fill.style.width = "0%";
      const value = el.querySelector(".threshold-bar-value");
      if (value) value.textContent = "-- / --";
    }
    const text = document.getElementById("emotion-label-text");
    if (text) text.textContent = message || "等待数据";
    this._setFreshness(message || "等待数据", true);
  }

  destroy() {
    this._stopPolling();
    this._initialized = false;
  }

  setVisible(v) {
    const visible = Boolean(v);
    if (this._visible === visible) return;
    this._visible = visible;
    if (visible) {
      if (this._initialized) this._startPolling();
      // Phase 9 Batch 5: when the panel becomes visible, also pull the
      // history series so the chart fills in immediately.
      if (window.emotionHistory) window.emotionHistory.refresh();
    } else {
      this._stopPolling();
    }
  }

  _startPolling() {
    this._stopPolling();
    this._loadPersonaForDefaults();
    this.pollInterval = setInterval(() => this._fetch(), 3000);
    this._personaInterval = setInterval(
      () => this._loadPersonaForDefaults(),
      60_000,
    );
    this._fetch();
  }

  _stopPolling() {
    if (this.pollInterval) clearInterval(this.pollInterval);
    if (this._personaInterval) clearInterval(this._personaInterval);
    this.pollInterval = null;
    this._personaInterval = null;
  }

  async _fetch() {
    if (!this._visible || this._requestInFlight) return;
    this._requestInFlight = true;
    try {
      if (!window.aerie || !window.aerie.api) return;
      const r = await window.aerie.api.request({ method: "GET", path: "/api/emotion/state" });
      if (!r || (Number.isInteger(r.status) && (r.status < 200 || r.status >= 300))
          || !r.data || r.data.error) {
        throw new Error(r && r.data && r.data.error || "emotion state unavailable");
      }
      this._render(r.data);
      if (window.emotionHistory) {
        window.emotionHistory.onStateUpdate(r.data);
      }
    } catch (_) {
      if (this._hasLiveData) this._setFreshness("连接中断", true);
      else this._renderWaiting("后端连接中");
    } finally {
      this._requestInFlight = false;
    }
  }

  _render(data) {
    // PAD values — accept both uppercase P/A/D (from get_state) and
    // lowercase pleasure/arousal/dominance (from analyze).
    const pad = data.pad || {};
    const P = this._padVal(pad, "P", "pleasure");
    const A = this._padVal(pad, "A", "arousal");
    const D = this._padVal(pad, "D", "dominance");
    if (![P, A, D].every(Number.isFinite)) {
      this._renderWaiting("等待数据");
      return;
    }
    this._hasLiveData = true;
    this._setPADCard("pad-p", P, "愉悦度");
    this._setPADCard("pad-a", A, "唤醒度");
    this._setPADCard("pad-d", D, "支配度");

    // R7.5: live flow bars show the derivative of PAD since the last
    // 3s poll. Idle ticks from the backend produce small but visible
    // deltas; chat replies produce larger spikes.
    this._setFlowBars(P, A, D);

    // Emotion label — split icon + text (Phase 7: SVG)
    const labelEl = document.getElementById("emotion-label");
    const labelText = data.label || "neutral";
    if (labelEl) {
      labelEl.className = "emotion-label emotion-label--" + labelText;
      const iconEl = document.getElementById("emotion-label-icon");
      if (iconEl) {
        const use = iconEl.querySelector("use");
        if (use) use.setAttribute("href", this._labelToIconId(labelText));
      }
      const textEl = document.getElementById("emotion-label-text");
      if (textEl) textEl.textContent = labelText;
    }

    // Threshold bars
    const thresholds = data.thresholds || {};
    const slotOrder = ["patience", "anxiety", "desire", "tenderness"];
    for (const slot of slotOrder) {
      const info = thresholds[slot];
      if (info) {
        this._setThresholdBar(slot, info);
      }
    }

    // Eruption banner (Phase 7: SVG warning icon, not emoji)
    this._renderEruptionBanner(data.eruption);
    this._setFreshnessFromState(data);
  }

  _renderEruptionBanner(eruption) {
    const banner = document.getElementById("emotion-eruption-banner");
    if (!banner) return;
    if (eruption) {
      const slot = eruption.slot || "patience";
      const cls = "emotion-eruption-banner emotion-eruption-banner--"
        + slot + (eruption.cooldown ? " emotion-eruption-banner--cooldown" : "");
      banner.className = cls;
      banner.innerHTML =
        '<svg class="icon icon--16 banner__icon" aria-hidden="true"><use href="#icon-ui-warning"/></svg>' +
        '<span class="banner__slot">' + this._escape(slot) + "</span>" +
        '<span class="banner__sep">·</span>' +
        '<span class="banner__mode">' + this._escape(eruption.mode || "") + "</span>" +
        '<span class="banner__desc">' + this._escape(eruption.description || "") + "</span>" +
        '<span class="banner__time">' + this._escape(eruption.timestamp || "") + "</span>";
      banner.classList.remove("hidden");
    } else {
      banner.classList.add("hidden");
      banner.className = "emotion-eruption-banner hidden";
    }
  }

  _padVal(pad, upperKey, lowerKey) {
    if (pad == null) return null;
    const v = pad[upperKey];
    if (typeof v === "number" && !Number.isNaN(v)) return v;
    const v2 = pad[lowerKey];
    if (typeof v2 === "number" && !Number.isNaN(v2)) return v2;
    return null;
  }

  _setFreshnessFromState(data) {
    const raw = data.sampledAt || data.sampled_at || data.serverNow;
    const sampled = this._formatTimestamp(raw);
    const prefix = data.stale ? "数据已过期" : "实时";
    this._setFreshness(
      sampled ? prefix + " · 更新于 " + sampled : prefix,
      Boolean(data.stale),
    );
  }

  _setFreshness(message, stale) {
    let el = document.getElementById("emotion-freshness");
    if (!el && document.createElement) {
      const label = document.getElementById("emotion-label");
      const host = label && label.parentNode;
      if (host && host.appendChild) {
        el = document.createElement("span");
        el.id = "emotion-freshness";
        el.className = "emotion-freshness";
        host.appendChild(el);
      }
    }
    if (el) {
      el.textContent = message;
      if (el.classList && el.classList.toggle) {
        el.classList.toggle("is-stale", Boolean(stale));
      }
    }
    const panel = document.getElementById("panel-emotion");
    if (panel && panel.dataset) panel.dataset.freshness = stale ? "stale" : "fresh";
  }

  _formatTimestamp(value) {
    if (value == null || value === "") return "";
    const parsed = typeof value === "number" ? value : Date.parse(String(value));
    if (!Number.isFinite(parsed)) return "";
    const d = new Date(parsed);
    const pad = (n) => String(n).padStart(2, "0");
    return pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds());
  }

  _setPADCard(id, value, label) {
    const el = document.getElementById(id);
    if (!el) return;
    // Clamp PAD to [-1, 1] for the percentage mapping.
    const v = Math.max(-1, Math.min(1, Number(value) || 0));
    const pct = Math.round((v + 1) / 2 * 100); // -1..1 → 0..100
    const ring = el.querySelector(".pad-card-ring");
    if (ring) ring.style.setProperty("--pad-pct", pct + "%");
    const valEl = el.querySelector(".pad-card-value");
    if (valEl) valEl.textContent = v.toFixed(2);
    const labEl = el.querySelector(".pad-card-label");
    if (labEl) labEl.textContent = label;
    // R7.5: 3-decimal raw value row so users can see sub-1% deltas
    // (e.g. P=0.010 vs P=0.000) that the ring collapses visually.
    const rawEl = el.querySelector(".pad-card-raw");
    if (rawEl) {
      const key = rawEl.getAttribute("data-raw") || "";
      const sign = v >= 0 ? "+" : "−";
      const abs = Math.abs(v).toFixed(3);
      rawEl.textContent = key + "=" + sign + abs;
      rawEl.classList.toggle("pad-card-raw--pos", v > 0.0005);
      rawEl.classList.toggle("pad-card-raw--neg", v < -0.0005);
    }
  }

  // R7.5: live flow bars (dP/dt, dA/dt, dD/dt). Width encodes
  // |delta|; the fill on the left half of the track means negative
  // (red), on the right half means positive (green).
  //
  // SCALE was tuned for the original 10s backend tick; the dashboard
  // now polls every 3s and the backend PAD tick also runs every 3s, so
  // per-tick deltas land in the 0.001-0.02 range. SCALE=100 makes a
  // 0.01 delta render as a 1% fill — small but readable. SCALE=25
  // (the previous value) collapsed that to 0.25% which looked frozen.
  //
  // A 3-sample rolling average smooths the inevitable single-tick
  // noise spikes (σ=0.01) so the bar doesn't twitch wildly.
  _setFlowBars(P, A, D) {
    const SCALE = 100;  // 1.0 delta → 100% track width (max ±50% each side)
    const cur = { P: P, A: A, D: D };
    if (!this._prevPad) {
      this._prevPad = cur;
      this._flowBuf = { P: [], A: [], D: [] };
      this._writeFlow("P", 0);
      this._writeFlow("A", 0);
      this._writeFlow("D", 0);
      return;
    }
    const raw = {
      P: cur.P - this._prevPad.P,
      A: cur.A - this._prevPad.A,
      D: cur.D - this._prevPad.D,
    };
    this._prevPad = cur;
    // Rolling buffer: keep last 3 samples, write the mean.
    const buf = this._flowBuf;
    const smooth = (key) => {
      const arr = buf[key];
      arr.push(raw[key]);
      if (arr.length > 3) arr.shift();
      return arr.reduce((s, v) => s + v, 0) / arr.length;
    };
    this._writeFlow("P", smooth("P"));
    this._writeFlow("A", smooth("A"));
    this._writeFlow("D", smooth("D"));
  }

  _writeFlow(key, delta) {
    const SCALE = 100;
    const row = document.querySelector('.emotion-flow-row[data-flow="' + key + '"]');
    if (!row) return;
    const posFill = row.querySelector('.emotion-flow-fill[data-side="pos"]');
    const negFill = row.querySelector('.emotion-flow-fill[data-side="neg"]');
    const valEl = row.querySelector('.emotion-flow-value[data-flow-val="' + key + '"]');
    if (posFill) posFill.style.width = Math.max(0, Math.min(50, delta * SCALE)) + "%";
    if (negFill) negFill.style.width = Math.max(0, Math.min(50, -delta * SCALE)) + "%";
    if (valEl) {
      const sign = delta >= 0 ? "+" : "−";
      valEl.textContent = sign + Math.abs(delta).toFixed(3);
      valEl.classList.toggle("emotion-flow-value--pos", delta > 0.0001);
      valEl.classList.toggle("emotion-flow-value--neg", delta < -0.0001);
    }
  }

  _setThresholdBar(slot, info) {
    const el = document.getElementById("threshold-" + slot);
    if (!el) return;
    // R6.4: if API or fallback didn't include pct, derive from
    // value / threshold so the bar always reflects the actual ratio.
    let pct = Number(info.pct);
    if (!Number.isFinite(pct) || pct < 0) {
      const v = Number(info.value) || 0;
      const t = Number(info.threshold) || 0;
      pct = t > 0 ? (v / t) * 100 : 0;
    }
    pct = Math.min(100, Math.max(0, pct));
    const fill = el.querySelector(".threshold-bar-fill");
    if (fill) {
      fill.style.width = pct + "%";
      if (pct > 80) fill.className = "threshold-bar-fill threshold-bar-fill--danger";
      else if (pct > 50) fill.className = "threshold-bar-fill threshold-bar-fill--warning";
      else fill.className = "threshold-bar-fill";
    }
    const valEl = el.querySelector(".threshold-bar-value");
    if (valEl) {
      valEl.textContent =
        (Number(info.value) || 0).toFixed(0) + " / " + (Number(info.threshold) || 0).toFixed(0);
    }
    const labEl = el.querySelector(".threshold-bar-label");
    if (labEl) labEl.textContent = info.label || slot;
  }

  _labelToIconId(label) {
    const map = {
      joy: "#icon-mood-joy",
      sad: "#icon-mood-sad",
      anger: "#icon-mood-anger",
      fear: "#icon-mood-fear",
      neutral: "#icon-mood-neutral",
    };
    return map[label] || "#icon-mood-neutral";
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

// Export singleton
window.EmotionDashboard = EmotionDashboard;

