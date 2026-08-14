"use strict";
/* v13.0: Persona Hub — 人设管理面板（可视化编辑器） */

class PersonaHubPanel {
  constructor() {
    this._personas = [];
    this._activeId = null;
    this._currentId = null;
    this._viewMode = "list"; // "list" | "editor" | "wizard"
    this._isLoaded = false;
    this._genTaskId = null;
    this._genTimer = null;
    this._genPayload = null;
    this._genPollCount = 0;
    this._selectedConcept = null;
  }

  init() {
    const panel = document.getElementById("panel-persona-hub");
    if (!panel) return;

    this._buildDom(panel);
    this._bindEvents(panel);
    this._loadList();

    if (window.aerie && window.aerie.electron && window.aerie.electron.onHealth) {
      let wasReady = false;
      window.aerie.electron.onHealth((data) => {
        if (data.ready && !wasReady && !this._isLoaded) {
          this._loadList();
        }
        wasReady = data.ready;
      });
    }
  }

  setVisible(visible) {
    if (visible && this._viewMode === "list" && !this._isLoaded) {
      this._loadList();
    }
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
            <div class="persona-hub__header-actions">
              <input type="file" id="persona-hub-import-input" accept=".json,application/json" hidden>
              <button class="persona-btn persona-btn--ghost" id="persona-hub-import-btn">
                导入人设
              </button>
              <button class="persona-btn persona-btn--primary" id="persona-hub-create-btn">
                <span class="persona-btn__icon">+</span>
                新建人设
              </button>
            </div>
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
              <button class="persona-btn persona-btn--ghost" id="persona-hub-export-btn">导出</button>
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
                <div class="persona-nav-item" data-section="three_view">三视图</div>
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

              <!-- Three View -->
              <div class="persona-section persona-section--hidden" id="persona-section-three_view">
                <h3 class="persona-section__title">三视图（辅助生图参考）</h3>
                <p class="persona-section__hint">
                  上传该人设的正面 / 侧面 / 背面参考图，作为图生图时锁定角色外观的参考。
                  每张 PNG/JPG，超过 8MB 会自动压缩至上限内。切换人设时三视图会跟随切换。
                </p>
                <div class="persona-three-view-grid">
                  ${["front", "side", "back"].map((view) => `
                    <div class="persona-three-view-card" data-view="${view}">
                      <div class="persona-three-view-card__img" data-role="preview">
                        <span>+</span>
                      </div>
                      <div class="persona-three-view-card__label">
                        ${{ front: "正面 Front", side: "侧面 Side", back: "背面 Back" }[view]}
                      </div>
                      <input type="file" class="persona-three-view-upload" accept="image/*" hidden>
                      <div class="persona-three-view-card__actions">
                        <button type="button" class="persona-btn persona-btn--primary" data-role="upload">上传</button>
                        <button type="button" class="persona-btn persona-btn--ghost" data-role="remove">删除</button>
                      </div>
                    </div>
                  `).join("")}
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
                    <option value="ENFJ">ENFJ - 引导者</option>
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
                  <textarea class="persona-form-textarea" id="persona-field-speech_style" rows="4" placeholder="描述 TA 的说话方式，例如：温柔、带点撒娇、喜欢用～结尾"></textarea>
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
                  <textarea class="persona-form-textarea" id="persona-field-background_story" rows="8" placeholder="TA 的身份、来历、与用户的关系..."></textarea>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">职业 / 特长</label>
                  <input type="text" class="persona-form-input" id="persona-field-occupation" placeholder="例如：全栈开发工程师 + 视觉设计师">
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">兴趣爱好</label>
                  <textarea class="persona-form-textarea" id="persona-field-hobbies" rows="3" placeholder="TA 喜欢做什么..."></textarea>
                </div>
              </div>

              <!-- Behavior -->
              <div class="persona-section persona-section--hidden" id="persona-section-behavior">
                <h3 class="persona-section__title">行为规范</h3>
                <div class="persona-form-row">
                  <label class="persona-form-label">对用户的称呼</label>
                  <input type="text" class="persona-form-input" id="persona-field-user_address" placeholder="例如：宝贝、亲爱的、你">
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">口头禅 / 常用语</label>
                  <textarea class="persona-form-textarea" id="persona-field-catchphrases" rows="3" placeholder="TA 常说的话..."></textarea>
                </div>
                <div class="persona-form-row">
                  <label class="persona-form-label">行为准则</label>
                  <textarea class="persona-form-textarea" id="persona-field-behavior_guidelines" rows="6" placeholder="TA 的行为原则、道德底线..."></textarea>
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

    // Wizard View（AI 智能生成人设向导）
    // 必须插入 .persona-hub__container 内部，与 list/editor 平级，
    // 才能共享其 flex 布局空间；插在 panel 层会被 height:100% 的
    // container 挤成 0 高度，导致点击"新建人设"后整面板空白（白屏）。
    const wizardHost = panel.querySelector(".persona-hub__container");
    if (wizardHost && !wizardHost.querySelector(".persona-wizard")) {
      wizardHost.insertAdjacentHTML("beforeend", `
        <div class="persona-wizard persona-wizard--hidden" id="persona-hub-wizard-view">
          <!-- 表单步骤 -->
          <div class="persona-wizard__panel" id="persona-wizard-form">
            <div class="persona-wizard__head">
              <h2 class="persona-wizard__title">用一句话，让 TA 成为你想的人</h2>
              <p class="persona-wizard__subtitle">AI 会理解你的描述，自动生成完整人设框架；生成后你可以逐项完善</p>
            </div>
            <div class="persona-wizard__body">
              <label class="persona-wizard__label">角色描述 *</label>
              <textarea id="persona-wizard-desc" class="persona-wizard__desc" rows="5"
                placeholder="例如：银发红瞳的温柔御姐设计师，28岁，是我的恋人，表面从容克制、私下占有欲极强，会用最轻的声音说最笃定的情话…"></textarea>
              <div class="persona-wizard__options">
                <label class="persona-wizard__opt">名字 <input id="persona-wizard-name" class="persona-form-input" placeholder="可选"></label>
                <label class="persona-wizard__opt">英文名 <input id="persona-wizard-english_name" class="persona-form-input" placeholder="可选"></label>
                <label class="persona-wizard__opt">性别
                  <select id="persona-wizard-gender" class="persona-form-input">
                    <option value="">— 可选 —</option><option value="female">女性</option><option value="male">男性</option><option value="other">其他</option>
                  </select>
                </label>
                <label class="persona-wizard__opt">年龄 <input id="persona-wizard-age" class="persona-form-input" type="number" min="0" max="200" placeholder="可选"></label>
                <label class="persona-wizard__opt">关系类型 <input id="persona-wizard-relationship" class="persona-form-input" placeholder="恋人 / 朋友 / 导师…"></label>
                <label class="persona-wizard__opt">你的名字 <input id="persona-wizard-user-name" class="persona-form-input" placeholder="你的昵称，可选"></label>
              </div>

              <div class="persona-wizard__story">
                <label class="persona-wizard__label">两人故事起因（可选）</label>
                <textarea id="persona-wizard-story" class="persona-wizard__desc persona-wizard__desc--short" rows="3"
                  placeholder="例如：TA 是我的秘书，想先从工作关系慢慢靠近我…"></textarea>
                <div class="persona-wizard__story-actions">
                  <button type="button" class="persona-btn persona-btn--ghost persona-btn--sm" id="persona-wizard-recommend-btn">
                    为我推荐故事概念
                  </button>
                  <span class="persona-wizard__story-hint" id="persona-wizard-story-hint">选一个喜欢的故事设定，生成时会融进两人的背景</span>
                </div>
                <div class="persona-wizard__concepts" id="persona-wizard-concepts"></div>
              </div>
            </div>
            <div class="persona-wizard__actions">
              <button class="persona-btn persona-btn--ghost" id="persona-wizard-skip-btn">跳过 AI 生成，手动创建</button>
              <button class="persona-btn persona-btn--primary" id="persona-wizard-start-btn">开始生成</button>
            </div>
          </div>

          <!-- 进度步骤 -->
          <div class="persona-wizard__panel persona-wizard__panel--hidden" id="persona-wizard-progress">
            <div class="persona-wizard__progress-head">
              <div class="persona-wizard__pulse" aria-hidden="true"></div>
              <h2 class="persona-wizard__title">AI 正在帮你生成你的角色…</h2>
              <p class="persona-wizard__msg" id="persona-wizard-msg">正在分析角色概念</p>
            </div>
            <div class="persona-wizard__bar"><div class="persona-wizard__bar-fill" id="persona-wizard-bar-fill"></div></div>
            <ul class="persona-wizard__stages" id="persona-wizard-stages">
              <li class="persona-wizard__stage" data-key="concept"><span class="persona-wizard__stage-dot"></span><span class="persona-wizard__stage-name">分析角色概念</span></li>
              <li class="persona-wizard__stage" data-key="detail"><span class="persona-wizard__stage-dot"></span><span class="persona-wizard__stage-name">生成外貌与性格</span></li>
              <li class="persona-wizard__stage" data-key="assemble"><span class="persona-wizard__stage-dot"></span><span class="persona-wizard__stage-name">构建人设框架</span></li>
              <li class="persona-wizard__stage" data-key="prompt"><span class="persona-wizard__stage-dot"></span><span class="persona-wizard__stage-name">组装系统提示词</span></li>
              <li class="persona-wizard__stage" data-key="finalize"><span class="persona-wizard__stage-dot"></span><span class="persona-wizard__stage-name">校验并保存</span></li>
            </ul>
            <div class="persona-wizard__error persona-wizard__error--hidden" id="persona-wizard-error">
              <div class="persona-wizard__error-text" id="persona-wizard-error-text"></div>
              <div class="persona-wizard__actions">
                <button class="persona-btn persona-btn--primary" id="persona-wizard-retry-btn">重新生成</button>
                <button class="persona-btn persona-btn--ghost" id="persona-wizard-back-btn">返回</button>
              </div>
            </div>
            <div class="persona-wizard__actions" style="margin-top:16px">
              <button class="persona-btn persona-btn--ghost" id="persona-wizard-cancel-btn">取消</button>
            </div>
          </div>
        </div>
      `);
    }
  }

