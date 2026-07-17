/* Aerie · 云栖 — brief-drawer.js (R7.2 brief-refactor)
   Replaces the 3 legacy surfaces (popup BrowserWindow, detail window,
   and main-app iframe) with a single self-contained right-side drawer
   that lives inside the main app. No system frame, no cross-window IPC,
   no hot-reload pain.

   R7.2 fixes (vs R7.1):
   - logo src: `Aerie · 云栖.svg` (file did not exist) → `assets/logo.png`
   - greeting: hard-coded "伊塔" → /api/persona `name` (cache + fallback)
   - date prefix: calendar emoji → inline SVG calendar
   - feedback: thumbs now POST /api/brief/feedback and lock once used
   - expand: "展开完整" now fetches /api/brief/run?limit=8 and grows the
     drawer to 92vw; clicking again collapses without re-fetching.
   - all colours and shadows come from main.css :root tokens.
*/
"use strict";

/* ── tiny DOM helpers (no DOMPurify / no framework) ───────── */
function _el(tag, props = {}, children = []) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k === "class") n.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(n.style, v);
    else if (k.startsWith("on") && typeof v === "function") n.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === "html") n.innerHTML = v;
    else if (v != null) n.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c == null) continue;
    n.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return n;
}

const _SVG = (vb, body, size = 12) =>
  `<svg viewBox="${vb}" width="${size}" height="${size}" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${body}</svg>`;

/* SVG icon library — keeps the drawer free of emoji (R6.2 three principles). */
const _ICONS = {
  close:    _SVG("0 0 24 24", '<path d="M18 6L6 18M6 6l12 12"/>', 14),
  refresh:  _SVG("0 0 24 24", '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>', 14),
  expand:   _SVG("0 0 24 24", '<path d="M7 17L17 7"/><path d="M8 7h9v9"/>', 12),
  collapse: _SVG("0 0 24 24", '<path d="M17 7L7 17"/><path d="M16 17h-9v-9"/>', 12),
  chat:     _SVG("0 0 24 24", '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>', 12),
  sun:      _SVG("0 0 24 24", '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>', 16),
  /* R7.2: SVG replacement for the calendar emoji previously used in the date row. */
  calendar: _SVG("0 0 24 24", '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>', 12),
  thumbUp:  _SVG("0 0 24 24", '<path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z"/>', 12),
  thumbDn:  _SVG("0 0 24 24", '<path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H17a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z"/>', 12),
  /* R7.3: location pin (SVG glyph replacing the previous emoji). */
  pin:      _SVG("0 0 24 24", '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>', 14),
  retry:    _SVG("0 0 24 24", '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/>', 12),
};

const SECTION_META = {
  ai_news:   { label: "AI 动向 / AI Trends",  icon: _SVG("0 0 24 24", '<path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M5.6 18.4l2.1-2.1M16.3 7.7l2.1-2.1"/><circle cx="12" cy="12" r="3.5"/>') },
  it_news:   { label: "IT 行业 / Tech Industry", icon: _SVG("0 0 24 24", '<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3M15 1v3M9 20v3M15 20v3M20 9h3M20 14h3M1 9h3M1 14h3"/>') },
  intl_news: { label: "国际 / International", icon: _SVG("0 0 24 24", '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>') },
  cn_news:   { label: "国家 / National", icon: _SVG("0 0 24 24", '<path d="M3 21V8l9-5 9 5v13"/><path d="M9 21V12h6v9"/>') },
};

/* Default limits: drawer 3条/段，展开 8条/段。 */
const COLLAPSED_LIMIT = 3;
const EXPANDED_LIMIT  = 8;

/* ── class ─────────────────────────────────────────────────── */
class BriefDrawer {
  constructor(root) {
    this.root = root || document.body;
    this._open = false;
    this._loading = false;
    this._cached = null;     // last successful payload, kept for re-open
    this._expanded = false;  // 是否展开到 92vw
    this._expandedData = null; // 展开模式下的最新数据（含 8 条/段）
    this._displayName = "伊塔"; // from /api/persona
    this._nameLoaded = false;
    this._render();
    this._bindEsc();
    this._bindBus();
  }

