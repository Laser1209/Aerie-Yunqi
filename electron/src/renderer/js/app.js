/* Aerie · 云栖 v9.0 — App entry & coordination
 *
 * Responsibilities:
 *  - Boot the application
 *  - Coordinate chat, sidebar, theme switcher
 *  - Provide a small dispatcher for proactive-messenger toasts
 *  - Wire global keyboard shortcuts
 */

(function () {
  'use strict';

  const API = window.AerieAPI;
  const CHAT = window.AerieChat;
  const bridge = window.aerie;

  // ---- Toast / proactive message popup ----
  function showToast(text) {
    if (!text) return;
    const layer = document.getElementById('toast-layer') || createToastLayer();
    const el = document.createElement('div');
    el.className = 'toast';
    el.textContent = text;
    layer.appendChild(el);
    setTimeout(() => {
      el.classList.add('toast-leave');
      setTimeout(() => el.remove(), 400);
    }, 4000);
  }

  function createToastLayer() {
    const layer = document.createElement('div');
    layer.id = 'toast-layer';
    layer.style.cssText = 'position:fixed;top:16px;right:16px;display:flex;flex-direction:column;gap:8px;z-index:9999;pointer-events:none;';
    document.body.appendChild(layer);
    return layer;
  }

  // ---- Proactive message preview ----
  async function pollProactive() {
    if (!API) return;
    try {
      const data = await API.get('/api/proactive/state');
      if (data && data.last_pushed_at && data.last_preview) {
        // Optionally show preview if new.
        const key = 'aerie.lastPreviewShownAt';
        const last = Number(localStorage.getItem(key) || 0);
        if (data.last_pushed_at > last) {
          showToast('伊塔: ' + data.last_preview);
          localStorage.setItem(key, String(data.last_pushed_at));
        }
      }
    } catch (e) {
      // Silent.
    }
  }

  // ---- Bootstrap ----
  document.addEventListener('DOMContentLoaded', () => {
    // 1. Theme is loaded by theme-switcher.js (synchronous)
    if (window.AerieTheme && typeof window.AerieTheme.init === 'function') {
      window.AerieTheme.init();
    }

    // 2. Sidebar tab logic
    if (window.AerieSidebar && typeof window.AerieSidebar.init === 'function') {
      window.AerieSidebar.init();
    }

    // 3. Chat (history + poll) — already self-init in chat.js
    if (CHAT && typeof CHAT.loadHistory === 'function') {
      // already invoked by chat.js on DOMContentLoaded; safety re-call no-ops
    }

    // 4. Proactive polling
    setInterval(pollProactive, 8000);
    pollProactive();

    // 5. Global keyboard shortcut: Ctrl+, → focus composer
    document.addEventListener('keydown', (e) => {
      if (e.ctrlKey && e.key === ',') {
        const input = document.getElementById('composer-input');
        if (input) input.focus();
        e.preventDefault();
      }
    });

    console.log('[Aerie] app ready');
  });

  // ---- Bridge exposure for other renderer scripts ----
  window.AerieApp = {
    showToast,
    pollProactive,
  };
})();
