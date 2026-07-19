/* Aerie · 云栖 — brief-drawer.js (v12.2.0 task-priority)
   Super Productivity 式任务优先每日简报：
   1. 顶部问候（伊塔人设）
   2. 今日待办（核心区域，可交互）
   3. 今日趋势
   4. 新闻资讯
*/
"use strict";

/* ── tiny DOM helpers ────────────────────────────────────── */
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

/* SVG icon library */
const _ICONS = {
  close:    _SVG("0 0 24 24", '<path d="M18 6L6 18M6 6l12 12"/>', 14),
  refresh:  _SVG("0 0 24 24", '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M3 21v-5h5"/>', 14),
  expand:   _SVG("0 0 24 24", '<path d="M7 17L17 7"/><path d="M8 7h9v9"/>', 12),
  collapse: _SVG("0 0 24 24", '<path d="M17 7L7 17"/><path d="M16 17h-9v-9"/>', 12),
  chat:     _SVG("0 0 24 24", '<path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z"/>', 12),
  sun:      _SVG("0 0 24 24", '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M4.93 19.07l1.41-1.41M17.66 6.34l1.41-1.41"/>', 16),
  calendar: _SVG("0 0 24 24", '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/>', 12),
  thumbUp:  _SVG("0 0 24 24", '<path d="M7 10v12"/><path d="M15 5.88 14 10h5.83a2 2 0 0 1 1.92 2.56l-2.33 8A2 2 0 0 1 17.5 22H7a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2h2.76a2 2 0 0 0 1.79-1.11L12 2h0a3.13 3.13 0 0 1 3 3.88Z"/>', 12),
  thumbDn:  _SVG("0 0 24 24", '<path d="M17 14V2"/><path d="M9 18.12 10 14H4.17a2 2 0 0 1-1.92-2.56l2.33-8A2 2 0 0 1 6.5 2H17a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-2.76a2 2 0 0 0-1.79 1.11L12 22h0a3.13 3.13 0 0 1-3-3.88Z"/>', 12),
  pin:      _SVG("0 0 24 24", '<path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z"/><circle cx="12" cy="10" r="3"/>', 14),
  retry:    _SVG("0 0 24 24", '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/>', 12),
  /* v12.2.0: task + trend icons */
  check:    _SVG("0 0 24 24", '<polyline points="20 6 9 17 4 12"/>', 14),
  plus:     _SVG("0 0 24 24", '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>', 14),
  trash:    _SVG("0 0 24 24", '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-2 14a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/><path d="M9 6V4a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/>', 12),
  clock:    _SVG("0 0 24 24", '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>', 12),
  flag:     _SVG("0 0 24 24", '<path d="M4 15s1-1 4-1 5 2 8 2 4-1 4-1V3s-1 1-4 1-5-2-8-2-4 1-4 1z"/><line x1="4" y1="22" x2="4" y2="15"/>', 12),
  trend:    _SVG("0 0 24 24", '<polyline points="23 6 13.5 15.5 8.5 10.5 1 18"/><polyline points="17 6 23 6 23 12"/>', 14),
  news:     _SVG("0 0 24 24", '<path d="M4 22h16a2 2 0 0 0 2-2V4a2 2 0 0 0-2-2H8a2 2 0 0 0-2 2v16a2 2 0 0 1-2 2zm0 0a2 2 0 0 1-2-2v-9c0-1.1.9-2 2-2h2"/><path d="M18 14h-8M15 18h-5M10 6h8v4h-8V6z"/>', 14),
  external: _SVG("0 0 24 24", '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/>', 10),
  sparkles: _SVG("0 0 24 24", '<path d="M12 3l1.9 5.8L20 10l-5.8 1.9L12 18l-1.9-5.8L4 10l5.8-1.9L12 3z"/><path d="M19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15z"/>', 12),
};

