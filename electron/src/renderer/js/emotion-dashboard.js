"use strict";
/* Emotion Dashboard — real-time PAD + cumulative threshold display */

class EmotionDashboard {
  constructor() {
    this.pollInterval = null;
    this._visible = false;
    this._padHistory = null;   // Phase 9 Batch 5: cached history series
  }

  init() {
    // Start polling for emotion data
    this.pollInterval = setInterval(() => this._fetch(), 3000);
    this._fetch(); // immediate first fetch
  }

  destroy() {
    if (this.pollInterval) {
      clearInterval(this.pollInterval);
      this.pollInterval = null;
    }
  }

  setVisible(v) {
    this._visible = v;
    if (v) {
      this._fetch();
      // Phase 9 Batch 5: when the panel becomes visible, also pull the
      // history series so the chart fills in immediately.
      if (window.emotionHistory) window.emotionHistory.refresh();
    }
  }

  async _fetch() {
    if (!this._visible) return;
    try {
      if (!window.aerie) return;
      const r = await window.aerie.api.request({ method: "GET", path: "/api/emotion/state" });
      if (r.data && !r.data.error) {
        this._render(r.data);
        // Notify the history module about the freshest label so the
        // chart annotation can move accordingly.
        if (window.emotionHistory) {
          window.emotionHistory.onStateUpdate(r.data);
        }
      }
    } catch (_) {}
  }

  _render(data) {
    // PAD values — accept both uppercase P/A/D (from get_state) and
    // lowercase pleasure/arousal/dominance (from analyze).
    const pad = data.pad || {};
    const P = this._padVal(pad, "P", "pleasure");
    const A = this._padVal(pad, "A", "arousal");
    const D = this._padVal(pad, "D", "dominance");
    this._setPADCard("pad-p", P, "愉悦度");
    this._setPADCard("pad-a", A, "唤醒度");
    this._setPADCard("pad-d", D, "支配度");

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
    if (pad == null) return 0;
    const v = pad[upperKey];
    if (typeof v === "number" && !Number.isNaN(v)) return v;
    const v2 = pad[lowerKey];
    if (typeof v2 === "number" && !Number.isNaN(v2)) return v2;
    return 0;
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
  }

  _setThresholdBar(slot, info) {
    const el = document.getElementById("threshold-" + slot);
    if (!el) return;
    const pct = Math.min(100, Math.max(0, Number(info.pct) || 0));
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

