/**
 * Aerie v13.0 — 主动推送管理面板
 * 管理主动消息推送的开关、场景配置、事件历史
 */

class ProactiveManager {
  constructor() {
    this.status = null;
    this.scenes = {};
    this.events = [];
    this.intervalId = null;
  }

  async init() {
    await this.loadStatus();
    await this.loadScenes();
    await this.loadEvents();
    this.startAutoRefresh();
    this.renderPanel();
    this.bindEvents();
  }

  destroy() {
    this.stopAutoRefresh();
  }

  startAutoRefresh() {
    this.stopAutoRefresh();
    this.intervalId = setInterval(() => {
      this.loadStatus();
      this.loadEvents();
    }, 30000);
  }

  stopAutoRefresh() {
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  async loadStatus() {
    try {
      const res = await fetch('/api/proactive/status');
      this.status = await res.json();
      this.updateStatusUI();
    } catch (e) {
      console.warn('load proactive status failed:', e);
    }
  }

  async loadScenes() {
    try {
      const res = await fetch('/api/proactive/scenes');
      const data = await res.json();
      this.scenes = data.scenes || {};
      this.updateScenesUI();
    } catch (e) {
      console.warn('load proactive scenes failed:', e);
    }
  }

  async loadEvents() {
    try {
      const res = await fetch('/api/proactive/events?limit=20');
      const data = await res.json();
      this.events = data.events || [];
      this.updateEventsUI();
    } catch (e) {
      console.warn('load proactive events failed:', e);
    }
  }

  async toggleEnabled(enabled) {
    try {
      await fetch('/api/proactive/toggle', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ enabled })
      });
      await this.loadStatus();
    } catch (e) {
      console.warn('toggle proactive failed:', e);
    }
  }

  async triggerScene(sceneName) {
    try {
      const res = await fetch('/api/proactive/trigger', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ scene: sceneName })
      });
      const data = await res.json();
      if (data.success) {
        this.showToast(`已触发：${sceneName}`);
      } else {
        this.showToast(`触发失败：${sceneName}`, 'error');
      }
    } catch (e) {
      this.showToast('触发失败', 'error');
    }
  }

  updateStatusUI() {
    const statusEl = document.getElementById('proactive-status-value');
    const toggleEl = document.getElementById('proactive-toggle');
    const dailyEl = document.getElementById('proactive-daily-count');
    const idleEl = document.getElementById('proactive-idle-time');

    if (!this.status) return;

    if (statusEl) {
      const isRunning = this.status.running && this.status.scheduler?.running;
      statusEl.textContent = isRunning ? '运行中' : '已停止';
      statusEl.className = `proactive-status ${isRunning ? 'active' : 'inactive'}`;
    }

    if (toggleEl) {
      toggleEl.checked = this.status.scheduler?.policy_enabled ?? true;
    }

    if (dailyEl) {
      dailyEl.textContent = this.status.scheduler?.daily_count ?? 0;
    }

    if (idleEl) {
      const mins = this.status.idle_minutes ?? 0;
      if (mins < 60) {
        idleEl.textContent = `${Math.round(mins)} 分钟`;
      } else {
        idleEl.textContent = `${(mins / 60).toFixed(1)} 小时`;
      }
    }
  }

  updateScenesUI() {
    const container = document.getElementById('proactive-scenes-list');
    if (!container) return;

    const scenes = Object.entries(this.scenes);
    if (scenes.length === 0) {
      container.innerHTML = '<div class="empty-state">暂无场景配置</div>';
      return;
    }

    container.innerHTML = scenes.map(([name, cfg]) => {
      const triggerType = cfg.cron ? `定时：${cfg.cron}` :
                         cfg.trigger ? `事件：${cfg.trigger}` :
                         cfg.custom_dispatcher ? `自定义：${cfg.custom_dispatcher}` : '手动';
      return `
        <div class="scene-card">
          <div class="scene-header">
            <span class="scene-name">${name}</span>
            <button class="scene-trigger-btn" data-scene="${name}">
              立即触发
            </button>
          </div>
          <div class="scene-meta">
            <span class="scene-trigger">${triggerType}</span>
            ${cfg.mood_aware ? '<span class="badge mood">情绪感知</span>' : ''}
            ${cfg.exempt_quiet ? '<span class="badge exempt">免打扰豁免</span>' : ''}
          </div>
          ${cfg.template ? `<div class="scene-template">模板：${cfg.template}</div>` : ''}
        </div>
      `;
    }).join('');

    container.querySelectorAll('.scene-trigger-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        const scene = e.target.dataset.scene;
        this.triggerScene(scene);
      });
    });
  }

  updateEventsUI() {
    const container = document.getElementById('proactive-events-list');
    if (!container) return;

    if (this.events.length === 0) {
      container.innerHTML = '<div class="empty-state">暂无事件记录</div>';
      return;
    }

    container.innerHTML = this.events.map(ev => {
      const time = new Date(ev.timestamp).toLocaleTimeString('zh-CN');
      const priorityColors = {
        10: 'critical', 9: 'critical', 8: 'high',
        7: 'high', 6: 'medium', 5: 'medium',
        4: 'low', 3: 'low', 2: 'info', 1: 'info'
      };
      const prioClass = priorityColors[ev.priority] || 'info';
      return `
        <div class="event-item">
          <div class="event-time">${time}</div>
          <div class="event-type">${ev.type}</div>
          <div class="event-priority ${prioClass}">P${ev.priority}</div>
          <div class="event-source">${ev.source}</div>
        </div>
      `;
    }).join('');
  }

  showToast(message, type = 'success') {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 2000);
  }

  renderPanel() {
    const panel = document.getElementById('proactive-panel');
    if (!panel) return;

    panel.innerHTML = `
      <div class="proactive-container">
        <div class="proactive-header">
          <h3>主动推送管理</h3>
          <div class="proactive-toggle-wrap">
            <label class="switch">
              <input type="checkbox" id="proactive-toggle" />
              <span class="slider"></span>
            </label>
            <span id="proactive-status-value" class="proactive-status">--</span>
          </div>
        </div>

        <div class="proactive-stats">
          <div class="stat-card">
            <div class="stat-label">今日推送</div>
            <div class="stat-value" id="proactive-daily-count">--</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">空闲时长</div>
            <div class="stat-value" id="proactive-idle-time">--</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">场景数</div>
            <div class="stat-value" id="proactive-scene-count">--</div>
          </div>
        </div>

        <div class="proactive-section">
          <h4>推送场景</h4>
          <div id="proactive-scenes-list" class="scenes-list">
            加载中...
          </div>
        </div>

        <div class="proactive-section">
          <h4>最近事件</h4>
          <div id="proactive-events-list" class="events-list">
            加载中...
          </div>
        </div>

        <div class="proactive-section">
          <h4>触发源说明</h4>
          <div class="trigger-sources">
            <div class="trigger-source">
              <div class="trigger-icon"><svg class="icon icon--20" style="color: #f59e0b;"><use href="#icon-ui-calendar"/></svg></div>
              <div class="trigger-info">
                <div class="trigger-title">定时触发</div>
                <div class="trigger-desc">基于 Cron 表达式的定时推送，如早安、午安、晚安等</div>
              </div>
            </div>
            <div class="trigger-source">
              <div class="trigger-icon"><svg class="icon icon--20" style="color: #ec4899;"><use href="#icon-ui-thought"/></svg></div>
              <div class="trigger-info">
                <div class="trigger-title">情绪触发</div>
                <div class="trigger-desc">基于思念值、情绪状态的主动推送，她想你了才会发</div>
              </div>
            </div>
            <div class="trigger-source">
              <div class="trigger-icon"><svg class="icon icon--20" style="color: #8b5cf6;"><use href="#icon-ui-target"/></svg></div>
              <div class="trigger-info">
                <div class="trigger-title">事件触发</div>
                <div class="trigger-desc">用户上线、纪念日、天气变化、待办到期等事件驱动</div>
              </div>
            </div>
          </div>
        </div>
      </div>
    `;
  }

  bindEvents() {
    const toggle = document.getElementById('proactive-toggle');
    if (toggle) {
      toggle.addEventListener('change', (e) => {
        this.toggleEnabled(e.target.checked);
      });
    }
  }
}

// 全局实例
let proactiveManager = null;

function initProactivePanel() {
  if (!proactiveManager) {
    proactiveManager = new ProactiveManager();
  }
  proactiveManager.init();
  return proactiveManager;
}

// 暴露到全局
window.ProactiveManager = ProactiveManager;
window.initProactivePanel = initProactivePanel;