const SECTION_META = {
  ai_news:   { label: "AI 动向 / AI Trends" },
  it_news:   { label: "IT 行业 / Tech Industry" },
  intl_news: { label: "国际 / International" },
  cn_news:   { label: "国内 / National" },
};

const PRIORITY_LABELS = { high: "高", medium: "中", low: "低" };

/* ── class ─────────────────────────────────────────────────── */
class BriefDrawer {
  constructor(root) {
    this.root = root || document.body;
    this._open = false;
    this._loading = false;
    this._cached = null;
    this._expanded = false;
    this._expandedData = null;
    this._displayName = "伊塔";
    this._nameLoaded = false;
    this._render();
    this._bindEsc();
    this._bindBus();
  }

  _render() {
    this._backdrop = _el("div", { class: "brief-drawer-backdrop" });
    this._backdrop.addEventListener("click", () => this.close());
    this.root.appendChild(this._backdrop);

    this._drawer = _el("aside", {
      class: "brief-drawer brief-drawer--v122",
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
        <div class="brief-drawer__locpop-error" id="brief-drawer-locpop-error"></div>
        <div class="brief-drawer__locpop-hint">保存后会立刻重拉天气；空值则恢复为 IP 自动定位。</div>
      </div>
      <div class="brief-drawer__body" id="brief-drawer-body">
        <div class="brief-drawer__skeleton" id="brief-drawer-skeleton">
          <div class="brief-drawer__skeleton-card brief-drawer__skeleton-card--greet"></div>
          <div class="brief-drawer__skeleton-card brief-drawer__skeleton-card--todos"></div>
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

    this._drawer.querySelector("#brief-drawer-close").addEventListener("click", () => this.close());
    this._drawer.querySelector("#brief-drawer-refresh").addEventListener("click", () => this.refresh());

    /* Location popover */
    this._locBtn = this._drawer.querySelector("#brief-drawer-loc");
    this._locpop = this._drawer.querySelector("#brief-drawer-locpop");
    this._locpopInput = this._drawer.querySelector("#brief-drawer-locpop-input");
    this._locpopSave = this._drawer.querySelector("#brief-drawer-locpop-save");
    this._locpopError = this._drawer.querySelector("#brief-drawer-locpop-error");
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
      if (e.key === "Escape" && this._open) {
        if (this._locpop && this._locpop.classList.contains("is-open")) {
          this._closeLocPop();
        } else {
          this.close();
        }
      }
    });
    document.addEventListener("click", (e) => {
      if (!this._locpop || !this._locpop.classList.contains("is-open")) return;
      if (this._locpop.contains(e.target) || (this._locBtn && this._locBtn.contains(e.target))) return;
      this._closeLocPop();
    });
  }