  _bindEvents(panel) {
    // List view
    panel.querySelector("#persona-hub-create-btn").addEventListener("click", () => {
      this._openWizard();
    });

    panel.querySelector("#persona-hub-import-btn").addEventListener("click", () => {
      panel.querySelector("#persona-hub-import-input").click();
    });

    panel.querySelector("#persona-hub-import-input").addEventListener("change", (e) => {
      const file = e.target.files[0];
      if (file) this._importPersona(file);
      e.target.value = "";
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

    panel.querySelector("#persona-hub-export-btn").addEventListener("click", () => {
      if (this._currentId) {
        this._exportPersona(this._currentId);
      }
    });

    panel.querySelector("#persona-editor-upload-btn").addEventListener("click", () => {
      panel.querySelector("#persona-editor-avatar-upload").click();
    });
    // 角色级隔离：编辑器头像上传 —— 打开裁切弹窗 → 裁切后按当前角色上传
    panel.querySelector("#persona-editor-avatar-upload").addEventListener("change", (e) => {
      const file = e.target.files && e.target.files[0];
      if (file) this._openAvatarCrop(file);
      e.target.value = "";
    });

    // Three-view: upload / remove
    panel.querySelectorAll(".persona-three-view-card").forEach((card) => {
      const uploadInput = card.querySelector(".persona-three-view-upload");
      const uploadBtn = card.querySelector('[data-role="upload"]');
      const removeBtn = card.querySelector('[data-role="remove"]');
      uploadBtn.addEventListener("click", () => uploadInput.click());
      uploadInput.addEventListener("change", (e) => {
        const file = e.target.files && e.target.files[0];
        if (file) this._uploadThreeView(card, file);
        uploadInput.value = "";
      });
      removeBtn.addEventListener("click", () => this._removeThreeView(card));
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

    // Wizard view
    panel.querySelector("#persona-wizard-start-btn").addEventListener("click", () => {
      this._startGeneration();
    });
    panel.querySelector("#persona-wizard-skip-btn").addEventListener("click", () => {
      this._skipToEditor();
    });
    panel.querySelector("#persona-wizard-cancel-btn").addEventListener("click", () => {
      this._showList();
    });
    panel.querySelector("#persona-wizard-back-btn").addEventListener("click", () => {
      this._showList();
    });
    panel.querySelector("#persona-wizard-retry-btn").addEventListener("click", () => {
      this._startGeneration();
    });
    panel.querySelector("#persona-wizard-recommend-btn").addEventListener("click", () => {
      this._recommendConcepts();
    });
  }

  async _loadList() {
    const grid = document.getElementById("persona-hub-grid");
    if (grid) {
      grid.innerHTML = `<div class="persona-hub__loading">加载中…</div>`;
    }

    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: "/api/persona/hub/list",
      });
      if (r && r.data && r.data.personas) {
        this._personas = r.data.personas;
        this._activeId = r.data.active_id;
        this._isLoaded = true;
        this._renderList();
      } else {
        this._showLoadError("返回数据格式异常");
      }
    } catch (e) {
      console.error("load persona list failed:", e);
      this._showLoadError(e.message || "网络请求失败");
    }
  }

  _showLoadError(message) {
    const grid = document.getElementById("persona-hub-grid");
    if (!grid) return;
    grid.innerHTML = `
      <div class="persona-hub__error">
        <div class="persona-hub__error-icon">!</div>
        <div class="persona-hub__error-text">加载失败：${message}</div>
        <button class="persona-btn persona-btn--primary" id="persona-hub-retry-btn">重试</button>
      </div>
    `;
    const retryBtn = document.getElementById("persona-hub-retry-btn");
    if (retryBtn) {
      retryBtn.addEventListener("click", () => this._loadList());
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
            : `<span style="${this._avatarPlaceholderStyle(p.id)}">${(p.name || "?").charAt(0)}</span>`
          }
          ${p.id === this._activeId ? '<div class="persona-card__badge">使用中</div>' : ""}
        </div>
        <div class="persona-card__info">
          <h4 class="persona-card__name">${p.name || "未命名"}</h4>
          <p class="persona-card__tagline">${p.tagline || p.english_name || p.description || ""}</p>
        </div>
        <div class="persona-card__actions">
          ${p.id !== this._activeId
            ? `<button class="persona-card__btn persona-card__btn--activate" data-action="activate">启用</button>`
            : ""
          }
          <button class="persona-card__btn persona-card__btn--edit" data-action="edit">编辑</button>
          <button class="persona-card__btn persona-card__btn--export" data-action="export">导出</button>
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
      const exportBtn = card.querySelector('[data-action="export"]');
      if (exportBtn) {
        exportBtn.addEventListener("click", (e) => {
          e.stopPropagation();
          this._exportPersona(id);
        });
      }
    });
  }

  _createNew() {
    this._openWizard();
  }

  _skipToEditor() {
    this._currentId = null;
    this._resetForm();
    this._showEditor();
  }

  async _editPersona(id) {
    this._currentId = id;
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: `/api/persona/hub/${id}`,
      });
      if (!r || !r.data || !r.data.persona) {
        throw new Error("返回数据格式异常");
      }
      this._fillForm(r.data.persona);
      this._showEditor();
      this._loadThreeViewSummary(id);
    } catch (e) {
      console.error("load persona detail failed:", e);
      alert("加载人设失败: " + (e.message || "unknown"));
    }
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

    if (!data.basic || !data.basic.name || !data.basic.name.trim()) {
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

      if (r && r.data && r.data.status === "ok" && r.data.persona_id) {
        await this._loadList();
        this._showList();
      } else {
        throw new Error((r && r.data && r.data.error) || "返回数据格式异常");
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

    // 静默删除：内置伊塔仅隐藏，其它角色物理删除；不弹任何确认框
    try {
      await window.aerie.api.request({
        method: "DELETE",
        path: `/api/persona/hub/${this._currentId}`,
      });
      await this._loadList();
      this._showList();
    } catch (e) {
      console.error("delete persona failed:", e);
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

    return this._toHubModel(data);
  }

  _toHubModel(data) {
    if (data.basic || data.personality || data.relationship) {
      return data;
    }
    const traits = (data.core_traits || "")
      .split("\n")
      .map((value) => value.trim())
      .filter(Boolean)
      .map((name) => ({ name, en: "", desc: "" }));
    const model = {
      name: data.name || "",
      version: "1.0.0",
      basic: {
        name: data.name || "",
        english_name: data.english_name || "",
        age: data.age ?? 0,
        product_name: "Aerie · 云栖",
      },
      personality: {
        cores: traits,
        speech_style: data.speech_style || "",
        big_five: data.big_five || {},
      },
      relationship: {
        user_address_default: data.user_address || "你",
        user_intimate_terms: data.user_address ? [data.user_address] : [],
        self_reference: "我",
      },
      emotion: {
        baseline: { pleasure: 0.1, arousal: 0.2, dominance: 0.8 },
        thresholds: {},
      },
      behavior: {
        proactivity_level: 0.5,
        default_permission_level: "VIEW_ONLY",
      },
      prompt_overrides: {
        system_prompt: data.system_prompt || "",
      },
    };
    ["tagline", "gender", "mbti", "occupation", "background_story", "hobbies", "catchphrases", "behavior_guidelines"].forEach((key) => {
      if (data[key] !== undefined) model[key] = data[key];
    });
    return model;
  }

  _fillForm(persona) {
    const basic = persona.basic || {};
    const personality = persona.personality || {};
    const relationship = persona.relationship || {};
    const promptOverrides = persona.prompt_overrides || {};
    persona = {
      ...persona,
      name: basic.name || persona.name,
      english_name: basic.english_name || persona.english_name,
      age: basic.age ?? persona.age,
      core_traits: (personality.cores || [])
        .map((item) => typeof item === "string" ? item : item.name)
        .filter(Boolean)
        .join("\n"),
      speech_style: personality.speech_style || persona.speech_style,
      big_five: personality.big_five || persona.big_five,
      user_address: (relationship.user_intimate_terms || [])[0]
        || relationship.user_address_default
        || persona.user_address,
      system_prompt: promptOverrides.system_prompt || persona.system_prompt,
    };
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
      avatarText.style.background = this._avatarPlaceholderColor(persona.id || persona.name);
    }
  }

  // 默认头像占位：按角色 id 确定性取色，避免所有无头像角色看起来一模一样
  _avatarPlaceholderColor(seed) {
    let h = 0;
    const s = String(seed || "default");
    for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
    const hue = h % 360;
    return "hsl(" + hue + ", 62%, 62%)";
  }

  _avatarPlaceholderStyle(seed) {
    return "display:inline-flex;align-items:center;justify-content:center;"
      + "width:100%;height:100%;color:#fff;font-size:26px;font-weight:600;"
      + "background:" + this._avatarPlaceholderColor(seed) + ";";
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

  async _loadThreeViewSummary(personaId) {
    if (!personaId) return;
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: `/api/persona/three-view?persona_id=${encodeURIComponent(personaId)}`,
      });
      const views = (r && r.data && r.data.views) || {};
      document.querySelectorAll(".persona-three-view-card").forEach((card) => {
        const view = card.getAttribute("data-view");
        const info = views[view] || {};
        const preview = card.querySelector('[data-role="preview"]');
        if (preview) {
          preview.innerHTML = info.present
            ? `<img src="${info.dataurl}" alt="${view}">`
            : "<span>+</span>";
        }
      });
    } catch (e) {
      console.error("load three-view summary failed:", e);
    }
  }

  async _uploadThreeView(card, file) {
    const view = card.getAttribute("data-view");
    if (!this._currentId) {
      alert("请先保存人设再上传三视图");
      return;
    }
    try {
      const buf = new Uint8Array(await file.arrayBuffer());
      let r = null;
      if (window.aerie && window.aerie.api && window.aerie.api.upload) {
        r = await window.aerie.api.upload({
          path: `/api/persona/three-view/${encodeURIComponent(this._currentId)}/${view}`,
          filename: file.name || `${view}.png`,
          contentType: file.type,
          bytes: Array.from(buf),
        });
      }
      if (!r || !r.data || r.data.status !== "ok") {
        throw new Error((r && r.data && r.data.error) || "上传失败");
      }
      const preview = card.querySelector('[data-role="preview"]');
      if (preview) {
        preview.innerHTML = r.data.dataurl
          ? `<img src="${r.data.dataurl}" alt="${view}">`
          : "<span>+</span>";
      }
    } catch (e) {
      console.error("upload three-view failed:", e);
      alert("三视图上传失败: " + (e.message || "unknown"));
    }
  }

  async _removeThreeView(card) {
    const view = card.getAttribute("data-view");
    if (!this._currentId) return;
    if (!confirm(`确定删除该人设的 ${view} 三视图吗？`)) return;
    try {
      const r = await window.aerie.api.request({
        method: "DELETE",
        path: `/api/persona/three-view/${encodeURIComponent(this._currentId)}/${view}`,
      });
      if (r && r.data && r.data.status === "ok") {
        const preview = card.querySelector('[data-role="preview"]');
        if (preview) preview.innerHTML = "<span>+</span>";
      } else {
        throw new Error((r && r.data && r.data.error) || "删除失败");
      }
    } catch (e) {
      console.error("remove three-view failed:", e);
      alert("三视图删除失败: " + (e.message || "unknown"));
    }
  }

  // ── 头像上传：文件 → 裁切弹窗 → 按角色上传 ──────────────
  _openAvatarCrop(file) {
    if (!this._currentId) {
      alert("请先保存人设再上传头像");
      return;
    }
    const reader = new FileReader();
    reader.onload = () => {
      const src = String(reader.result || "");
      if (!src) return;
      const img = new Image();
      img.onload = () => this._renderAvatarCropModal(img, file);
      img.src = src;
    };
    reader.readAsDataURL(file);
  }

  _renderAvatarCropModal(img, file) {
    const old = document.getElementById("persona-avatar-crop-modal");
    if (old) old.remove();

    const natural = { w: img.naturalWidth, h: img.naturalHeight };
    if (!natural.w || !natural.h) return;

    const modal = document.createElement("div");
    modal.id = "persona-avatar-crop-modal";
    modal.style.cssText =
      "position:fixed;inset:0;z-index:9999;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center;";

    const box = document.createElement("div");
    box.style.cssText =
      "background:#fff;border-radius:14px;padding:18px;width:min(480px,92vw);display:flex;flex-direction:column;gap:12px;font-family:inherit;box-shadow:0 10px 40px rgba(0,0,0,.3);";

    const title = document.createElement("div");
    title.textContent = "裁切头像（方形）· 拖动调整位置，右下角手柄缩放";
    title.style.cssText = "font-size:15px;font-weight:600;color:#3c3c43;";

    const viewport = document.createElement("div");
    viewport.style.cssText =
      "position:relative;overflow:hidden;background:#111;border-radius:10px;user-select:none;touch-action:none;";
    const maxW = 440, maxH = 360;
    const scale = Math.min(maxW / natural.w, maxH / natural.h);
    const dispW = Math.round(natural.w * scale);
    const dispH = Math.round(natural.h * scale);
    viewport.style.width = dispW + "px";
    viewport.style.height = dispH + "px";

    const imgEl = document.createElement("img");
    imgEl.src = img.src;
    imgEl.style.cssText = "position:absolute;top:0;left:0;width:" + dispW + "px;height:" + dispH + "px;display:block;pointer-events:none;";

    const crop = {
      size: Math.max(40, Math.round(Math.min(dispW, dispH) * 0.7)),
      x: 0, y: 0,
    };
    crop.x = Math.round((dispW - crop.size) / 2);
    crop.y = Math.round((dispH - crop.size) / 2);

    const cropEl = document.createElement("div");
    cropEl.style.cssText =
      "position:absolute;border:2px solid #fff;box-sizing:border-box;cursor:move;"
      + "box-shadow:0 0 0 9999px rgba(0,0,0,.45);";
    const handle = document.createElement("div");
    handle.style.cssText =
      "position:absolute;right:-7px;bottom:-7px;width:16px;height:16px;"
      + "background:#fff;border:2px solid #ff6b9d;border-radius:4px;cursor:se-resize;";

    function paint() {
      cropEl.style.left = crop.x + "px";
      cropEl.style.top = crop.y + "px";
      cropEl.style.width = crop.size + "px";
      cropEl.style.height = crop.size + "px";
    }
    paint();

    let dragging = null;
    cropEl.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      dragging = { type: "move", sx: e.clientX, sy: e.clientY, ox: crop.x, oy: crop.y };
      cropEl.setPointerCapture(e.pointerId);
    });
    handle.addEventListener("pointerdown", (e) => {
      e.stopPropagation();
      e.preventDefault();
      dragging = { type: "resize", sx: e.clientX, sy: e.clientY, osize: crop.size };
      handle.setPointerCapture(e.pointerId);
    });
    cropEl.addEventListener("pointermove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - dragging.sx;
      const dy = e.clientY - dragging.sy;
      if (dragging.type === "move") {
        crop.x = Math.min(Math.max(dragging.ox + dx, 0), dispW - crop.size);
        crop.y = Math.min(Math.max(dragging.oy + dy, 0), dispH - crop.size);
      } else {
        const s = Math.min(Math.max(dragging.osize + Math.max(dx, dy), 40), Math.min(dispW, dispH));
        crop.size = s;
        crop.x = Math.min(crop.x, dispW - s);
        crop.y = Math.min(crop.y, dispH - s);
      }
      paint();
    });
    const endDrag = () => { dragging = null; };
    cropEl.addEventListener("pointerup", endDrag);
    handle.addEventListener("pointerup", endDrag);
    cropEl.addEventListener("pointercancel", endDrag);
    handle.addEventListener("pointercancel", endDrag);

    cropEl.appendChild(handle);
    viewport.appendChild(imgEl);
    viewport.appendChild(cropEl);

    const actions = document.createElement("div");
    actions.style.cssText = "display:flex;justify-content:flex-end;gap:10px;";
    const cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.textContent = "取消";
    cancelBtn.style.cssText = "padding:8px 18px;border-radius:20px;border:1px solid #e5e5ea;background:#fafafa;color:#3c3c43;font-size:14px;cursor:pointer;";
    const okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.textContent = "确认裁切并上传";
    okBtn.style.cssText = "padding:8px 18px;border-radius:20px;border:none;background:#ff8fb1;color:#fff;font-size:14px;cursor:pointer;";

    cancelBtn.addEventListener("click", () => modal.remove());
    okBtn.addEventListener("click", () => {
      const out = 512;
      const cvs = document.createElement("canvas");
      cvs.width = out; cvs.height = out;
      const c2 = cvs.getContext("2d");
      const nx = crop.x / scale, ny = crop.y / scale, nsize = crop.size / scale;
      c2.drawImage(img, nx, ny, nsize, nsize, 0, 0, out, out);
      const mime = (file && file.type === "image/jpeg") ? "image/jpeg" : "image/png";
      const outUrl = cvs.toDataURL(mime, 0.92);
      modal.remove();
      this._uploadAvatar(outUrl, mime);
    });

    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    box.appendChild(title);
    box.appendChild(viewport);
    box.appendChild(actions);
    modal.appendChild(box);
    document.body.appendChild(modal);
  }

  _uploadAvatar(dataurl, mime) {
    const pid = this._currentId;
    if (!pid) return;
    try {
      const idx = dataurl.indexOf(",");
      const bin = atob(dataurl.slice(idx + 1));
      const bytes = new Uint8Array(bin.length);
      for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
      const ext = mime === "image/jpeg" ? "jpg" : "png";
      const doUpload = async () => {
        let r = null;
        if (window.aerie && window.aerie.api && window.aerie.api.upload) {
          r = await window.aerie.api.upload({
            path: "/api/persona/avatar?persona_id=" + encodeURIComponent(pid),
            filename: "avatar." + ext,
            contentType: mime,
            bytes: Array.from(bytes),
          });
        }
        if (!r || !r.data || r.data.status !== "ok") {
          throw new Error((r && r.data && r.data.error) || "上传失败");
        }
        const dataurlResp = r.data.avatar_dataurl || dataurl;
        const avatarEl = document.getElementById("persona-editor-avatar");
        if (avatarEl) avatarEl.innerHTML = `<img src="${dataurlResp}" alt="avatar">`;
        // 刷新人设列表（卡片头像即时可见，无需重启应用）
        this._loadList();
        // 角色级隔离：带 persona_id 通知 chat/settings —— 只有当前激活角色
        // 的头像更新才被聊天窗口采纳，非激活角色的头像不会串到聊天里。
        window.dispatchEvent(new CustomEvent("aerie:persona-updated", {
          detail: { persona_id: pid, avatar_dataurl: dataurlResp, source: "persona-hub" },
        }));
      };
      doUpload().catch((e) => {
        console.error("avatar upload failed:", e);
        alert("头像上传失败: " + (e.message || "unknown"));
      });
    } catch (e) {
      alert("头像处理失败: " + (e.message || "unknown"));
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
    this._hideWizard();
    this._viewMode = "list";
    this._loadList();
  }

  _showEditor() {
    const listView = document.getElementById("persona-hub-list-view");
    const editorView = document.getElementById("persona-hub-editor-view");
    if (listView) listView.classList.add("persona-hub__list-view--hidden");
    if (editorView) editorView.classList.remove("persona-hub__editor-view--hidden");
    this._hideWizard();
    this._viewMode = "editor";

    const deleteBtn = document.getElementById("persona-hub-delete-btn");
    const exportBtn = document.getElementById("persona-hub-export-btn");
    if (deleteBtn) deleteBtn.style.display = this._currentId ? "" : "none";
    if (exportBtn) exportBtn.style.display = this._currentId ? "" : "none";
  }

  _hideWizard() {
    const wizardView = document.getElementById("persona-hub-wizard-view");
    if (wizardView) wizardView.classList.add("persona-wizard--hidden");
  }

  _openWizard() {
    this._currentId = null;
    const payload = this._genPayload || {};
    const opts = payload.options || {};
    const setVal = (id, value) => {
      const el = document.getElementById(id);
      if (el) el.value = value === undefined || value === null ? "" : value;
    };
    setVal("persona-wizard-desc", payload.description || "");
    setVal("persona-wizard-name", opts.name || "");
    setVal("persona-wizard-english_name", opts.english_name || "");
    setVal("persona-wizard-gender", opts.gender || "");
    setVal("persona-wizard-age", opts.age !== undefined ? opts.age : "");
    setVal("persona-wizard-relationship", opts.relationship_type || "");
    setVal("persona-wizard-story", opts.story_seed || "");
    // 用户昵称：优先用上次生成用的，否则读聊天模块缓存的名字（非默认"你"）
    const cachedUser = (window._chat && window._chat._userName && window._chat._userName !== "你")
      ? window._chat._userName : "";
    setVal("persona-wizard-user-name", opts.user_name || cachedUser);
    this._selectedConcept = opts.story_concept || null;
    this._showWizard();
  }

  _showWizard() {
    const wizardView = document.getElementById("persona-hub-wizard-view");
    if (!wizardView) {
      // 防御：向导视图未构建（DOM 异常/旧缓存）时退回编辑器，避免整面板空白
      console.warn("wizard view missing, fallback to blank editor");
      this._skipToEditor();
      return;
    }
    const listView = document.getElementById("persona-hub-list-view");
    const editorView = document.getElementById("persona-hub-editor-view");
    if (listView) listView.classList.add("persona-hub__list-view--hidden");
    if (editorView) editorView.classList.add("persona-hub__editor-view--hidden");
    if (wizardView) wizardView.classList.remove("persona-wizard--hidden");
    this._viewMode = "wizard";

    // 每次进入默认展示表单步骤（若上次停留在进度/错误页则回退）
    const form = document.getElementById("persona-wizard-form");
    const progress = document.getElementById("persona-wizard-progress");
    if (form) form.classList.remove("persona-wizard__panel--hidden");
    if (progress) progress.classList.add("persona-wizard__panel--hidden");

    // 重置提示文案与颜色，避免上次校验的红色提示残留
    const hint = document.getElementById("persona-wizard-story-hint");
    if (hint) {
      hint.textContent = "选一个喜欢的故事设定，生成时会融进两人的背景";
      hint.style.color = "";
    }
  }

  _esc(str) {
    return String(str || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async _recommendConcepts() {
    const storyEl = document.getElementById("persona-wizard-story");
    const relEl = document.getElementById("persona-wizard-relationship");
    const descEl = document.getElementById("persona-wizard-desc");
    const hint = document.getElementById("persona-wizard-story-hint");
    const box = document.getElementById("persona-wizard-concepts");
    if (!box) return;

    const storySeed = storyEl ? storyEl.value.trim() : "";
    if (!storySeed) {
      // Non-blocking hint + focus instead of alert(): a native modal steals
      // focus in Electron and can leave the wizard uneditable afterwards.
      if (hint) hint.textContent = "请先在「两人故事起因」里简单描述一下你们的开始，我再为你推荐";
      if (hint) hint.style.color = "var(--danger, #e5484d)";
      if (storyEl) storyEl.focus();
      return;
    }
    if (hint) {
      hint.textContent = "正在生成故事概念…";
      hint.style.color = "";
    }
    box.innerHTML = `<div class="persona-wizard__concepts-loading">AI 正在构思中…</div>`;
    try {
      const r = await window.aerie.api.request({
        method: "POST",
        path: "/api/persona/hub/generate/concepts",
        body: JSON.stringify({
          relationship_type: relEl && relEl.value.trim() ? relEl.value.trim() : "恋人",
          story_seed: storySeed,
          description: descEl ? descEl.value.trim() : "",
        }),
        headers: { "Content-Type": "application/json" },
      });
      const concepts = (r && r.data && r.data.concepts) || [];
      if (!concepts.length) {
        throw new Error("没有拿到推荐，请稍后重试");
      }
      if (hint) hint.textContent = "点击选择一个，生成时会作为两人的相识背景";
      this._renderConcepts(concepts);
    } catch (e) {
      console.error("recommend concepts failed:", e);
      box.innerHTML = "";
      if (hint) hint.textContent = "推荐失败：" + (e.message || "unknown") + "，可稍后再试";
    }
  }

  _renderConcepts(concepts) {
    const box = document.getElementById("persona-wizard-concepts");
    if (!box) return;
    box.innerHTML = concepts.map((c, idx) => `
      <button type="button" class="persona-wizard__concept" data-idx="${idx}">
        <span class="persona-wizard__concept-title">${this._esc(c.title || "")}</span>
        <span class="persona-wizard__concept-tagline">${this._esc(c.tagline || "")}</span>
        ${(c.tags || []).length ? `<span class="persona-wizard__concept-tags">${(c.tags || []).map((t) => this._esc(t)).join(" ")}</span>` : ""}
      </button>
    `).join("");

    box.querySelectorAll(".persona-wizard__concept").forEach((btn, idx) => {
      btn.addEventListener("click", () => {
        const selected = concepts[idx];
        this._selectedConcept = selected;
        box.querySelectorAll(".persona-wizard__concept").forEach((b) => {
          b.classList.toggle("persona-wizard__concept--selected", b === btn);
        });
      });
    });
  }

  async _startGeneration() {
    const descEl = document.getElementById("persona-wizard-desc");
    const description = descEl ? descEl.value.trim() : "";
    if (!description) {
      // Non-blocking hint + focus instead of alert() (same Electron focus bug).
      const hint = document.getElementById("persona-wizard-story-hint");
      if (hint) {
        hint.textContent = "请先在上方描述你的角色，再开始生成";
        hint.style.color = "var(--danger, #e5484d)";
      }
      if (descEl) descEl.focus();
      return;
    }

    const options = {};
    const nameEl = document.getElementById("persona-wizard-name");
    const englishNameEl = document.getElementById("persona-wizard-english_name");
    const genderEl = document.getElementById("persona-wizard-gender");
    const ageEl = document.getElementById("persona-wizard-age");
    const relEl = document.getElementById("persona-wizard-relationship");
    const storyEl = document.getElementById("persona-wizard-story");
    const userNameEl = document.getElementById("persona-wizard-user-name");
    if (nameEl && nameEl.value.trim()) options.name = nameEl.value.trim();
    if (englishNameEl && englishNameEl.value.trim()) options.english_name = englishNameEl.value.trim();
    if (genderEl && genderEl.value) options.gender = genderEl.value;
    if (ageEl && ageEl.value !== "") {
      const age = parseInt(ageEl.value, 10);
      if (!isNaN(age)) options.age = age;
    }
    if (relEl && relEl.value.trim()) options.relationship_type = relEl.value.trim();
    if (storyEl && storyEl.value.trim()) options.story_seed = storyEl.value.trim();
    if (userNameEl && userNameEl.value.trim()) options.user_name = userNameEl.value.trim();
    if (this._selectedConcept) options.story_concept = this._selectedConcept;

    this._genPayload = { description, options };
    this._resetWizardProgress();

    const form = document.getElementById("persona-wizard-form");
    const progress = document.getElementById("persona-wizard-progress");
    if (form) form.classList.add("persona-wizard__panel--hidden");
    if (progress) progress.classList.remove("persona-wizard__panel--hidden");

    try {
      const r = await window.aerie.api.request({
        method: "POST",
        path: "/api/persona/hub/generate",
        body: JSON.stringify(this._genPayload),
        headers: { "Content-Type": "application/json" },
      });
      const taskId = r && r.data && r.data.task_id;
      if (!taskId) {
        throw new Error((r && r.data && r.data.error) || "返回数据格式异常");
      }
      this._genTaskId = taskId;
      this._genPollCount = 0;
      this._pollGeneration();
    } catch (e) {
      console.error("start generation failed:", e);
      this._showWizardError("生成任务创建失败: " + (e.message || "unknown"));
    }
  }

  _resetWizardProgress() {
    const fill = document.getElementById("persona-wizard-bar-fill");
    if (fill) fill.style.width = "0%";
    const msg = document.getElementById("persona-wizard-msg");
    if (msg) msg.textContent = "正在分析角色概念";
    const err = document.getElementById("persona-wizard-error");
    if (err) err.classList.add("persona-wizard__error--hidden");
    document.querySelectorAll(".persona-wizard__stage").forEach((li) => {
      li.classList.remove("persona-wizard__stage--done", "persona-wizard__stage--active");
    });
  }

  _pollGeneration() {
    if (this._genTimer) {
      clearTimeout(this._genTimer);
      this._genTimer = null;
    }
    this._genTimer = setTimeout(async () => {
      this._genTimer = null;
      if (!this._genTaskId) return;
      this._genPollCount += 1;
      try {
        const r = await window.aerie.api.request({
          method: "GET",
          path: `/api/persona/hub/generate/${this._genTaskId}`,
        });
        const task = r && r.data && r.data.task;
        if (!task) {
          this._showWizardError("生成任务已失效，请重试");
          return;
        }
        this._updateWizardProgress(task);

        if (task.state === "done") {
          const persona = task.persona;
          const pid = task.persona_id;
          this._currentId = pid;
          if (persona) this._fillForm(persona);
          this._showEditor();
          if (pid) this._loadThreeViewSummary(pid);
          this._loadList();
          alert("人设已生成，可继续完善细节");
        } else if (task.state === "error") {
          this._showWizardError(task.error || "生成失败，请重试");
        } else if (this._genPollCount >= 120) {
          this._showWizardError("生成超时，请重试");
        } else {
          this._pollGeneration();
        }
      } catch (e) {
        console.error("poll generation failed:", e);
        if (this._genPollCount >= 120) {
          this._showWizardError("生成超时，请重试");
        } else {
          this._pollGeneration();
        }
      }
    }, 800);
  }

  _updateWizardProgress(task) {
    const pct = task.progress || 0;
    const fill = document.getElementById("persona-wizard-bar-fill");
    if (fill) fill.style.width = pct + "%";

    const msg = document.getElementById("persona-wizard-msg");
    if (msg) msg.textContent = task.message || task.stage || "";

    const order = ["concept", "detail", "assemble", "prompt", "finalize"];
    const stageIdx = typeof task.stage_index === "number"
      ? task.stage_index
      : order.indexOf(task.stage_key);
    document.querySelectorAll(".persona-wizard__stage").forEach((li) => {
      li.classList.remove("persona-wizard__stage--done", "persona-wizard__stage--active");
      const keyIdx = order.indexOf(li.getAttribute("data-key"));
      if (keyIdx >= 0 && stageIdx >= 0) {
        if (keyIdx < stageIdx) {
          li.classList.add("persona-wizard__stage--done");
        } else if (keyIdx === stageIdx) {
          li.classList.add("persona-wizard__stage--active");
        }
      }
    });
  }

  _showWizardError(msg) {
    if (this._genTimer) {
      clearTimeout(this._genTimer);
      this._genTimer = null;
    }
    const err = document.getElementById("persona-wizard-error");
    const errText = document.getElementById("persona-wizard-error-text");
    if (err) err.classList.remove("persona-wizard__error--hidden");
    if (errText) errText.textContent = msg;
  }

  async _exportPersona(personaId) {
    try {
      const r = await window.aerie.api.request({
        method: "GET",
        path: `/api/persona/hub/${personaId}/export`,
      });
      let data;
      if (r && r.data) {
        data = typeof r.data === "string" ? JSON.parse(r.data) : r.data;
      }
      if (!data || !data.id) {
        throw new Error("导出数据无效");
      }

      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `persona_${data.id || personaId}.json`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("export persona failed:", e);
      alert("导出失败: " + (e.message || "unknown"));
    }
  }

  async _importPersona(file) {
    try {
      const arrayBuffer = await file.arrayBuffer();
      const uint8Array = new Uint8Array(arrayBuffer);

      const r = await window.aerie.api.upload({
        path: "/api/persona/hub/import",
        bytes: Array.from(uint8Array),
        filename: file.name || "persona.json",
        contentType: "application/json",
      });

      const data = (r && r.data) ? r.data : r;
      if (data && data.status === "ok") {
        await this._loadList();
        alert("导入成功！");
      } else {
        throw new Error((data && data.error) || "导入失败");
      }
    } catch (e) {
      console.error("import persona failed:", e);
      alert("导入失败: " + (e.message || "unknown"));
    }
  }
}

window.PersonaHubPanel = PersonaHubPanel;
