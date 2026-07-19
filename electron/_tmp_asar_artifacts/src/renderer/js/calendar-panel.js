"use strict";
/* Calendar Panel — v12.0.1
 * 日历 / 纪念日 / 日程 / 倒计时 / 日志
 */

class CalendarPanel {
  constructor() {
    this._currentDate = new Date();
    this._selectedDate = new Date();
    this._events = [];
    this._filterType = "all";
    this._editingId = null;
    this._selectedColor = "#ff9a9e";
    this._init();
  }

  _init() {
    this._bindEvents();
    this._renderMonth();
    this._loadEvents();
    this._loadStats();
  }

  _bindEvents() {
    const prevBtn = document.getElementById("cal-prev-month");
    const nextBtn = document.getElementById("cal-next-month");
    const todayBtn = document.getElementById("cal-today-btn");
    const addBtn = document.getElementById("cal-add-btn");
    const saveBtn = document.getElementById("cal-save-btn");
    const cancelBtn = document.getElementById("cal-cancel-btn");
    const deleteBtn = document.getElementById("cal-delete-btn");
    const colorPicker = document.getElementById("cal-color-picker");

    if (prevBtn) prevBtn.addEventListener("click", () => this._prevMonth());
    if (nextBtn) nextBtn.addEventListener("click", () => this._nextMonth());
    if (todayBtn) todayBtn.addEventListener("click", () => this._goToday());
    if (addBtn) addBtn.addEventListener("click", () => this._openModal());
    if (saveBtn) saveBtn.addEventListener("click", () => this._saveEvent());
    if (cancelBtn) cancelBtn.addEventListener("click", () => this._closeModal());
    if (deleteBtn) deleteBtn.addEventListener("click", () => this._deleteEvent());

    const modal = document.getElementById("cal-event-modal");
    if (modal) {
      modal.querySelectorAll("[data-close]").forEach((el) => {
        el.addEventListener("click", () => this._closeModal());
      });
    }

    if (colorPicker) {
      colorPicker.querySelectorAll(".cal-color-dot").forEach((dot) => {
        dot.addEventListener("click", () => {
          const color = dot.dataset.color;
          this._selectedColor = color;
          colorPicker.querySelectorAll(".cal-color-dot").forEach((d) => d.classList.remove("active"));
          dot.classList.add("active");
        });
      });
    }

    const filters = document.querySelectorAll(".cal-filter-btn");
    filters.forEach((btn) => {
      btn.addEventListener("click", () => {
        this._filterType = btn.dataset.type;
        filters.forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        this._renderEventList();
      });
    });
  }

  _prevMonth() {
    this._currentDate.setMonth(this._currentDate.getMonth() - 1);
    this._renderMonth();
    this._loadEvents();
  }

  _nextMonth() {
    this._currentDate.setMonth(this._currentDate.getMonth() + 1);
    this._renderMonth();
    this._loadEvents();
  }

  _goToday() {
    this._currentDate = new Date();
    this._selectedDate = new Date();
    this._renderMonth();
    this._loadEvents();
  }

  _renderMonth() {
    const grid = document.getElementById("cal-grid");
    const titleEl = document.getElementById("cal-month-title");
    if (!grid) return;

    const year = this._currentDate.getFullYear();
    const month = this._currentDate.getMonth();
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const startDay = firstDay.getDay();
    const totalDays = lastDay.getDate();

    if (titleEl) {
      titleEl.textContent = `${year}年 ${month + 1}月`;
    }

    let html = "";
    const today = new Date();
    const todayStr = this._dateStr(today);
    const selectedStr = this._dateStr(this._selectedDate);

    const prevMonth = new Date(year, month, 0);
    const prevDays = prevMonth.getDate();
    for (let i = startDay - 1; i >= 0; i--) {
      const day = prevDays - i;
      html += `<div class="cal-day cal-day--other">${day}</div>`;
    }

    for (let day = 1; day <= totalDays; day++) {
      const dateStr = `${year}-${String(month + 1).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
      const isToday = dateStr === todayStr;
      const isSelected = dateStr === selectedStr;
      const dayEvents = this._getDayEvents(dateStr);
      const hasEvents = dayEvents.length > 0;
      const dots = dayEvents.slice(0, 3).map((e) =>
        `<span class="cal-event-dot" style="background:${e.color || "#ff9a9e"}"></span>`
      ).join("");

      html += `
        <div class="cal-day ${isToday ? "cal-day--today" : ""} ${isSelected ? "cal-day--selected" : ""}"
             data-date="${dateStr}">
          <span class="cal-day-num">${day}</span>
          ${hasEvents ? `<div class="cal-day-dots">${dots}</div>` : ""}
        </div>
      `;
    }

