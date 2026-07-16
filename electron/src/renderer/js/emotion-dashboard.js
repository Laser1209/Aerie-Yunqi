"use strict";
/* Emotion Dashboard — real-time PAD + cumulative threshold display */

class EmotionDashboard {
  constructor() {
    this.pollInterval = null;
    this._visible = false;
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
    if (v) this._fetch();
  }

  async _fetch() {
    if (!this._visible) return;
    try {
      if (!window.aerie) return;
      const r = await window.aerie.api.request({ method: "GET", path: "/api/emotion/state" });
      if (r.data && !r.data.error) {
        this._render(r.data);
      }
    } catch (_) {}
  }

  _render(data) {
    // PAD values
    const pad = data.pad || {};
    this._setPADCard("pad-p", pad.P || 0, "愉悦度");
    this._setPADCard("pad-a", pad.A || 0, "唤醒度");
    this._setPADCard("pad-d", pad.D || 0, "支配度");

    // Emotion label
    const labelEl = document.getElementById("emotion-label");
    if (labelEl) {
      labelEl.textContent = this._labelToEmoji(data.label || "neutral") + " " + (data.label || "neutral");
      labelEl.className = "emotion-label emotion-label--" + (data.label || "neutral");
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

    // Eruption banner
    const banner = document.getElementById("emotion-eruption-banner");
    if (banner && data.eruption) {
      banner.textContent = "⚠ " + data.eruption.mode + " — " + (data.eruption.description || "");
      banner.classList.remove("hidden");
      banner.className = "emotion-eruption-banner emotion-eruption-banner--" + (data.eruption.slot || "patience");
    } else if (banner) {
      banner.classList.add("hidden");
    }
  }

  _setPADCard(id, value, label) {
    const el = document.getElementById(id);
    if (!el) return;
    const pct = Math.round((value + 1) / 2 * 100); // -1..1 → 0..100
    el.querySelector(".pad-card-ring").style.setProperty("--pad-pct", pct + "%");
    el.querySelector(".pad-card-value").textContent = value.toFixed(2);
    el.querySelector(".pad-card-label").textContent = label;
  }

  _setThresholdBar(slot, info) {
    const el = document.getElementById("threshold-" + slot);
    if (!el) return;
    const pct = Math.min(100, Math.max(0, info.pct || 0));
    el.querySelector(".threshold-bar-fill").style.width = pct + "%";
    el.querySelector(".threshold-bar-value").textContent =
      (info.value || 0).toFixed(0) + " / " + (info.threshold || 0).toFixed(0);
    el.querySelector(".threshold-bar-label").textContent = info.label || slot;

    // Color coding: near threshold = warning
    const fill = el.querySelector(".threshold-bar-fill");
    if (pct > 80) fill.className = "threshold-bar-fill threshold-bar-fill--danger";
    else if (pct > 50) fill.className = "threshold-bar-fill threshold-bar-fill--warning";
    else fill.className = "threshold-bar-fill";
  }

  _labelToEmoji(label) {
    const map = { joy: "\u{1F60A}", sad: "\u{1F622}", anger: "\u{1F621}", fear: "\u{1F628}", neutral: "\u{1F610}" };
    return map[label] || "\u{1F610}";
  }
}

// Export singleton
window.EmotionDashboard = EmotionDashboard;
