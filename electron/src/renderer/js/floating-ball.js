/* Aerie · 云栖 v9.0 — Floating ball renderer
 *
 * Responsibilities:
 *  - Drag the ball across the screen
 *  - Smart edge吸附 (stick to nearest edge when released)
 *  - Single-click expand → request main window
 *  - Double-click → open main window
 *  - Idle semi-transparent (5s without interaction)
 */

(function () {
  'use strict';

  const ball = document.getElementById('ball');
  if (!ball) {
    console.warn('Floating ball DOM not found.');
    return;
  }

  // ---- State ----
  let dragging = false;
  let dragStartX = 0;
  let dragStartY = 0;
  let ballStartX = 0;
  let ballStartY = 0;
  let lastInteractionAt = Date.now();
  let idleTimer = null;
  let clickGuardUntil = 0;

  // ---- Idle detection ----
  const IDLE_AFTER_MS = 5000;
  const IDLE_OPACITY = 0.3;
  const ACTIVE_OPACITY = 1.0;

  function markActive() {
    lastInteractionAt = Date.now();
    ball.style.opacity = String(ACTIVE_OPACITY);
  }

  function startIdleWatcher() {
    if (idleTimer) clearInterval(idleTimer);
    idleTimer = setInterval(() => {
      const idleFor = Date.now() - lastInteractionAt;
      if (idleFor >= IDLE_AFTER_MS) {
        ball.style.opacity = String(IDLE_OPACITY);
      }
    }, 1000);
  }

  // ---- Dragging ----
  function getCurrentPos() {
    const rect = ball.getBoundingClientRect();
    return { x: rect.left, y: rect.top };
  }

  function onMouseDown(e) {
    e.preventDefault();
    dragging = true;
    clickGuardUntil = Date.now() + 250;
    const pos = getCurrentPos();
    ballStartX = pos.x;
    ballStartY = pos.y;
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    markActive();
    document.body.style.userSelect = 'none';
  }

  function onMouseMove(e) {
    if (!dragging) return;
    const dx = e.clientX - dragStartX;
    const dy = e.clientY - dragStartY;
    const newX = ballStartX + dx;
    const newY = ballStartY + dy;
    // Clamp to viewport
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const bw = ball.offsetWidth;
    const bh = ball.offsetHeight;
    const clampedX = Math.max(0, Math.min(vw - bw, newX));
    const clampedY = Math.max(0, Math.min(vh - bh, newY));
    ball.style.left = clampedX + 'px';
    ball.style.top = clampedY + 'px';
    ball.style.right = 'auto';
    ball.style.bottom = 'auto';
  }

  function onMouseUp() {
    if (!dragging) return;
    dragging = false;
    document.body.style.userSelect = '';
    snapToEdge();
  }

  function snapToEdge() {
    const rect = ball.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const bw = rect.width;
    const bh = rect.height;
    const centerX = rect.left + bw / 2;
    const centerY = rect.top + bh / 2;
    const margin = 16;
    // Snap X to nearest edge
    const snapLeft = centerX < vw / 2;
    const snapX = snapLeft ? margin : vw - bw - margin;
    // Snap Y to nearest edge
    const snapTop = centerY < vh / 2;
    const snapY = snapTop ? margin : vh - bh - margin;
    ball.style.transition = 'left 200ms ease-out, top 200ms ease-out';
    ball.style.left = snapX + 'px';
    ball.style.top = snapY + 'px';
    setTimeout(() => {
      ball.style.transition = '';
    }, 220);
  }

  // ---- Click / double-click ----
  function onClick() {
    // Suppress click immediately after drag-release
    if (Date.now() < clickGuardUntil) return;
    if (window.aerie && window.aerie.ball && window.aerie.ball.expand) {
      window.aerie.ball.expand();
    }
  }

  function onDoubleClick() {
    if (Date.now() < clickGuardUntil) return;
    // Same as expand — main process will show main window.
    if (window.aerie && window.aerie.ball && window.aerie.ball.expand) {
      window.aerie.ball.expand();
    }
  }

  // ---- Wire up ----
  ball.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
  ball.addEventListener('click', onClick);
  ball.addEventListener('dblclick', onDoubleClick);
  ball.addEventListener('mouseenter', markActive);
  ball.addEventListener('mouseleave', () => {
    // Reset last interaction so the idle watcher can fade again.
    lastInteractionAt = Date.now() - IDLE_AFTER_MS + 1000;
  });

  // Keyboard accessibility: Space / Enter triggers expand
  ball.setAttribute('tabindex', '0');
  ball.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick();
    }
  });

  // Initial: set default position via CSS to bottom-right; let snapToEdge align.
  // Wait for layout, then snap to right-bottom edge.
  requestAnimationFrame(() => {
    snapToEdge();
    startIdleWatcher();
  });
})();