    const remaining = 42 - (startDay + totalDays);
    for (let i = 1; i <= remaining; i++) {
      html += `<div class="cal-day cal-day--other">${i}</div>`;
    }

    grid.innerHTML = html;

    grid.querySelectorAll(".cal-day[data-date]").forEach((el) => {
      el.addEventListener("click", () => {
        const dateStr = el.dataset.date;
        this._selectedDate = new Date(dateStr + "T00:00:00");
        this._renderMonth();
        this._renderEventList();
      });
    });
  }

  _getDayEvents(dateStr) {
    return this._events.filter((e) => {
      const start = e.start_time ? e.start_time.split("T")[0] : "";
      return start === dateStr;
    });
  }

  async _loadEvents() {
    try {
      const year = this._currentDate.getFullYear();
      const month = this._currentDate.getMonth();
      const start = `${year}-${String(month + 1).padStart(2, "0")}-01T00:00:00`;
      const endDate = new Date(year, month + 1, 0);
      const end = `${year}-${String(month + 1).padStart(2, "0")}-${endDate.getDate()}T23:59:59`;

      const r = await window.aerie.api.request({
        method: "GET",
        path: `/api/calendar/events?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
      });
      this._events = (r.data && r.data.events) || [];
      this._renderMonth();
      this._renderEventList();
    } catch (e) {
      console.warn("[calendar] load events failed", e);
    }
  }

  async _loadStats() {
    try {
      const [companionR, statsR] = await Promise.all([
        window.aerie.api.request({ method: "GET", path: "/api/calendar/companion" }).catch(() => null),
        window.aerie.api.request({ method: "GET", path: "/api/calendar/stats" }).catch(() => null),
      ]);

      const companion = (companionR && companionR.data) || {};
      const stats = (statsR && statsR.data) || {};

      const daysEl = document.getElementById("cal-days-together");
      const userEl = document.getElementById("cal-user-msgs");
      const compEl = document.getElementById("cal-companion-msgs");
      const totalEl = document.getElementById("cal-total-events");

      if (daysEl) daysEl.textContent = companion.days_together != null ? companion.days_together : 0;
      if (userEl) userEl.textContent = companion.user_messages != null ? companion.user_messages : 0;
      if (compEl) compEl.textContent = companion.companion_messages != null ? companion.companion_messages : 0;
      if (totalEl) totalEl.textContent = stats.total != null ? stats.total : 0;
    } catch (e) {
      console.warn("[calendar] load stats failed", e);
    }
  }

  _renderEventList() {
    const listEl = document.getElementById("cal-events-list");
    const titleEl = document.getElementById("cal-events-date");
    if (!listEl) return;

    const dateStr = this._dateStr(this._selectedDate);
    if (titleEl) {
      const todayStr = this._dateStr(new Date());
      const prefix = dateStr === todayStr ? "今天 · " : "";
      titleEl.textContent = `${prefix}${dateStr} 的事件`;
    }

    let events = this._getDayEvents(dateStr);
    if (this._filterType !== "all") {
      events = events.filter((e) => e.event_type === this._filterType);
    }

    if (!events.length) {
      listEl.innerHTML = `<div class="cal-empty">这一天还没有事件，点击右上角添加～</div>`;
      return;
    }

    const typeMap = {
      anniversary: { label: "纪念日", cls: "anniversary" },
      schedule: { label: "日程", cls: "schedule" },
      countdown: { label: "倒计时", cls: "countdown" },
      journal: { label: "日志", cls: "journal" },
      reminder: { label: "提醒", cls: "reminder" },
    };

    listEl.innerHTML = events.map((e) => {
      const t = typeMap[e.event_type] || typeMap.schedule;
      const time = e.start_time ? e.start_time.split("T")[1]?.slice(0, 5) || "全天" : "全天";
      return `
        <div class="cal-event-item" data-id="${e.id}" style="border-left-color:${e.color || "#ff9a9e"}">
          <div class="cal-event-time">${time}</div>
          <div class="cal-event-body">
            <div class="cal-event-title">${this._escape(e.title)}</div>
            ${e.description ? `<div class="cal-event-desc">${this._escape(e.description)}</div>` : ""}
          </div>
          <span class="cal-event-type cal-event-type--${t.cls}">${t.label}</span>
        </div>
      `;
    }).join("");

    listEl.querySelectorAll(".cal-event-item").forEach((el) => {
      el.addEventListener("click", () => {
        const id = parseInt(el.dataset.id, 10);
        const event = this._events.find((e) => e.id === id);
        if (event) this._openModal(event);
      });
    });
  }

  _openModal(event = null) {
    const modal = document.getElementById("cal-event-modal");
    const titleEl = document.getElementById("cal-modal-title");
    const deleteBtn = document.getElementById("cal-delete-btn");
    if (!modal) return;

    this._editingId = event ? event.id : null;

    if (titleEl) titleEl.textContent = event ? "编辑事件" : "添加事件";
    if (deleteBtn) deleteBtn.style.display = event ? "block" : "none";

    const titleInput = document.getElementById("cal-form-title");
    const typeInput = document.getElementById("cal-form-type");
    const dateInput = document.getElementById("cal-form-date");
    const timeInput = document.getElementById("cal-form-time");
    const descInput = document.getElementById("cal-form-desc");

    if (event) {
      if (titleInput) titleInput.value = event.title || "";
      if (typeInput) typeInput.value = event.event_type || "schedule";
      if (dateInput && event.start_time) dateInput.value = event.start_time.split("T")[0];
      if (timeInput && event.start_time) {
        const t = event.start_time.split("T")[1];
        if (t) timeInput.value = t.slice(0, 5);
      }
      if (descInput) descInput.value = event.description || "";
      this._selectedColor = event.color || "#ff9a9e";
    } else {
      if (titleInput) titleInput.value = "";
      if (typeInput) typeInput.value = "schedule";
      if (dateInput) dateInput.value = this._dateStr(this._selectedDate);
      if (timeInput) timeInput.value = "";
      if (descInput) descInput.value = "";
      this._selectedColor = "#ff9a9e";
    }

    const colorPicker = document.getElementById("cal-color-picker");
    if (colorPicker) {
      colorPicker.querySelectorAll(".cal-color-dot").forEach((dot) => {
        dot.classList.toggle("active", dot.dataset.color === this._selectedColor);
      });
    }

    modal.classList.remove("hidden");
  }

  _closeModal() {
    const modal = document.getElementById("cal-event-modal");
    if (modal) modal.classList.add("hidden");
    this._editingId = null;
  }

  async _saveEvent() {
    const title = document.getElementById("cal-form-title")?.value.trim();
    const type = document.getElementById("cal-form-type")?.value;
    const date = document.getElementById("cal-form-date")?.value;
    const time = document.getElementById("cal-form-time")?.value;
    const desc = document.getElementById("cal-form-desc")?.value.trim();

    if (!title) {
      alert("请输入事件名称");
      return;
    }
    if (!date) {
      alert("请选择日期");
      return;
    }

    const start_time = time ? `${date}T${time}:00` : `${date}T00:00:00`;
    const all_day = !time ? 1 : 0;

    try {
      if (this._editingId) {
        await window.aerie.api.request({
          method: "PUT",
          path: `/api/calendar/events/${this._editingId}`,
          body: JSON.stringify({
            title,
            event_type: type,
            start_time,
            all_day,
            description: desc,
            color: this._selectedColor,
          }),
          headers: { "Content-Type": "application/json" },
        });
      } else {
        await window.aerie.api.request({
          method: "POST",
          path: "/api/calendar/events",
          body: JSON.stringify({
            title,
            event_type: type,
            start_time,
            all_day,
            description: desc,
            color: this._selectedColor,
            source: "manual",
          }),
          headers: { "Content-Type": "application/json" },
        });
      }
      this._closeModal();
      this._loadEvents();
      this._loadStats();
    } catch (e) {
      alert("保存失败: " + e.message);
    }
  }

  async _deleteEvent() {
    if (!this._editingId) return;
    if (!confirm("确定要删除这个事件吗？")) return;
    try {
      await window.aerie.api.request({
        method: "DELETE",
        path: `/api/calendar/events/${this._editingId}`,
      });
      this._closeModal();
      this._loadEvents();
      this._loadStats();
    } catch (e) {
      alert("删除失败: " + e.message);
    }
  }

  _dateStr(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, "0");
    const day = String(d.getDate()).padStart(2, "0");
    return `${y}-${m}-${day}`;
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

window.addEventListener("DOMContentLoaded", () => {
  window._calendarPanel = new CalendarPanel();
});
