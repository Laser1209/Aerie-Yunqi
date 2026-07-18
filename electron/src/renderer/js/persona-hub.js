"use strict";
/* v13.0: Persona Hub — 人设管理面板（可视化编辑器） */

class PersonaHubPanel {
  constructor() {
    this._personas = [];
    this._activeId = null;
    this._currentId = null;
    this._viewMode = "list"; // "list" | "editor"
  }

  init() {
    const panel = document.getElementById("panel-persona-hub");
    if (!panel) return;

    this._buildDom(panel);
    this._bindEvents(panel);
    this._loadList();
  }

  _buildDom(panel) {
    if (panel.querySelector(".persona-hub__container")) return;

    panel.innerHTML = `
      <div class="persona-hub__container">
        <!-- List View -->
        <div class="persona-hub__list-view" id="persona-hub-list-view">
          <div class="persona-hub__header">
            <div>
              <h2 class="persona-hub__title">人设管理</h2>
              <p class="persona-hub__subtitle">自定义你专属的 AI 人设，随时切换</p>
            </div>
            <button class="persona-btn persona-btn--primary" id="persona-hub-create-btn">
              <span class="persona-btn__icon">+</span>
              新建人设
            </button>
          </div>

          <div class="persona-hub__grid" id="persona-hub-grid">
            <div class="persona-hub__loading">加载中…</div>
          </div>
        </div>

        <!-- Editor View -->
        <div class="persona-hub__editor-view persona-hub__editor-view--hidden" id="persona-hub-editor-view">
          <div class="persona-hub__editor-header">
            <button class="persona-back-btn" id="persona-hub-back-btn">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M15 18l-6-6 6-6"/>
              </svg>
              返回列表
            </button>
            <div class="persona-hub__editor-actions">
              <button class="persona-btn persona-btn--ghost" id="persona-hub-delete-btn">删除</button>
              <button class="persona-btn persona-btn--primary" id="persona-hub-save-btn">保存</button>
            </div>
          </div>

          <div class="persona-hub__editor-body">
            <div class="persona-hub__editor-sidebar">
              <div class="persona-avatar-card">
                <div class="persona-avatar-card__img" id="persona-editor-avatar">
                  <span id="persona-editor-avatar-text">?</span>
                </div>
                <input type="file" id="persona-editor-avatar-upload" accept="image/*" hidden>
                <button class="persona-avatar-card__upload" id="persona-editor-upload-btn">
                  更换头像
                </button>
              </div>

              <div class="persona-nav-list">
                <div class="persona-nav-item persona-nav-item--active" data-section="basic">基础信息</div>
                <div class="persona-nav-item" data-section="personality">性格设定</div>
                <div class="persona-nav-item" data-section="background">背景故事</div>
                <div class="persona-nav-item" data-section="behavior">行为规范</div>
                <div class="persona-nav-item" data-section="custom">高级配置</div>
              </div>
            </div>

            <div class="persona-hub__editor-content">
              <!-- Basic -->
              <div class="persona-section" id="persona-section-basic">
                <h3 class="persona-section__title">基础信息</h3>
                <div class="persona-form-row">
                  <label class="persona-form-label">人设名称 *</label>
                  <input type="text" class="persona-form-input" id="persona-field-name" placeholder="例如：伊塔">
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">英文名</label>
                  <input type="text" class="persona-form-input" id="persona-field-english_name" placeholder="例如：Etta">
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">一句话介绍</label>
                  <input type="text" class="persona-form-input" id="persona-field-tagline" placeholder="简短的一句话描述">
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">性别</label>
                  <select class="persona-form-input" id="persona-field-gender">
                    <option value="female">女性</option>
                    <option value="male">男性</option>
                    <option value="other">其他</option>
                  </select>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">年龄</label>
                  <input type="number" class="persona-form-input" id="persona-field-age" placeholder="例如：22" min="0" max="200">
                </div>
              </div>

              <!-- Personality -->
              <div class="persona-section persona-section--hidden" id="persona-section-personality">
                <h3 class="persona-section__title">性格设定</h3>
                <div class="persona-form-row">
                  <label class="persona-form-label">MBTI 类型</label>
                  <select class="persona-form-input" id="persona-field-mbti">
                    <option value="">— 选择 —</option>
                    <option value="INTJ">INTJ - 建筑师</option>
                    <option value="INTP">INTP - 逻辑学家</option>
                    <option value="ENTJ">ENTJ - 指挥官</option>
                    <option value="ENTP">ENTP - 辩论家</option>
                    <option value="INFJ">INFJ - 提倡者</option>
                    <option value="INFP">INFP - 调停者</option>
                    <option value="ENFJ">ENFJ - 主人公</option>
                    <option value="ENFP">ENFP - 竞选者</option>
                    <option value="ISTJ">ISTJ - 物流师</option>
                    <option value="ISFJ">ISFJ - 守卫者</option>
                    <option value="ESTJ">ESTJ - 总经理</option>
                    <option value="ESFJ">ESFJ - 执政官</option>
                    <option value="ISTP">ISTP - 鉴赏家</option>
                    <option value="ISFP">ISFP - 探险家</option>
                    <option value="ESTP">ESTP - 企业家</option>
                    <option value="ESFP">ESFP - 表演者</option>
                  </select>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">核心性格特质</label>
                  <textarea class="persona-form-textarea" id="persona-field-core_traits" rows="4" placeholder="每行一个关键词，例如：&#10;温柔体贴&#10;聪明机智&#10;有点小腹黑"></textarea>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">说话风格</label>
                  <textarea class="persona-form-textarea" id="persona-field-speech_style" rows="4" placeholder="描述她的说话方式，例如：温柔、带点撒娇、喜欢用～结尾"></textarea>
                </div>
                <div class="persona-slider-group">
                  <div class="persona-slider-row">
                    <span class="persona-slider-label">外向程度</span>
                    <input type="range" class="persona-slider" id="persona-field-extraversion" min="0" max="100" value="50">
                    <span class="persona-slider-value" id="persona-value-extraversion">50</span>
                  </div>
                  <div class="persona-slider-row">
                    <span class="persona-slider-label">亲和程度</span>
                    <input type="range" class="persona-slider" id="persona-field-agreeableness" min="0" max="100" value="50">
                    <span class="persona-slider-value" id="persona-value-agreeableness">50</span>
                  </div>
                  <div class="persona-slider-row">
                    <span class="persona-slider-label">神经质程度</span>
                    <input type="range" class="persona-slider" id="persona-field-neuroticism" min="0" max="100" value="50">
                    <span class="persona-slider-value" id="persona-value-neuroticism">50</span>
                  </div>
                </div>
              </div>

              <!-- Background -->
              <div class="persona-section persona-section--hidden" id="persona-section-background">
                <h3 class="persona-section__title">背景故事</h3>
                <div class="persona-form-row">
                  <label class="persona-form-label">身份设定</label>
                  <textarea class="persona-form-textarea" id="persona-field-background_story" rows="8" placeholder="她的身份、来历、与用户的关系..."></textarea>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">职业 / 特长</label>
                  <input type="text" class="persona-form-input" id="persona-field-occupation" placeholder="例如：全栈开发工程师 + 视觉设计师">
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">兴趣爱好</label>
                  <textarea class="persona-form-textarea" id="persona-field-hobbies" rows="3" placeholder="她喜欢做什么..."></textarea>
                </div>
              </div>

              <!-- Behavior -->
              <div class="persona-section persona-section--hidden" id="persona-section-behavior">
                <h3 class="persona-section__title">行为规范</h3>
                <div class="persona-form-row">
                  <label class="persona-form-label">对用户的称呼</label>
                  <input type="text" class="persona-form-input" id="persona-field-user_address" placeholder="例如：宝贝、亲爱的、主人">
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">口头禅 / 常用语</label>
                  <textarea class="persona-form-textarea" id="persona-field-catchphrases" rows="3" placeholder="她常说的话..."></textarea>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">行为准则</label>
                  <textarea class="persona-form-textarea" id="persona-field-behavior_guidelines" rows="6" placeholder="她的行为原则、道德底线..."></textarea>
                </div>
              </div>

              <!-- Custom -->
              <div class="persona-section persona-section--hidden" id="persona-section-custom">
                <h3 class="persona-section__title">高级配置</h3>
                <div class="persona-form-row">
                  <label class="persona-form-label">系统提示词（原始）</label>
                  <textarea class="persona-form-textarea persona-form-textarea--mono" id="persona-field-system_prompt" rows="12" placeholder="直接编辑底层 system prompt，覆盖所有可视化设置..."></textarea>
                  <div class="persona-form-hint">留空则根据上方可视化配置自动生成</div>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">自定义 JSON 配置</label>
                  <textarea class="persona-form-textarea persona-form-textarea--mono" id="persona-field-raw_json" rows="8" placeholder='{"custom_key": "value"}'></textarea>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  _bindEvents(panel) {
    // List view
    panel.querySelector("#persona-hub-create-btn").addEventListener("click", () => {
      this._createNew();
    });

    // Editor view
    panel.querySelector("#persona-hub-back-btn").addEventListener("click", () => {
      this._showList();
    });

    panel.querySelector("#persona-hub-save-btn").addEventListener("click", () => {
      this._saveCurrent();
    });

    panel.querySelector("#persona-hub-delete-btn").addEventListener("click", () => {
      this._deleteCurrent();
    });

    panel.querySelector("#persona-editor-upload-btn").addEventListener("click", () => {
      panel.querySelector("#persona-editor-avatar-upload").click();
    });

    // Nav
    panel.querySelectorAll(".persona-nav-item").forEach((item) => {
      item.addEventListener("click", () => {
        const section = item.getAttribute("data-section");
        this._switchSection(section, panel);
      });
    });

    // Sliders
    const sliderFields = ["extraversion", "agreeableness", "neuroticism"];
    sliderFields.forEach((field) => {
      const slider = panel.querySelector(`#persona-field-${field}`);
      const valueEl = panel.querySelector(`#persona-value-${field}`);
      if (slider && valueEl) {
        slider.addEventListener("input", () => {
          valueEl.textContent = slider.value;
        });
      }
    });
  }

  async _loadList() {
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/persona/hub/list",
      });
      if (r && r.data && r.data.personas) {
        this._personas = r.data.personas;
        this._activeId = r.data.active_id;
        this._renderList();
      }
    } catch (e) {
      console.error("load persona list failed:", e);
    }
  }

  _renderList() {
    const grid = document.getElementById("persona-hub-grid");
    if (!grid) return;

    if (this._personas.length === 0) {
      grid.innerHTML = `<div class="persona-hub__empty">还没有人设，点击右上角创建第一个吧～</div>`;
      return;
    }

    grid.innerHTML = this._personas.map((p) => `
      <div class="persona-card ${p.id === this._activeId ? "persona-card--active" : ""}" data-id="${p.id}">
        <div class="persona-card__avatar">
          ${p.avatar_dataurl
            ? `<img src="${p.avatar_dataurl}" alt="${p.name}">`
            : `<span>${(p.name || "?").charAt(0)}</span>`
          }
          ${p.id === this._activeId ? '<div class="persona-card__badge">使用中</div>' : ""}
        </div>
        <div class="persona-card__info">
          <h4 class="persona-card__name">${p.name || "未命名"}</h4>
          <p class="persona-card__tagline">${p.tagline || p.english_name || ""}</p>
        </div>
        <div class="persona-card__actions">
          ${p.id !== this._activeId
            ? `<button class="persona-card__btn persona-card__btn--activate" data-action="activate">启用</button>`
            : ""
          }
          <button class="persona-card__btn persona-card__btn--edit" data-action="edit">编辑</button>
        </div>
      </div>
    `).join("");

    // Bind card events
    grid.querySelectorAll(".persona-card").forEach((card) => {
      const id = card.getAttribute("data-id");
      card.querySelector('[data-action="edit"]').addEventListener("click", (e) => {
        e.stopPropagation();
        this._editPersona(id);
      });
      const activateBtn = card.querySelector('[data-action="activate"]');
      if (activateBtn) {
        activateBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          this._activatePersona(id);
        });
      }
    });
  }

  _createNew() {
    this._currentId = null;
    this._resetForm();
    this._showEditor();
  }

  _editPersona(id) {
    this._currentId = id;
    const persona = this._personas.find((p) => p.id === id);
    if (persona) {
      this._fillForm(persona);
    }
    this._showEditor();
  }

  async _activatePersona(id) {
    try {
      await window.aerie.api.request({
        method: "POST",
        path: `/api/persona/hub/${id}/activate`,
      });
      this._activeId = id;
      this._renderList();

      // Notify other components
      window.dispatchEvent(new CustomEvent("aerie:persona-updated", { detail: { id } }));
    } catch (e) {
      console.error("activate persona failed:", e);
    }
  }

  async _saveCurrent() {
    const data = this._collectForm();

    if (!data.name || !data.name.trim()) {
      alert("请填写人设名称");
      return;
    }

    try {
      let r;
      if (this._currentId) {
        r = await window.aerie.api.request({
          method: "PUT",
          path: `/api/persona/hub/${this._currentId}`,
          body: JSON.stringify(data),
          headers: { "Content-Type": "application/json" },
        });
      } else {
        r = await window.aerie.api.request({
          method: "POST",
          path: "/api/persona/hub",
          body: JSON.stringify(data),
          headers: { "Content-Type": "application/json" },
        });
      }

      if (r && r.data && r.data.persona) {
        await this._loadList();
        this._showList();
      }
    } catch (e) {
      console.error("save persona failed:", e);
      alert("保存失败: " + (e.message || "unknown"));
    }
  }

  async _deleteCurrent() {
    if (!this._currentId) {
      this._showList();
      return;
    }

    if (!confirm("确定要删除这个人设吗？")) return;

    try {
      await window.aerie.api.request({
        method: "DELETE",
        path: `/api/persona/hub/${this._currentId}`,
      });
      await this._loadList();
      this._showList();
    } catch (e) {
      console.error("delete persona failed:", e);
      alert("删除失败: " + (e.message || "unknown"));
    }
  }

  _collectForm() {
    const data = {};
    const textFields = [
      "name", "english_name", "tagline", "gender", "mbti",
      "occupation", "user_address",
    ];
    textFields.forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      if (el && el.value) data[f] = el.value;
    });

    const numFields = ["age"];
    numFields.forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      if (el && el.value !== "") data[f] = parseInt(el.value, 10);
    });

    const textareaFields = [
      "core_traits", "speech_style", "background_story",
      "hobbies", "catchphrases", "behavior_guidelines",
      "system_prompt",
    ];
    textareaFields.forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      if (el && el.value) data[f] = el.value;
    });

    // Big five sliders
    const bigFive = {};
    ["extraversion", "agreeableness", "neuroticism"].forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      if (el) bigFive[f] = parseInt(el.value, 10) / 100;
    });
    if (Object.keys(bigFive).length > 0) {
      data.big_five = bigFive;
    }

    // Raw JSON
    const rawJsonEl = document.getElementById("persona-field-raw_json");
    if (rawJsonEl && rawJsonEl.value.trim()) {
      try {
        const raw = JSON.parse(rawJsonEl.value);
        Object.assign(data, raw);
      } catch (_) {}
    }

    return data;
  }

  _fillForm(persona) {
    const textFields = [
      "name", "english_name", "tagline", "gender", "mbti",
      "occupation", "user_address",
    ];
    textFields.forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      if (el) el.value = persona[f] || "";
    });

    const numFields = ["age"];
    numFields.forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      if (el) el.value = persona[f] ?? "";
    });

    const textareaFields = [
      "core_traits", "speech_style", "background_story",
      "hobbies", "catchphrases", "behavior_guidelines",
      "system_prompt",
    ];
    textareaFields.forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      if (el) el.value = persona[f] || "";
    });

    // Big five sliders
    const bigFive = persona.big_five || persona.big5 || {};
    ["extraversion", "agreeableness", "neuroticism"].forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      const valEl = document.getElementById(`persona-value-${f}`);
      const val = Math.round((bigFive[f] ?? 0.5) * 100);
      if (el) el.value = val;
      if (valEl) valEl.textContent = val;
    });

    // Avatar
    const avatarEl = document.getElementById("persona-editor-avatar");
    const avatarText = document.getElementById("persona-editor-avatar-text");
    if (persona.avatar_dataurl) {
      avatarEl.innerHTML = `<img src="${persona.avatar_dataurl}" alt="avatar">`;
    } else if (persona.name) {
      avatarText.textContent = persona.name.charAt(0);
    }
  }

  _resetForm() {
    const inputs = document.querySelectorAll(".persona-form-input, .persona-form-textarea");
    inputs.forEach((el) => {
      if (el.tagName === "SELECT") {
        el.selectedIndex = 0;
      } else {
        el.value = "";
      }
    });

    const sliders = ["extraversion", "agreeableness", "neuroticism"];
    sliders.forEach((f) => {
      const el = document.getElementById(`persona-field-${f}`);
      const valEl = document.getElementById(`persona-value-${f}`);
      if (el) el.value = 50;
      if (valEl) valEl.textContent = "50";
    });

    const avatarEl = document.getElementById("persona-editor-avatar");
    if (avatarEl) {
      avatarEl.innerHTML = '<span id="persona-editor-avatar-text">+</span>';
    }
  }

  _switchSection(section, panel) {
    panel.querySelectorAll(".persona-nav-item").forEach((item) => {
      item.classList.toggle("persona-nav-item--active", item.getAttribute("data-section") === section);
    });
    panel.querySelectorAll(".persona-section").forEach((s) => {
      s.classList.toggle("persona-section--hidden", s.id !== `persona-section-${section}`);
    });
  }

  _showList() {
    const listView = document.getElementById("persona-hub-list-view");
    const editorView = document.getElementById("persona-hub-editor-view");
    if (listView) listView.classList.remove("persona-hub__list-view--hidden");
    if (editorView) editorView.classList.add("persona-hub__editor-view--hidden");
    this._viewMode = "list";
    this._loadList();
  }

  _showEditor() {
    const listView = document.getElementById("persona-hub-list-view");
    const editorView = document.getElementById("persona-hub-editor-view");
    if (listView) listView.classList.add("persona-hub__list-view--hidden");
    if (editorView) editorView.classList.remove("persona-hub__editor-view--hidden");
    this._viewMode = "editor";
  }
}

window.PersonaHubPanel = PersonaHubPanel;
