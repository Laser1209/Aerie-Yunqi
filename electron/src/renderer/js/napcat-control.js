/* Aerie · 云栖 v9.0 — NapCat control panel
 *
 * Wires the "系统 / NapCat" tab to the IPC bridge exposed in preload.js.
 * Also listens for `napcat:bootstrap` events from the main process so
 * startup auto-connect feedback appears immediately.
 */
(function () {
  'use strict';

  const bridge = window.aerie;
  const API = window.AerieAPI;

  if (!bridge || !bridge.napcat) return;

  // --- Elements ---
  const dot = document.getElementById('napcat-dot');
  const dotTop = document.getElementById('napcat-dot-top');
  const statusText = document.getElementById('napcat-status-text');
  const logEl = document.getElementById('napcat-log');
  const startBtn = document.getElementById('napcat-start');
  const stopBtn = document.getElementById('napcat-stop');
  const bootBtn = document.getElementById('napcat-bootstrap');
  const backendDot = document.getElementById('backend-dot');

  function setState(state, label) {
    const colorMap = {
      ok: '#4cd964',
      running: '#4cd964',
      starting: '#f5a623',
      error: '#ff5252',
      stopped: '#9aa0a6',
      unknown: '#9aa0a6',
    };
    const cls = colorMap[state] || '#9aa0a6';
    [dot, dotTop].forEach((d) => {
      if (!d) return;
      d.setAttribute('data-state', state);
      d.style.background = cls;
    });
    if (label && statusText) statusText.textContent = label;
  }

  function appendLog(line) {
    if (!logEl) return;
    const ts = new Date().toLocaleTimeString();
    logEl.textContent = `[${ts}] ${line}\n` + (logEl.textContent || '').split('\n').slice(0, 19).join('\n');
  }

  async function refreshStatus() {
    try {
      const r = await bridge.napcat.status();
      if (!r || r.status !== 200) {
        setState('unknown', '后端不可用');
        return;
      }
      const s = r.data || {};
      if (s.running || s.ws_port_open) {
        setState('ok', s.ws_port_open ? 'NapCat WS 已就绪' : 'NapCat 运行中（端口未开放）');
      } else if (s.installed) {
        setState('stopped', 'NapCat 未启动');
      } else {
        setState('error', '未检测到 NapCat 启动器');
      }
    } catch (e) {
      setState('error', '查询失败: ' + (e && e.message || e));
    }
  }

  // Poll QQ status separately so the top bar reflects real-time connection.
  async function pollQQ() {
    if (!API) return;
    try {
      const r = await API.get('/api/qq/status');
      if (r && r.connected) {
        const dotEl = backendDot || document.getElementById('backend-dot');
        if (dotEl) {
          dotEl.setAttribute('data-state', 'ok');
          dotEl.style.background = '#4cd964';
        }
        const st = document.getElementById('qq-status');
        if (st) st.textContent = '已连接 (QQ ' + (r.self_qq || '?') + ')';
      } else {
        const dotEl = backendDot || document.getElementById('backend-dot');
        if (dotEl) {
          dotEl.setAttribute('data-state', 'starting');
          dotEl.style.background = '#f5a623';
        }
        const st = document.getElementById('qq-status');
        if (st) st.textContent = '未连接';
      }
    } catch (e) {
      const st = document.getElementById('qq-status');
      if (st) st.textContent = '连接中…';
    }
  }

  async function handleStart() {
    setState('starting', '正在启动 NapCat…');
    appendLog('请求启动 NapCat (prefer_user=true)');
    startBtn.disabled = true;
    try {
      const r = await bridge.napcat.start({ prefer_user: true, wait_port: true });
      if (r && r.data) {
        appendLog('启动结果: ' + JSON.stringify(r.data));
        if (r.data.port_open) {
          setState('ok', 'NapCat WS 已就绪');
        } else if (r.data.running) {
          setState('starting', 'NapCat 启动中…');
        } else {
          setState('error', r.data.message || '启动失败');
        }
      } else {
        setState('error', '启动失败: ' + (r && r.error || 'unknown'));
      }
    } catch (e) {
      setState('error', '启动异常: ' + (e && e.message || e));
    } finally {
      startBtn.disabled = false;
      setTimeout(refreshStatus, 1000);
    }
  }

  async function handleStop() {
    appendLog('请求停止 NapCat');
    stopBtn.disabled = true;
    try {
      const r = await bridge.napcat.stop();
      if (r && r.data) {
        appendLog('停止结果: ' + JSON.stringify(r.data));
        setState('stopped', 'NapCat 已停止');
      }
    } catch (e) {
      appendLog('停止失败: ' + e);
    } finally {
      stopBtn.disabled = false;
      setTimeout(refreshStatus, 1000);
    }
  }

  async function handleBootstrap() {
    appendLog('一键连接：自动检测并启动 NapCat');
    bootBtn.disabled = true;
    setState('starting', '正在一键连接…');
    try {
      const r = await bridge.napcat.bootstrap({ prefer_user: true });
      if (r && r.data) {
        appendLog('连接结果: ' + JSON.stringify(r.data));
        if (r.data.status === 'ok' || r.data.status === 'already_ready') {
          setState('ok', '已就绪，等待 QQ 登录');
        } else if (r.data.status === 'not_installed') {
          setState('error', 'NapCat 启动器不存在');
        } else {
          setState('starting', r.data.message || '启动中…');
        }
      }
    } catch (e) {
      setState('error', '连接异常: ' + (e && e.message || e));
    } finally {
      bootBtn.disabled = false;
      setTimeout(refreshStatus, 1500);
    }
  }

  function bind() {
    if (startBtn) startBtn.addEventListener('click', handleStart);
    if (stopBtn) stopBtn.addEventListener('click', handleStop);
    if (bootBtn) bootBtn.addEventListener('click', handleBootstrap);
  }

  function onBootstrapEvent(payload) {
    if (!payload) return;
    appendLog('主进程引导结果: ' + JSON.stringify(payload));
    if (payload.status === 'ok' || payload.status === 'already_ready') {
      setState('ok', 'NapCat WS 已就绪');
    } else if (payload.status === 'not_installed') {
      setState('error', '未检测到 NapCat 启动器');
    } else {
      setState('starting', payload.message || '启动中…');
    }
  }

  function init() {
    bind();
    refreshStatus();
    pollQQ();
    setInterval(refreshStatus, 8000);
    setInterval(pollQQ, 5000);
    if (bridge.on) {
      bridge.on('napcat:bootstrap', onBootstrapEvent);
      bridge.on('backend:ready', () => {
        const d = document.getElementById('backend-dot');
        if (d) {
          d.setAttribute('data-state', 'ok');
          d.style.background = '#4cd964';
        }
      });
      bridge.on('backend:error', (msg) => {
        const d = document.getElementById('backend-dot');
        if (d) {
          d.setAttribute('data-state', 'error');
          d.style.background = '#ff5252';
        }
        appendLog('后端错误: ' + msg);
      });
      bridge.on('backend:timeout', () => {
        const d = document.getElementById('backend-dot');
        if (d) {
          d.setAttribute('data-state', 'error');
          d.style.background = '#ff5252';
        }
        appendLog('后端启动超时');
      });
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