  /* DOM construction (called once) */
  _render() {
    // Backdrop
    this._backdrop = _el("div", { class: "brief-drawer-backdrop" });
    this._backdrop.addEventListener("click", () => this.close());
    this.root.appendChild(this._backdrop);

    // Drawer shell
    this._drawer = _el("aside", {
      class: "brief-drawer",
      id: "brief-drawer",
      "aria-hidden": "true",
    });
    this._drawer.innerHTML = `
      <div class="brief-drawer__bar">
        <div class="brief-drawer__bar-left">
          <img class="brief-drawer__logo" src="assets/logo.png" alt="Aerie"
               onerror="this.onerror=null;this.style.visibility='hidden'">
          <span class="brief-drawer__title">Aerie · 云栖</span>
          <span class="brief-drawer__sub">每日简报 · Daily Brief</span>
        </div>
        <div class="brief-drawer__bar-right">
          <button class="brief-drawer__icon-btn" id="brief-drawer-loc"
                  title="更改城市 / Change city" aria-label="更改城市">${_ICONS.pin}</button>
          <button class="brief-drawer__icon-btn" id="brief-drawer-refresh"
                  title="刷新 / Refresh" aria-label="刷新">${_ICONS.refresh}</button>
          <button class="brief-drawer__icon-btn brief-drawer__icon-btn--close" id="brief-drawer-close"
                  title="关闭 / Close" aria-label="关闭">${_ICONS.close}</button>
        </div>
      </div>
      <div class="brief-drawer__locpop" id="brief-drawer-locpop" role="dialog" aria-label="更改城市">
        <div class="brief-drawer__locpop-brand">
          <span class="brief-drawer__locpop-brand-mark">A</span>
          <span class="brief-drawer__locpop-brand-text">更改定位 · Location</span>
        </div>
        <div class="brief-drawer__locpop-title">输入城市名（如 上海 / Beijing）</div>
        <div class="brief-drawer__locpop-row">
          <input class="brief-drawer__locpop-input" id="brief-drawer-locpop-input"
                 type="text" maxlength="40" placeholder="上海" autocomplete="off">
          <button class="brief-drawer__locpop-save" id="brief-drawer-locpop-save">保存</button>
        </div>
        <div class="brief-drawer__locpop-hint">保存后会立刻重拉天气；空值则恢复为 IP 自动定位。</div>
      </div>
      <div class="brief-drawer__body" id="brief-drawer-body">
        <div class="brief-drawer__skeleton" id="brief-drawer-skeleton">
          <div class="brief-drawer__skeleton-card"></div>
          <div class="brief-drawer__skeleton-card"></div>
          <div class="brief-drawer__skeleton-card"></div>
          <div class="brief-drawer__skeleton-card"></div>
          <div class="brief-drawer__skeleton-card"></div>
          <div class="brief-drawer__skeleton-dots"><span></span><span></span><span></span></div>
        </div>
      </div>
      <div class="brief-drawer__footer">
        <span class="brief-drawer__footer-text">有什么需要我帮忙的吗？</span>
        <div class="brief-drawer__footer-actions">
          <a href="#" class="brief-drawer__footer-link" id="brief-drawer-chat">${_ICONS.chat} <span>和她聊聊</span></a>
          <a href="#" class="brief-drawer__footer-link" id="brief-drawer-expand">${_ICONS.expand} <span id="brief-drawer-expand-label">展开完整</span></a>
        </div>
      </div>
    `;
    this.root.appendChild(this._drawer);

    // Bindings
    this._drawer.querySelector("#brief-drawer-close").addEventListener("click", () => this.close());
    this._drawer.querySelector("#brief-drawer-refresh").addEventListener("click", () => this.refresh());
    /* R7.3: location pin opens an inline popover. Click outside or Esc closes it. */
    this._locBtn = this._drawer.querySelector("#brief-drawer-loc");
    this._locpop = this._drawer.querySelector("#brief-drawer-locpop");
    this._locpopInput = this._drawer.querySelector("#brief-drawer-locpop-input");
    this._locpopSave = this._drawer.querySelector("#brief-drawer-locpop-save");
    this._locBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      this._toggleLocPop();
    });
    this._locpop.addEventListener("click", (e) => e.stopPropagation());
    this._locpopSave.addEventListener("click", () => this._onLocSave());
    this._locpopInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); this._onLocSave(); }
      if (e.key === "Escape") { this._closeLocPop(); }
    });
    this._drawer.querySelector("#brief-drawer-chat").addEventListener("click", (e) => {
      e.preventDefault();
      this.close();
      try {
        const chatTab = document.querySelector('[data-tab="chat"]');
        if (chatTab) chatTab.click();
        const input = document.getElementById("chat-input") || document.querySelector(".chat-input");
        if (input) setTimeout(() => input.focus(), 350);
      } catch (_) {}
    });
    this._expandBtn = this._drawer.querySelector("#brief-drawer-expand");
    this._expandLabel = this._drawer.querySelector("#brief-drawer-expand-label");
    this._expandBtn.addEventListener("click", (e) => {
      e.preventDefault();
      this._toggleExpanded();
    });
  }

  _bindEsc() {
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && this._open) this.close();
    });
    /* R7.3: clicking outside the location popover closes it. */
    document.addEventListener("click", (e) => {
      if (!this._locpop || !this._locpop.classList.contains("is-open")) return;
      if (this._locpop.contains(e.target) || (this._locBtn && this._locBtn.contains(e.target))) return;
      this._closeLocPop();
    });
  }

  /* R7.3: location popover helpers (inline city editor). */
  _toggleLocPop() {
    if (!this._locpop) return;
    if (this._locpop.classList.contains("is-open")) {
      this._closeLocPop();
    } else {
      this._locpop.classList.add("is-open");
      this._locBtn && this._locBtn.classList.add("is-active");
      // Pre-fill with the current city (if known) so the user can edit.
      try {
        const cur = (this._cached && this._cached.weather && this._cached.weather.city) || "";
        if (this._locpopInput && !this._locpopInput.value) {
          this._locpopInput.value = cur;
        }
        if (this._locpopInput) {
          setTimeout(() => { try { this._locpopInput.focus(); this._locpopInput.select(); } catch (_) {} }, 30);
        }
      } catch (_) {}
    }
  }
  _closeLocPop() {
    if (!this._locpop) return;
    this._locpop.classList.remove("is-open");
    this._locBtn && this._locBtn.classList.remove("is-active");
  }
  async _onLocSave() {
    if (!this._locpopInput) return;
    const city = (this._locpopInput.value || "").trim();
    this._locpopSave && (this._locpopSave.disabled = true);
    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request);
      if (api) {
        await api({ method: "POST", path: "/api/location/set", body: { city } });
      }
      this._closeLocPop();
      // Re-fetch so the user sees the new city in the pill / weather.
      this.refresh();
    } catch (e) {
      console.warn("brief-drawer: location save failed", e);
    } finally {
      this._locpopSave && (this._locpopSave.disabled = false);
    }
  }

  _bindBus() {
    // R7.1: internal bus so the topbar "今日简报" button can open us
    // without going through any IPC channel.
    const bus = (window.bus || (window.bus = {
      on(ev, fn) { (this._listeners[ev] = this._listeners[ev] || []).push(fn); },
      emit(ev, data) { (this._listeners[ev] || []).forEach(fn => { try { fn(data); } catch (e) { console.warn(e); } }); },
      _listeners: {},
    }));
    bus.on("brief:open",  () => this.open());
    bus.on("brief:close", () => this.close());
    bus.on("brief:refresh", () => this.refresh());
  }

  /* lifecycle */
  open() {
    if (this._open) return;
    this._open = true;
    this._drawer.classList.add("is-open");
    this._backdrop.classList.add("is-open");
    this._drawer.setAttribute("aria-hidden", "false");
    document.body.style.overflow = "hidden";
    // Eagerly load persona name so the greeting is correct on first paint.
    this._ensureDisplayName();
    // Use cache if fresh enough; otherwise fetch.
    if (this._cached && (Date.now() - this._cached._ts) < 60_000) {
      this._renderData(this._cached);
    } else {
      this.refresh();
    }
  }

  close() {
    if (!this._open) return;
    this._open = false;
    this._drawer.classList.remove("is-open");
    this._backdrop.classList.remove("is-open");
    this._drawer.setAttribute("aria-hidden", "true");
    document.body.style.overflow = "";
  }

  async refresh() {
    if (this._loading) return;
    this._loading = true;
    this._showSkeleton();
    this._spinRefresh(true);
    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request) || null;
      if (!api) throw new Error("IPC not available");
      // Collapse back to default size on a manual refresh so the user
      // gets the canonical 3/section view first.
      if (this._expanded) this._setExpanded(false, /*redraw*/ false);
      const r = await api({ method: "GET", path: "/api/brief/today" });
      const data = (r && r.data && r.data.brief) ? r.data.brief
                  : (r && r.data) ? r.data
                  : {};
      this._cached = Object.assign({}, data, { _ts: Date.now() });
      this._cached._limit = COLLAPSED_LIMIT;
      this._renderData(this._cached);
    } catch (e) {
      console.warn("brief-drawer: refresh failed", e);
      this._renderError(e.message || String(e));
    } finally {
      this._loading = false;
      this._spinRefresh(false);
    }
  }

  /* ── helpers ───────────────────────────────────────── */
  _body() { return this._drawer.querySelector("#brief-drawer-body"); }

  _spinRefresh(on) {
    const btn = this._drawer.querySelector("#brief-drawer-refresh");
    if (!btn) return;
    btn.classList.toggle("is-spinning", !!on);
    btn.disabled = !!on;
  }

  async _ensureDisplayName() {
    if (this._nameLoaded) return;
    this._nameLoaded = true; // mark even on failure to avoid spamming
    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request);
      if (!api) return;
      const r = await api({ method: "GET", path: "/api/persona" });
      const data = (r && r.data) || {};
      const nm = (data.name || data.english_name || "").toString().trim();
      if (nm) {
        this._displayName = nm;
        // Re-render the greeting inline if the drawer is already showing data.
        if (this._cached) this._renderData(this._cached);
      }
    } catch (e) {
      console.warn("brief-drawer: persona fetch failed", e);
    }
  }

  _showSkeleton() {
    this._body().innerHTML = `
      <div class="brief-drawer__skeleton">
        <div class="brief-drawer__skeleton-card"></div>
        <div class="brief-drawer__skeleton-card"></div>
        <div class="brief-drawer__skeleton-card"></div>
        <div class="brief-drawer__skeleton-card"></div>
        <div class="brief-drawer__skeleton-card"></div>
        <div class="brief-drawer__skeleton-dots"><span></span><span></span><span></span></div>
      </div>
    `;
  }

  _renderData(data) {
    const sections = ["ai_news", "it_news", "intl_news", "cn_news"];
    const fragment = document.createDocumentFragment();
    fragment.appendChild(this._renderGreeting(data));
    fragment.appendChild(this._renderDate(data));
    /* R7.3: location pill sits right under the date so the user can
       instantly see whether the IP / manual city resolved correctly. */
    fragment.appendChild(this._renderLocation(data));
    let i = 0;
    for (const key of sections) {
      fragment.appendChild(this._renderSection(key, data[key] || [], i++));
    }
    fragment.appendChild(this._renderWeather(data.weather));
    this._body().innerHTML = "";
    this._body().appendChild(fragment);
  }

  _renderGreeting(data) {
    const h = new Date().getHours();
    const greet = h < 6 ? "夜深了" : h < 11 ? "早上好" : h < 14 ? "中午好" : h < 18 ? "下午好" : "晚上好";
    const head = _el("div", { class: "brief-drawer__greet" }, [
      _el("span", { class: "brief-drawer__greet-text" }, greet + "，" + this._displayName),
      _el("span", { class: "brief-drawer__greet-sun" }, _ICONS.sun),
    ]);
    return head;
  }

  _renderDate(data) {
    const date = data.date || new Date().toISOString().slice(0, 10);
    // R7.2: SVG calendar icon instead of the old calendar emoji.
    return _el("p", { class: "brief-drawer__date", html: _ICONS.calendar + " <span>" + _esc(date) + "</span>" });
  }

  /* R7.3: location pill — city + "自动/已设" tag + pin glyph. */
  _renderLocation(data) {
    const w = data && data.weather ? data.weather : null;
    const city = (w && w.city) ? w.city : "—";
    const tag = (w && w.manual) ? "已设" : "自动";
    const pill = _el("div", { class: "brief-drawer__loc" });
    pill.innerHTML = _ICONS.pin
      + ' <span class="brief-drawer__loc-city">' + _esc(city) + "</span>"
      + ' <span class="brief-drawer__loc-tag">· ' + _esc(tag) + "</span>";
    pill.addEventListener("click", () => this._toggleLocPop());
    return pill;
  }

  _renderSection(key, items, idx) {
    const meta = SECTION_META[key] || { label: key, icon: "" };
    /* R7.3: card → row (semantic shift, no visual "card" feel). */
    const row = _el("div", {
      class: "brief-drawer__row" + (key === "weather" ? " brief-drawer__row--weather" : ""),
      "data-section": key,
    });
    row.style.setProperty("--brief-i", String(idx));

    const title = _el("div", { class: "brief-drawer__row-title" }, "");
    title.innerHTML = meta.icon + " " + _esc(meta.label);
    const count = _el("span", { class: "brief-drawer__row-count" }, String(items.length));
    title.appendChild(count);
    row.appendChild(title);

    const list = _el("ul", { class: "brief-drawer__list" });
    if (!items.length) {
      list.appendChild(_el("li", { class: "brief-drawer__item brief-drawer__item--empty" }, "（暂无）"));
    } else {
      for (const it of items) {
        const li = _el("li", { class: "brief-drawer__item" });
        if (it && it.url) {
          const a = _el("a", { href: it.url, target: "_blank", rel: "noopener" });
          a.textContent = (it.title || it.text || it.url).toString();
          li.appendChild(a);
        } else {
          li.textContent = (it && (it.title || it.text)) || JSON.stringify(it);
        }
        list.appendChild(li);
      }
    }
    row.appendChild(list);

    // Feedback row — R7.2: real POST + lock after use.
    const upBtn = _el("button", {
      class: "brief-drawer__thumb brief-drawer__thumb--up",
      "data-thumb": "up",
      "aria-label": "喜欢",
    });
    upBtn.innerHTML = _ICONS.thumbUp;
    upBtn.addEventListener("click", () => this._onThumb(key, "up", upBtn, downBtn));

    const downBtn = _el("button", {
      class: "brief-drawer__thumb brief-drawer__thumb--down",
      "data-thumb": "down",
      "aria-label": "不喜欢",
    });
    downBtn.innerHTML = _ICONS.thumbDn;
    downBtn.addEventListener("click", () => this._onThumb(key, "down", downBtn, upBtn));

    const commentInput = _el("input", {
      class: "brief-drawer__comment",
      type: "text",
      placeholder: "想说点什么 / Comment…",
      maxlength: "120",
    });
    commentInput.addEventListener("change", () => {
      const txt = commentInput.value.trim();
      if (txt) this._onComment(key, txt, commentInput);
    });

    const fb = _el("div", { class: "brief-drawer__feedback" }, [upBtn, downBtn, commentInput]);
    row.appendChild(fb);
    return row;
  }

  _renderWeather(weather) {
    const row = _el("div", {
      class: "brief-drawer__row brief-drawer__row--weather",
      "data-section": "weather",
    });
    row.style.setProperty("--brief-i", "4");
    const title = _el("div", { class: "brief-drawer__row-title" });
    title.innerHTML = _ICONS.sun + " 天气 / Weather";
    row.appendChild(title);

    const w = weather || {};
    const city = w.city || "—";
    const temp = (w.temp || "—") + "℃";
    const desc = w.desc || "暂无 / unavailable";
    const sug  = w.suggestion ? " · " + w.suggestion : "";
    const pill = _el("div", { class: "brief-drawer__weather" }, [
      _el("div", {}, [
        _el("span", { class: "brief-drawer__weather-city" }, _esc(city)),
        _el("span", { class: "brief-drawer__weather-temp" }, " " + _esc(temp)),
      ]),
      _el("div", { class: "brief-drawer__weather-desc" }, _esc(desc + sug)),
    ]);
    row.appendChild(pill);

    // Weather also gets thumbs
    const upBtn = _el("button", {
      class: "brief-drawer__thumb brief-drawer__thumb--up",
      "data-thumb": "up",
    });
    upBtn.innerHTML = _ICONS.thumbUp;
    upBtn.addEventListener("click", () => this._onThumb("weather", "up", upBtn, downBtn));

    const downBtn = _el("button", {
      class: "brief-drawer__thumb brief-drawer__thumb--down",
      "data-thumb": "down",
    });
    downBtn.innerHTML = _ICONS.thumbDn;
    downBtn.addEventListener("click", () => this._onThumb("weather", "down", downBtn, upBtn));

    const commentInput = _el("input", {
      class: "brief-drawer__comment",
      type: "text",
      placeholder: "想说点什么 / Comment…",
      maxlength: "120",
    });
    commentInput.addEventListener("change", () => {
      const txt = commentInput.value.trim();
      if (txt) this._onComment("weather", txt, commentInput);
    });

    const fb = _el("div", { class: "brief-drawer__feedback" }, [upBtn, downBtn, commentInput]);
    row.appendChild(fb);
    return row;
  }

  _renderError(msg) {
    this._body().innerHTML = `
      <div class="brief-drawer__error">
        <div class="brief-drawer__error-title">简报暂时拿不到 · Brief unavailable</div>
        <div class="brief-drawer__error-detail">${_esc(msg)}</div>
        <div class="brief-drawer__error-detail">请确认后端已启动 / Make sure the backend is running.</div>
        <button class="brief-drawer__error-retry" id="brief-drawer-error-retry">${_ICONS.retry}<span>重试</span></button>
      </div>
    `;
    const btn = this._body().querySelector("#brief-drawer-error-retry");
    if (btn) btn.addEventListener("click", () => this.refresh());
  }

  /* ── feedback ────────────────────────────────────── */
  async _onThumb(section, value, btn, sibling) {
    if (btn.disabled) return;
    // Optimistic UI
    btn.classList.add("is-on");
    btn.disabled = true;
    if (sibling) { sibling.disabled = true; sibling.classList.remove("is-on"); }

    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request);
      if (!api) return;
      await api({
        method: "POST",
        path: "/api/brief/feedback",
        body: { section, value, ts: Date.now() },
      });
    } catch (e) {
      console.warn("brief-drawer: feedback failed", e);
      // Keep the visual state even if the network call fails; user already
      // expressed intent and we don't want a flicker.
    }
  }

  async _onComment(section, text, input) {
    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request);
      if (!api) return;
      await api({
        method: "POST",
        path: "/api/brief/feedback",
        body: { section, value: "comment", text, ts: Date.now() },
      });
      input.value = "";
    } catch (e) {
      console.warn("brief-drawer: comment failed", e);
    }
  }

  /* ── expand / collapse ───────────────────────────── */
  async _toggleExpanded() {
    if (this._expanded) {
      this._setExpanded(false, false);
      return;
    }
    // Need to fetch the expanded payload first.
    this._setExpanded(true, false);
    this._showSkeleton();
    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request);
      if (!api) throw new Error("IPC not available");
      const r = await api({
        method: "POST",
        path: "/api/brief/run?limit=" + EXPANDED_LIMIT,
        body: { limit: EXPANDED_LIMIT },
      });
      const data = (r && r.data && r.data.brief) ? r.data.brief
                  : (r && r.data) ? r.data
                  : {};
      this._expandedData = Object.assign({}, data, { _ts: Date.now() });
      this._expandedData._limit = EXPANDED_LIMIT;
      this._renderData(this._expandedData);
    } catch (e) {
      console.warn("brief-drawer: expand failed", e);
      this._renderError("展开失败 / Expand failed: " + (e.message || String(e)));
      // Revert expansion since we couldn't load the data
      this._setExpanded(false, false);
    }
  }

  _setExpanded(on, redraw) {
    this._expanded = !!on;
    this._drawer.classList.toggle("brief-drawer--expanded", this._expanded);
    this._expandBtn.classList.toggle("is-expanded", this._expanded);
    this._expandLabel.textContent = this._expanded ? "收起" : "展开完整";
    // Swap the expand/collapse icon (find first <svg> in the link)
    const svg = this._expandBtn.querySelector("svg");
    if (svg) {
      // Replace the icon by re-rendering the whole footer link? Too much.
      // Easier: just replace innerHTML of the link minus the label.
      const newIcon = this._expanded ? _ICONS.collapse : _ICONS.expand;
      const label = _expandLabel_text(this._expandLabel);
      this._expandBtn.innerHTML = newIcon + " <span id='brief-drawer-expand-label'>" + _esc(label) + "</span>";
      // Re-bind the click handler (innerHTML replacement kills the old one)
      this._expandBtn = this._drawer.querySelector("#brief-drawer-expand");
      this._expandLabel = this._drawer.querySelector("#brief-drawer-expand-label");
      this._expandBtn.addEventListener("click", (e) => { e.preventDefault(); this._toggleExpanded(); });
    }
    if (redraw !== false && (this._cached || this._expandedData)) {
      this._renderData(this._expanded ? (this._expandedData || this._cached) : this._cached);
    }
  }
}

function _expandLabel_text(el) {
  return el ? el.textContent : "";
}

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/* singleton bootstrap */
window.briefDrawer = null;
function _bootBriefDrawer() {
  if (window.briefDrawer) return window.briefDrawer;
  window.briefDrawer = new BriefDrawer(document.body);
  return window.briefDrawer;
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", _bootBriefDrawer, { once: true });
} else {
  _bootBriefDrawer();
}