  _bindBus() {
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
    this._ensureDisplayName();
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
    const hasVisibleContent = !!(this._cached && this._body().children.length > 0);
    if (!hasVisibleContent) this._showSkeleton();
    this._spinRefresh(true);
    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request) || null;
      if (!api) throw new Error("IPC not available");
      if (this._expanded) this._setExpanded(false, false);
      const r = await api({ method: "GET", path: "/api/brief/today" });
      const data = (r && r.data && r.data.brief) ? r.data.brief
                  : (r && r.data) ? r.data
                  : {};
      this._cached = Object.assign({}, data, { _ts: Date.now() });
      this._cached._limit = 3;
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
    this._nameLoaded = true;
    try {
      const api = (window.aerie && window.aerie.api && window.aerie.api.request);
      if (!api) return;
      const r = await api({ method: "GET", path: "/api/persona" });
      const data = (r && r.data) || {};
      const nm = (data.name || data.english_name || "").toString().trim();
      if (nm && nm !== this._displayName) {
        this._displayName = nm;
        if (this._cached) this._renderData(this._cached);
      }
    } catch (e) {
      console.warn("brief-drawer: persona fetch failed", e);
    }
  }

  _api() {
    return (window.aerie && window.aerie.api && window.aerie.api.request) || null;
  }

  /* Location popover helpers */
  _toggleLocPop() {
    if (!this._locpop) return;
    if (this._locpop.classList.contains("is-open")) {
      this._closeLocPop();
    } else {
      this._locpop.classList.add("is-open");
      this._locBtn && this._locBtn.classList.add("is-active");
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
    if (this._locpopError) {
      this._locpopError.textContent = "";
      this._locpopError.style.display = "none";
    }
    if (this._locpopSave) {
      this._locpopSave.disabled = true;
      this._locpopSave.textContent = "保存中...";
    }
    try {
      const api = this._api();
      if (!api) throw new Error("API not available");
      const r = await api({ method: "POST", path: "/api/location/set", body: { city } });
      if (r && r.error) throw new Error(r.error);
      this._closeLocPop();
      this.refresh();
    } catch (e) {
      console.warn("brief-drawer: location save failed", e);
      if (this._locpopError) {
        this._locpopError.textContent = "保存失败：" + (e.message || String(e));
        this._locpopError.style.display = "block";
      }
    } finally {
      if (this._locpopSave) {
        this._locpopSave.disabled = false;
        this._locpopSave.textContent = "保存";
      }
    }
  }

  _showSkeleton() {
    this._body().innerHTML = `
      <div class="brief-drawer__skeleton">
        <div class="brief-drawer__skeleton-card brief-drawer__skeleton-card--greet"></div>
        <div class="brief-drawer__skeleton-card brief-drawer__skeleton-card--todos"></div>
        <div class="brief-drawer__skeleton-card"></div>
        <div class="brief-drawer__skeleton-card"></div>
        <div class="brief-drawer__skeleton-dots"><span></span><span></span><span></span></div>
      </div>
    `;
  }

  /* ── main renderer ─────────────────────────────────── */
  _renderData(data) {
    const fragment = document.createDocumentFragment();

    /* 1. Greeting + date */
    fragment.appendChild(this._renderHeroGreeting(data));

    /* 2. Todos (core section) */
    fragment.appendChild(this._renderTodoSection(data));

    /* 3. Trends */
    fragment.appendChild(this._renderTrendSection(data.trends || []));

    /* 4. News (合并所有来源) */
    const allNews = [
      ...(data.ai_news || []).map(i => ({ ...i, _cat: "ai_news" })),
      ...(data.it_news || []).map(i => ({ ...i, _cat: "it_news" })),
      ...(data.intl_news || []).map(i => ({ ...i, _cat: "intl_news" })),
      ...(data.cn_news || []).map(i => ({ ...i, _cat: "cn_news" })),
    ];
    fragment.appendChild(this._renderNewsSection(allNews));

    /* 5. Weather (compact) */
    if (data.weather) fragment.appendChild(this._renderWeatherCompact(data.weather));

    this._body().innerHTML = "";
    this._body().appendChild(fragment);

    /* Bind weather section click after render */
    const weatherSection = this._body().querySelector(".brief-drawer__section--weather");
    if (weatherSection) {
      weatherSection.addEventListener("click", () => this._toggleLocPop());
    }
  }

  /* ── Section 1: Hero Greeting ─────────────────────── */
  _renderHeroGreeting(data) {
    const h = new Date().getHours();
    const timeLabel = h < 6 ? "凌晨" : h < 12 ? "早上" : h < 18 ? "下午" : "晚上";
    const greetingText = data.greeting || `${timeLabel}好呀，宝贝～今天也要加油哦`;

    const date = data.date || new Date().toISOString().slice(0, 10);
    const stats = data.todo_stats || { remaining: 0, total: 0, percent: 0 };
    const weather = data.weather || null;

    const hero = _el("div", { class: "brief-drawer__hero" });
    hero.innerHTML = `
      <div class="brief-drawer__hero-greet">
        <span class="brief-drawer__hero-sparkles">${_ICONS.sparkles}</span>
        <span class="brief-drawer__hero-text">${_esc(greetingText)}</span>
      </div>
      <div class="brief-drawer__hero-meta">
        <span class="brief-drawer__hero-date">
          ${_ICONS.calendar} <span>${_esc(date)}</span>
        </span>
        ${weather ? `
          <span class="brief-drawer__hero-weather">
            ${_ICONS.sun} <span>${_esc(weather.city || "")} ${_esc(weather.temp || "")}° ${_esc(weather.desc || "")}</span>
          </span>
        ` : ""}
        <span class="brief-drawer__hero-progress">
          ${_ICONS.flag} <span>${stats.remaining || 0} / ${stats.total || 0} 项待办</span>
        </span>
      </div>
    `;
    return hero;
  }

  /* ── Section 2: Todos (core) ──────────────────────── */
  _renderTodoSection(data) {
    const todos = data.todos || [];
    const stats = data.todo_stats || { total: 0, completed: 0, remaining: 0, percent: 0, high_priority_remaining: 0 };

    const section = _el("section", { class: "brief-drawer__section brief-drawer__section--todos" });

    /* Section header */
    const header = _el("div", { class: "brief-drawer__section-header" });
    header.innerHTML = `
      <div class="brief-drawer__section-title">
        ${_ICONS.flag} <span>今日待办</span>
        <span class="brief-drawer__section-badge">${stats.remaining || 0} 项</span>
      </div>
      <button class="brief-drawer__todo-add-btn" id="brief-drawer-todo-add" title="添加任务">
        ${_ICONS.plus} <span>添加</span>
      </button>
    `;
    section.appendChild(header);

    /* Progress bar */
    const progressWrap = _el("div", { class: "brief-drawer__progress-wrap" });
    const percent = stats.percent != null ? stats.percent : (stats.total ? Math.round((stats.completed / stats.total) * 100) : 0);
    progressWrap.innerHTML = `
      <div class="brief-drawer__progress-info">
        <span>完成进度</span>
        <span class="brief-drawer__progress-percent">${percent}%</span>
      </div>
      <div class="brief-drawer__progress-bar">
        <div class="brief-drawer__progress-fill" style="width: ${percent}%"></div>
      </div>
    `;
    section.appendChild(progressWrap);

    /* Todo list */
    const list = _el("div", { class: "brief-drawer__todo-list" });
    const sortedTodos = [...todos].sort((a, b) => {
      if (a.completed !== b.completed) return a.completed ? 1 : -1;
      const prio = { high: 0, medium: 1, low: 2 };
      return (prio[a.priority] ?? 1) - (prio[b.priority] ?? 1);
    });

    if (!sortedTodos.length) {
      list.appendChild(_el("div", { class: "brief-drawer__todo-empty" }, "今天还没有任务，添加一个吧～"));
    } else {
      for (const todo of sortedTodos) {
        list.appendChild(this._renderTodoCard(todo));
      }
    }

    /* Add form (hidden by default) */
    const addForm = _el("div", { class: "brief-drawer__todo-add-form", id: "brief-drawer-todo-form" });
    addForm.innerHTML = `
      <input type="text" class="brief-drawer__todo-input" id="brief-drawer-todo-input"
             placeholder="输入任务内容..." maxlength="120">
      <div class="brief-drawer__todo-add-row">
        <select class="brief-drawer__todo-priority" id="brief-drawer-todo-priority">
          <option value="high">高优先级</option>
          <option value="medium" selected>中优先级</option>
          <option value="low">低优先级</option>
        </select>
        <input type="time" class="brief-drawer__todo-due" id="brief-drawer-todo-due">
        <button class="brief-drawer__todo-save" id="brief-drawer-todo-save">保存</button>
        <button class="brief-drawer__todo-cancel" id="brief-drawer-todo-cancel">取消</button>
      </div>
    `;
    addForm.style.display = "none";
    section.appendChild(list);
    section.appendChild(addForm);

    /* Bind add button */
    setTimeout(() => {
      const addBtn = section.querySelector("#brief-drawer-todo-add");
      const form = section.querySelector("#brief-drawer-todo-form");
      const input = section.querySelector("#brief-drawer-todo-input");
      const saveBtn = section.querySelector("#brief-drawer-todo-save");
      const cancelBtn = section.querySelector("#brief-drawer-todo-cancel");

      if (addBtn && form) {
        addBtn.addEventListener("click", () => {
          form.style.display = form.style.display === "none" ? "block" : "none";
          if (form.style.display !== "none") setTimeout(() => input && input.focus(), 30);
        });
      }
      if (cancelBtn && form) {
        cancelBtn.addEventListener("click", () => {
          form.style.display = "none";
          if (input) input.value = "";
        });
      }
      if (saveBtn && input) {
        saveBtn.addEventListener("click", () => this._onAddTodo(section));
        input.addEventListener("keydown", (e) => {
          if (e.key === "Enter") { e.preventDefault(); this._onAddTodo(section); }
        });
      }
    }, 0);

    return section;
  }

  _renderTodoCard(todo) {
    const card = _el("div", {
      class: "brief-drawer__todo-card" +
        (todo.completed ? " is-done" : "") +
        ` brief-drawer__todo-card--${todo.priority || "medium"}`,
      "data-todo-id": todo.id,
    });

    const checkbox = _el("button", {
      class: "brief-drawer__todo-check",
      "aria-label": todo.completed ? "标记为未完成" : "标记为完成",
      html: todo.completed ? _ICONS.check : "",
    });
    checkbox.addEventListener("click", () => this._onToggleTodo(todo.id));

    const content = _el("div", { class: "brief-drawer__todo-content" });
    content.innerHTML = `
      <div class="brief-drawer__todo-title">${_esc(todo.title || "")}</div>
      <div class="brief-drawer__todo-meta">
        <span class="brief-drawer__todo-prio-tag brief-drawer__todo-prio-tag--${todo.priority || "medium"}">
          ${PRIORITY_LABELS[todo.priority] || "中"}
        </span>
        ${todo.due_time ? `
          <span class="brief-drawer__todo-due-time">
            ${_ICONS.clock} ${_esc(todo.due_time)}
          </span>
        ` : ""}
        ${todo.estimated_minutes ? `
          <span class="brief-drawer__todo-estimate">
            约 ${todo.estimated_minutes} 分钟
          </span>
        ` : ""}
      </div>
      ${todo.notes ? `<div class="brief-drawer__todo-notes">${_esc(todo.notes)}</div>` : ""}
    `;

    const delBtn = _el("button", {
      class: "brief-drawer__todo-delete",
      title: "删除任务",
      "aria-label": "删除任务",
      html: _ICONS.trash,
    });
    delBtn.addEventListener("click", (e) => {
      e.stopPropagation();
      this._onDeleteTodo(todo.id);
    });

    card.appendChild(checkbox);
    card.appendChild(content);
    card.appendChild(delBtn);
    return card;
  }

  async _onToggleTodo(todoId) {
    try {
      const api = this._api();
      if (!api) return;
      const r = await api({ method: "POST", path: `/api/todos/${todoId}/toggle` });
      if (r && r.data && r.data.todo && this._cached) {
        this._cached.todos = (this._cached.todos || []).map(t =>
          t.id === todoId ? r.data.todo : t
        );
        this._cached.todo_stats = await this._fetchStats();
        this._renderData(this._cached);
      }
    } catch (e) {
      console.warn("brief-drawer: toggle todo failed", e);
    }
  }

  async _onAddTodo(sectionEl) {
    const input = sectionEl.querySelector("#brief-drawer-todo-input");
    const prioritySel = sectionEl.querySelector("#brief-drawer-todo-priority");
    const dueInput = sectionEl.querySelector("#brief-drawer-todo-due");
    const form = sectionEl.querySelector("#brief-drawer-todo-form");
    const title = (input && input.value || "").trim();
    if (!title) return;

    try {
      const api = this._api();
      if (!api) return;
      const r = await api({
        method: "POST",
        path: "/api/todos",
        body: {
          title,
          priority: prioritySel ? prioritySel.value : "medium",
          due_time: dueInput && dueInput.value ? dueInput.value : null,
        },
      });
      if (r && r.data && r.data.todo && this._cached) {
        this._cached.todos = [...(this._cached.todos || []), r.data.todo];
        this._cached.todo_stats = await this._fetchStats();
        if (input) input.value = "";
        if (form) form.style.display = "none";
        this._renderData(this._cached);
      }
    } catch (e) {
      console.warn("brief-drawer: add todo failed", e);
    }
  }

  async _onDeleteTodo(todoId) {
    try {
      const api = this._api();
      if (!api) return;
      await api({ method: "DELETE", path: `/api/todos/${todoId}` });
      if (this._cached) {
        this._cached.todos = (this._cached.todos || []).filter(t => t.id !== todoId);
        this._cached.todo_stats = await this._fetchStats();
        this._renderData(this._cached);
      }
    } catch (e) {
      console.warn("brief-drawer: delete todo failed", e);
    }
  }

  async _fetchStats() {
    try {
      const api = this._api();
      if (!api) return { total: 0, completed: 0, remaining: 0, percent: 0 };
      const r = await api({ method: "GET", path: "/api/todos" });
      return (r && r.data && r.data.stats) || { total: 0, completed: 0, remaining: 0, percent: 0 };
    } catch (e) {
      return { total: 0, completed: 0, remaining: 0, percent: 0 };
    }
  }

  /* ── Section 3: Trends ────────────────────────────── */
  _renderTrendSection(trends) {
    const section = _el("section", { class: "brief-drawer__section brief-drawer__section--trends" });
    const header = _el("div", { class: "brief-drawer__section-header" });
    header.innerHTML = `
      <div class="brief-drawer__section-title">
        ${_ICONS.trend} <span>今日趋势</span>
        <span class="brief-drawer__section-badge">${trends.length} 条</span>
      </div>
    `;
    section.appendChild(header);

    const list = _el("div", { class: "brief-drawer__trend-list" });
    if (!trends.length) {
      list.appendChild(_el("div", { class: "brief-drawer__trend-empty" }, "暂无趋势数据"));
    } else {
      for (const t of trends) {
        const item = _el("div", { class: "brief-drawer__trend-item" });
        const kws = (t.keywords || []).slice(0, 3).map(k =>
          `<span class="brief-drawer__trend-tag">${_esc(k)}</span>`
        ).join("");
        item.innerHTML = `
          <div class="brief-drawer__trend-title">${_esc(t.title || "")}</div>
          <div class="brief-drawer__trend-summary">${_esc(t.summary || "")}</div>
          ${kws ? `<div class="brief-drawer__trend-tags">${kws}</div>` : ""}
        `;
        list.appendChild(item);
      }
    }
    section.appendChild(list);
    return section;
  }

  /* ── Section 4: News ──────────────────────────────── */
  _renderNewsSection(newsItems) {
    const section = _el("section", { class: "brief-drawer__section brief-drawer__section--news" });
    const header = _el("div", { class: "brief-drawer__section-header" });
    header.innerHTML = `
      <div class="brief-drawer__section-title">
        ${_ICONS.news} <span>新闻资讯</span>
        <span class="brief-drawer__section-badge">${newsItems.length} 条</span>
      </div>
    `;
    section.appendChild(header);

    const list = _el("div", { class: "brief-drawer__news-list" });
    if (!newsItems.length) {
      list.appendChild(_el("div", { class: "brief-drawer__news-empty" }, "暂无新闻"));
    } else {
      const displayLimit = this._expanded ? 12 : 6;
      for (const item of newsItems.slice(0, displayLimit)) {
        list.appendChild(this._renderNewsItem(item));
      }
    }
    section.appendChild(list);
    return section;
  }

  _renderNewsItem(item) {
    const a = _el("div", { class: "brief-drawer__news-item" });
    const cat = item._cat || "";
    const catLabel = SECTION_META[cat] ? SECTION_META[cat].label.split(" / ")[0] : "";
    const summary = item.summary || item.description || item.content || "";
    const shortSummary = summary.length > 120 ? summary.slice(0, 120) + "..." : summary;

    a.innerHTML = `
      ${catLabel ? `<span class="brief-drawer__news-cat">${_esc(catLabel)}</span>` : ""}
      <div class="brief-drawer__news-title">${_esc(item.title || "")}</div>
      ${shortSummary ? `<div class="brief-drawer__news-summary">${_esc(shortSummary)}</div>` : ""}
      ${item.url ? `
        <a class="brief-drawer__news-link" href="${_esc(item.url)}" target="_blank" rel="noopener">
          查看原文 ${_ICONS.external}
        </a>
      ` : ""}
    `;
    return a;
  }

  /* ── Section 5: Weather (compact) ─────────────────── */
  _renderWeatherCompact(weather) {
    const section = _el("section", {
      class: "brief-drawer__section brief-drawer__section--weather",
    });
    const w = weather || {};
    const manualTag = w.manual ? "已设" : "自动";
    section.innerHTML = `
      <div class="brief-drawer__weather-compact">
        <span class="brief-drawer__weather-icon">${_ICONS.pin}</span>
        <span class="brief-drawer__weather-city">${_esc(w.city || "定位中")}</span>
        <span class="brief-drawer__weather-tag">· ${_esc(manualTag)}</span>
        <span class="brief-drawer__weather-temp">${_esc(w.temp || "—")}°</span>
        <span class="brief-drawer__weather-desc">${_esc(w.desc || "")}</span>
        ${w.suggestion ? `<span class="brief-drawer__weather-sug">· ${_esc(w.suggestion)}</span>` : ""}
        <span class="brief-drawer__weather-edit">点击更改</span>
      </div>
    `;
    return section;
  }

  /* ── error ────────────────────────────────────────── */
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

  /* ── expand / collapse ───────────────────────────── */
  async _toggleExpanded() {
    if (this._expanded) {
      this._setExpanded(false, false);
      return;
    }
    this._setExpanded(true, false);
    this._showSkeleton();
    try {
      const api = this._api();
      if (!api) throw new Error("IPC not available");
      const r = await api({
        method: "POST",
        path: "/api/brief/run?limit=8",
        body: { limit: 8 },
      });
      const data = (r && r.data && r.data.brief) ? r.data.brief
                  : (r && r.data) ? r.data
                  : {};
      this._expandedData = Object.assign({}, data, { _ts: Date.now() });
      this._expandedData._limit = 8;
      this._renderData(this._expandedData);
    } catch (e) {
      console.warn("brief-drawer: expand failed", e);
      this._renderError("展开失败 / Expand failed: " + (e.message || String(e)));
      this._setExpanded(false, false);
    }
  }

  _setExpanded(on, redraw) {
    this._expanded = !!on;
    this._drawer.classList.toggle("brief-drawer--expanded", this._expanded);
    this._expandBtn.classList.toggle("is-expanded", this._expanded);
    this._expandLabel.textContent = this._expanded ? "收起" : "展开完整";
    const svg = this._expandBtn.querySelector("svg");
    if (svg) {
      const newIcon = this._expanded ? _ICONS.collapse : _ICONS.expand;
      svg.outerHTML = newIcon;
    }
    if (redraw !== false && (this._cached || this._expandedData)) {
      this._renderData(this._expanded ? (this._expandedData || this._cached) : this._cached);
    }
  }
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
