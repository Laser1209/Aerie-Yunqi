/* Aerie · 云栖 v9.0 — Chat renderer logic
 *
 * Responsibilities:
 *  - Render incoming/outgoing messages
 *  - Send user input to /api/chat/send
 *  - Load recent history from /api/chat/history
 *  - Poll /api/chat/poll every 5s for new messages
 *  - Apply message segmentation (拟人化分段) visualization
 *  - Update QQ connection status indicator
 */

(function () {
  'use strict';

  const API = window.AerieAPI;
  const messagesEl = document.getElementById('messages');
  const inputEl = document.getElementById('composer-input');
  const sendBtn = document.getElementById('composer-send');
  const qqDotEl = document.getElementById('qq-dot');
  const qqStatusEl = document.getElementById('qq-status');

  if (!API) {
    console.warn('AerieAPI not ready; chat.js exiting.');
    return;
  }

  // ---- State ----
  let lastPollTimestamp = 0;
  let knownMessageIds = new Set();
  let pollTimer = null;
  let isSending = false;

  // ---- Helpers ----
  function escapeHtml(str) {
    if (str == null) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function fmtTime(ts) {
    if (!ts) return '';
    const d = new Date(typeof ts === 'number' && ts < 1e12 ? ts * 1000 : ts);
    if (isNaN(d.getTime())) return '';
    const pad = (n) => (n < 10 ? '0' + n : '' + n);
    return pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function renderMessage(msg) {
    if (!msg || !msg.id) return;
    if (knownMessageIds.has(msg.id)) return;
    knownMessageIds.add(msg.id);

    const wrap = document.createElement('div');
    const role = msg.role || (msg.direction === 'out' ? 'assistant' : 'user');
    wrap.className = 'msg msg-' + role;
    wrap.dataset.id = msg.id;

    const meta = document.createElement('div');
    meta.className = 'msg-meta';
    meta.textContent = (role === 'user' ? '你' : '伊塔') + ' · ' + fmtTime(msg.timestamp);

    const body = document.createElement('div');
    body.className = 'msg-body';
    // Support segmented content (array) and single string.
    if (Array.isArray(msg.segments) && msg.segments.length > 1) {
      body.innerHTML = msg.segments
        .map((s, i) => '<p class="msg-segment" data-idx="' + i + '">' + escapeHtml(s) + '</p>')
        .join('');
    } else {
      body.innerHTML = '<p class="msg-segment">' + escapeHtml(msg.content || '') + '</p>';
    }

    wrap.appendChild(meta);
    wrap.appendChild(body);
    messagesEl.appendChild(wrap);

    // Auto-scroll
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function renderHistory(items) {
    messagesEl.innerHTML = '';
    knownMessageIds.clear();
    if (!Array.isArray(items)) return;
    items.forEach(renderMessage);
  }

  async function loadHistory() {
    try {
      const data = await API.get('/api/chat/history?limit=50');
      if (data && Array.isArray(data.items)) {
        renderHistory(data.items);
        if (data.items.length > 0) {
          lastPollTimestamp = Math.max(
            ...data.items.map((m) => Number(m.timestamp) || 0)
          );
        }
      }
    } catch (e) {
      console.warn('loadHistory failed:', e);
    }
  }

  async function pollNew() {
    try {
      const url = '/api/chat/poll?since=' + encodeURIComponent(lastPollTimestamp);
      const data = await API.get(url);
      if (data && Array.isArray(data.items)) {
        data.items.forEach(renderMessage);
        if (data.items.length > 0) {
          lastPollTimestamp = Math.max(
            lastPollTimestamp,
            ...data.items.map((m) => Number(m.timestamp) || 0)
          );
        }
      }
    } catch (e) {
      // Silent: polling is best-effort.
    }
  }

  function startPolling(intervalMs) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(pollNew, intervalMs || 5000);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  async function sendCurrent() {
    if (isSending) return;
    const text = (inputEl.value || '').trim();
    if (!text) return;
    if (text.length > 2000) {
      alert('消息过长（>2000 字符），已截断。');
      inputEl.value = text.slice(0, 2000);
      return;
    }
    isSending = true;
    sendBtn.disabled = true;
    try {
      const data = await API.post('/api/chat/send', { content: text });
      // Optimistic local echo.
      const echoId = 'local-' + Date.now();
      renderMessage({
        id: echoId,
        role: 'user',
        content: text,
        timestamp: Math.floor(Date.now() / 1000),
      });
      inputEl.value = '';
      // Backend will deliver reply via poll.
      if (data && data.id) {
        lastPollTimestamp = Math.max(lastPollTimestamp, Number(data.timestamp) || 0);
      }
    } catch (e) {
      console.error('send failed:', e);
      alert('发送失败：' + (e && e.message ? e.message : e));
    } finally {
      isSending = false;
      sendBtn.disabled = false;
      inputEl.focus();
    }
  }

  async function refreshQQStatus() {
    try {
      const data = await API.get('/api/qq/status');
      if (data && data.connected) {
        qqDotEl.classList.add('on');
        qqDotEl.classList.remove('off');
        qqStatusEl.textContent = '已连接' + (data.self_qq ? ' · ' + data.self_qq : '');
      } else {
        qqDotEl.classList.add('off');
        qqDotEl.classList.remove('on');
        qqStatusEl.textContent = '未连接';
      }
    } catch (e) {
      qqDotEl.classList.add('off');
      qqDotEl.classList.remove('on');
      qqStatusEl.textContent = '服务不可用';
    }
  }

  // ---- Wire up ----
  if (sendBtn) {
    sendBtn.addEventListener('click', sendCurrent);
  }
  if (inputEl) {
    inputEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendCurrent();
      }
    });
  }

  // Expose for app.js coordination
  window.AerieChat = {
    loadHistory,
    pollNew,
    startPolling,
    stopPolling,
    refreshQQStatus,
    renderMessage,
  };

  // Initial bootstrap (deferred to app.js for coordination)
  document.addEventListener('DOMContentLoaded', () => {
    loadHistory();
    startPolling(5000);
    refreshQQStatus();
    setInterval(refreshQQStatus, 10000);
  });
})();
