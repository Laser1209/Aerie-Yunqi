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
    this._requestVersion = 0;
    this._loading = false;
    this._error = "";
    this._init();
  }

  _init() {
    this._bindEvents();
    this._renderMonth();
    this._loadEvents();
    this._loadStats();
    if (window.aerie.api.onMessage) {
      window.aerie.api.onMessage((event) => {
        if (event && event.type === "timeline_changed") this._loadEvents();
        if (event && event.type === "calendar_reminder") this._handleCalendarReminder(event);
      });
    }
  }

  _handleCalendarReminder(event) {
    const title = event.title || "日程提醒";
    const start = event.start_time ? event.start_time.replace("T", " ").slice(0, 16) : "";
    const desc = event.description || (start ? `${start} 开始` : "你有一个日程即将开始");
    window.aerie.dynamicIsland?.notify?.({ title, desc, icon: "ui-calendar", type: "calendar_reminder" });
    window.aerie.dynamicIsland?.systemNotify?.({ title: `日程提醒：${title}`, body: desc }).catch?.(() => {});
    this._loadEvents();
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
    const allDayInput = document.getElementById("cal-form-all-day");

    if (prevBtn) prevBtn.addEventListener("click", () => this._prevMonth());
    if (nextBtn) nextBtn.addEventListener("click", () => this._nextMonth());
    if (todayBtn) todayBtn.addEventListener("click", () => this._goToday());
    if (addBtn) addBtn.addEventListener("click", () => this._openModal());
    if (saveBtn) saveBtn.addEventListener("click", () => this._saveEvent());
    if (cancelBtn) cancelBtn.addEventListener("click", () => this._closeModal());
    if (deleteBtn) deleteBtn.addEventListener("click", () => this._deleteEvent());
    if (allDayInput) allDayInput.addEventListener("change", () => this._syncAllDayFields());

    const modal = document.getElementById("cal-event-modal");
    if (modal) {
      modal.querySelectorAll("[data-close]").forEach((el) => {
        el.addEventListener("click", () => this._closeModal());
      });
    }

    if (colorPicker) {
      colorPicker.querySelectorAll(".cal-color-dot").forEach((dot) => {
        dot.addEventListener("change", () => {
          if (!dot.checked) return;
          this._selectedColor = dot.dataset.color;
          colorPicker.querySelectorAll(".cal-color-dot").forEach((d) => d.classList.toggle("active", d === dot));
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
      const labels = dayEvents.slice(0, 2).map((e) => `<span class="cal-day-label">${this._escape(e.title).slice(0, 8)}</span>`).join("");
      const overflow = dayEvents.length > 2 ? `<span class="cal-day-more">+${dayEvents.length - 2}</span>` : "";

      html += `
        <div class="cal-day ${isToday ? "cal-day--today" : ""} ${isSelected ? "cal-day--selected" : ""}"
             data-date="${dateStr}">
          <span class="cal-day-num">${day}</span>
          <div class="cal-day-items">${labels}${overflow}</div>
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

      const version = ++this._requestVersion;
      this._loading = true;
      const r = await window.aerie.api.request({
        method: "GET",
        path: `/api/calendar/timeline?start=${encodeURIComponent(start)}&end=${encodeURIComponent(end)}`,
      });
      if (version !== this._requestVersion) return;
      const data = this._requireResponse(r, "加载议程失败");
      if (!Array.isArray(data.items)) throw new Error("加载议程失败：返回数据格式不正确");
      this._events = data.items;
      this._loading = false;
      this._error = "";
      this._renderMonth();
      this._renderEventList();
      this._renderLocalStats();
    } catch (e) {
      this._loading = false;
      this._error = e.message || "加载失败";
      this._renderEventList();
      console.warn("[calendar] load events failed", e);
    }
  }

  async _loadStats() {
    try {
      const companionR = await window.aerie.api.request({ method: "GET", path: "/api/calendar/companion" });
      const companion = this._requireResponse(companionR, "加载相伴数据失败");
      const daysEl = document.getElementById("cal-days-together");
      if (daysEl) daysEl.textContent = companion.days_together != null ? companion.days_together : 0;
    } catch (e) {
      console.warn("[calendar] load stats failed", e);
    }
  }

  _renderLocalStats() {
    const todayEl = document.getElementById("cal-today-count");
    const pendingEl = document.getElementById("cal-pending-count");
    const anniversaryEl = document.getElementById("cal-anniversary-count");
    const today = this._dateStr(new Date());
    if (todayEl) todayEl.textContent = this._getDayEvents(today).length;
    if (pendingEl) pendingEl.textContent = this._events.filter((item) => item.kind === "todo" && !item.completed).length;
    if (anniversaryEl) anniversaryEl.textContent = this._events.filter((item) => item.type === "anniversary").length;
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

    if (this._loading) { listEl.innerHTML = `<div class="cal-empty">正在加载议程…</div>`; return; }
    if (this._error) { listEl.innerHTML = `<div class="cal-inline-error">${this._escape(this._error)}</div>`; return; }
    let events = this._getDayEvents(dateStr);
    if (this._filterType !== "all") {
      events = events.filter((e) => this._filterType === "todo" ? e.kind === "todo" : e.type === this._filterType);
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
      const t = e.kind === "todo" ? { label: "任务", cls: "todo" } : (typeMap[e.type] || typeMap.schedule);
      const time = e.all_day ? "全天" : (e.start_time ? e.start_time.split("T")[1]?.slice(0, 5) || "全天" : "全天");
      return `
        <div class="cal-event-item ${e.completed ? "is-completed" : ""}" data-id="${e.id}">
          <div class="cal-event-time">${time}</div>
          ${e.kind === "todo" ? `<button class="cal-todo-toggle" aria-label="切换任务完成">${e.completed ? "已完成" : "待办"}</button>` : ""}
          <div class="cal-event-body">
            <div class="cal-event-title">${this._escape(e.title)}</div>
            ${e.description ? `<div class="cal-event-desc">${this._escape(e.description)}</div>` : ""}
          </div>
          <span class="cal-event-type cal-event-type--${t.cls}">${t.label}</span>
        </div>
      `;
    }).join("");

    listEl.querySelectorAll(".cal-todo-toggle").forEach((button) => {
      button.addEventListener("click", async (event) => {
        event.stopPropagation();
        const item = button.closest(".cal-event-item");
        const id = item.dataset.id.replace("todo:", "");
        const response = await window.aerie.api.request({ method: "POST", path: `/api/todos/${encodeURIComponent(id)}/toggle` });
        const data = this._requireResponse(response, "更新任务失败");
        if (data.status && data.status !== "ok") throw new Error(data.error || "更新任务失败");
        this._loadEvents();
      });
    });
    listEl.querySelectorAll(".cal-event-item").forEach((el) => {
      el.addEventListener("click", () => {
        if (el.dataset.id.startsWith("todo:")) return;
        const id = parseInt(el.dataset.id.replace("event:", ""), 10);
        if (Number.isInteger(id)) this._openEventForEdit(id);
      });
    });
  }

  async _openEventForEdit(id) {
    this._openModal();
    this._editingId = id;
    const modalTitle = document.getElementById("cal-modal-title");
    const saveBtn = document.getElementById("cal-save-btn");
    if (modalTitle) modalTitle.textContent = "编辑事件";
    if (saveBtn) saveBtn.disabled = true;
    this._showFormError("正在加载事件详情…");
    let loaded = false;

    try {
      const response = await window.aerie.api.request({
        method: "GET",
        path: `/api/calendar/events/${encodeURIComponent(id)}`,
      });
      const event = this._requireResponse(response, "加载事件详情失败");
      if (!event.id || !event.start_time) throw new Error("加载事件详情失败：返回数据不完整");
      if (this._editingId !== id) return;
      this._openModal(event);
      loaded = true;
    } catch (error) {
      if (this._editingId === id) this._showFormError(error.message || "加载事件详情失败");
    } finally {
      if (loaded && this._editingId === id && saveBtn) saveBtn.disabled = false;
    }
  }

  _openModal(event = null) {
    const modal = document.getElementById("cal-event-modal");
    const titleEl = document.getElementById("cal-modal-title");
    const deleteBtn = document.getElementById("cal-delete-btn");
    if (!modal) return;

    this._editingId = event ? event.id : null;
    if (titleEl) titleEl.textContent = event ? "编辑事件" : "添加事件";
    if (deleteBtn) deleteBtn.style.display = event ? "block" : "none";
    this._showFormError("");

    const startParts = this._dateTimeParts(event && event.start_time);
    const endParts = this._dateTimeParts(event && event.end_time);
    const selectedDate = this._dateStr(this._selectedDate);
    const values = {
      "cal-form-title": event ? event.title || "" : "",
      "cal-form-type": event ? event.event_type || "schedule" : "schedule",
      "cal-form-date": startParts.date || selectedDate,
      "cal-form-time": startParts.time || "09:00",
      "cal-form-end-date": endParts.date || startParts.date || selectedDate,
      "cal-form-end-time": endParts.time || "10:00",
      "cal-form-repeat": event ? event.repeat_type || "none" : "none",
      "cal-form-remind": String(event && event.remind_before != null ? event.remind_before : -1),
      "cal-form-desc": event ? event.description || "" : "",
    };
    Object.entries(values).forEach(([id, value]) => {
      const input = document.getElementById(id);
      if (input) input.value = value;
    });

    const allDayInput = document.getElementById("cal-form-all-day");
    if (allDayInput) allDayInput.checked = Boolean(event && Number(event.all_day));
    this._selectedColor = event && event.color || "#ff9a9e";
    const colorPicker = document.getElementById("cal-color-picker");
    if (colorPicker) {
      colorPicker.querySelectorAll(".cal-color-dot").forEach((dot) => {
        const selected = dot.dataset.color === this._selectedColor;
        dot.checked = selected;
        dot.classList.toggle("active", selected);
      });
    }

    this._syncAllDayFields();
    modal.classList.remove("hidden");
    document.getElementById("cal-form-title")?.focus();
  }

  _closeModal() {
    const modal = document.getElementById("cal-event-modal");
    if (modal) modal.classList.add("hidden");
    this._editingId = null;
    this._showFormError("");
  }

  _syncAllDayFields() {
    const allDay = Boolean(document.getElementById("cal-form-all-day")?.checked);
    document.querySelectorAll(".cal-time-field").forEach((field) => field.classList.toggle("is-all-day", allDay));
    ["cal-form-time", "cal-form-end-time"].forEach((id) => {
      const input = document.getElementById(id);
      if (input) input.disabled = allDay;
    });
  }

  async _saveEvent() {
    const fields = {
      title: document.getElementById("cal-form-title"),
      date: document.getElementById("cal-form-date"),
      time: document.getElementById("cal-form-time"),
      endDate: document.getElementById("cal-form-end-date"),
      endTime: document.getElementById("cal-form-end-time"),
    };
    const title = fields.title?.value.trim();
    const type = document.getElementById("cal-form-type")?.value;
    const date = fields.date?.value;
    const time = fields.time?.value;
    const endDate = fields.endDate?.value;
    const endTime = fields.endTime?.value;
    const allDay = Boolean(document.getElementById("cal-form-all-day")?.checked);
    const repeatType = document.getElementById("cal-form-repeat")?.value;
    const remindBefore = Number(document.getElementById("cal-form-remind")?.value);
    const description = document.getElementById("cal-form-desc")?.value.trim();

    const invalid = [];
    let validationError = "";
    if (!title) { invalid.push(fields.title); validationError = "请输入事件名称"; }
    else if (!date) { invalid.push(fields.date); validationError = "请选择开始日期"; }
    else if (!endDate) { invalid.push(fields.endDate); validationError = "请选择结束日期"; }
    else if (!allDay && !time) { invalid.push(fields.time); validationError = "请选择开始时间"; }
    else if (!allDay && !endTime) { invalid.push(fields.endTime); validationError = "请选择结束时间"; }

    const startTime = date ? `${date}T${allDay ? "00:00:00" : `${time}:00`}` : "";
    const endTimeValue = endDate ? `${endDate}T${allDay ? "23:59:59" : `${endTime}:00`}` : "";
    if (!validationError && endTimeValue < startTime) {
      invalid.push(fields.date, fields.time, fields.endDate, fields.endTime);
      validationError = "结束时间不能早于开始时间";
    }
    if (validationError) {
      this._showFormError(validationError, invalid);
      invalid[0]?.focus();
      return;
    }

    const payload = {
      title,
      event_type: type,
      start_time: startTime,
      end_time: endTimeValue,
      all_day: allDay ? 1 : 0,
      repeat_type: repeatType,
      remind_before: remindBefore,
      description,
      color: this._selectedColor,
    };
    if (!this._editingId) payload.source = "manual";

    const saveBtn = document.getElementById("cal-save-btn");
    const originalText = saveBtn ? saveBtn.textContent : "保存";
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = "保存中…"; }
    this._showFormError("");
    try {
      const response = await window.aerie.api.request({
        method: this._editingId ? "PUT" : "POST",
        path: this._editingId ? `/api/calendar/events/${encodeURIComponent(this._editingId)}` : "/api/calendar/events",
        body: JSON.stringify(payload),
        headers: { "Content-Type": "application/json" },
      });
      const data = this._requireResponse(response, "保存失败");
      if (data.status !== "ok") throw new Error(data.error || "保存失败：服务端未确认成功");
      this._closeModal();
      this._loadEvents();
      this._loadStats();
    } catch (error) {
      this._showFormError(error.message || "保存失败");
    } finally {
      if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = originalText; }
    }
  }

  async _deleteEvent() {
    if (!this._editingId || !confirm("确定要删除这个事件吗？")) return;
    try {
      const response = await window.aerie.api.request({
        method: "DELETE",
        path: `/api/calendar/events/${encodeURIComponent(this._editingId)}`,
      });
      const data = this._requireResponse(response, "删除失败");
      if (data.status !== "ok") throw new Error(data.error || "删除失败：服务端未确认成功");
      this._closeModal();
      this._loadEvents();
      this._loadStats();
    } catch (error) {
      this._showFormError(error.message || "删除失败");
    }
  }

  _showFormError(message, invalidFields = []) {
    const errorEl = document.getElementById("cal-form-error");
    document.querySelectorAll("#cal-event-modal .is-invalid").forEach((field) => field.classList.remove("is-invalid"));
    invalidFields.filter(Boolean).forEach((field) => field.classList.add("is-invalid"));
    if (errorEl) {
      errorEl.hidden = !message;
      errorEl.textContent = message;
    }
  }

  _requireResponse(response, fallback) {
    if (!response || !Number.isInteger(response.status) || response.status < 200 || response.status >= 300) {
      const detail = response && response.data && (response.data.error || response.data.detail);
      throw new Error(detail ? `${fallback}：${detail}` : fallback);
    }
    if (!response.data || typeof response.data !== "object") throw new Error(`${fallback}：返回数据格式不正确`);
    if (response.data.error) throw new Error(`${fallback}：${response.data.error}`);
    return response.data;
  }

  _dateTimeParts(value) {
    if (!value) return { date: "", time: "" };
    const parts = String(value).split("T");
    return { date: parts[0] || "", time: parts[1] ? parts[1].slice(0, 5) : "" };
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
