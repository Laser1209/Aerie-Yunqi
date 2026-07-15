/* Aerie · 云栖 v9.0 — Floating ball renderer
 *
 * Responsibilities:
 *  - Drag the ball across the screen via IPC (window-move, not CSS transform inside window)
 *  - Smart edge吸附 (stick to nearest edge when released) with screen bounds clamping
 *  - Single-click expand → dialog → choose to open main window or wide sidebar
 *  - Idle semi-transparent (3s without interaction)
 */

(function () {
  'use strict';

  const ball = document.getElementById('ball');
  if (!ball) {
    console.warn('Floating ball DOM not found.');
    return;
  }

  const bridge = window.aerie;
  if (!bridge || !bridge.ball) {
    console.warn('aerie bridge not ready in floating ball');
    return;
  }

  // ---- State ----
  let dragging = false;
  let dragMoved = false;
  let lastX = 0;
  let lastY = 0;
  let originX = 0;     // where ball sits at mousedown (px relative to window)
  let originY = 0;
  let idleTimer = null;
  let clickGuardUntil = 0;

  const DRAG_THRESHOLD = 4; // px before we treat movement as a drag
  const IDLE_AFTER_MS = 3000;
  const IDLE_OPACITY = 0.3;
  const ACTIVE_OPACITY = 1.0;

  // ---- Opacity helpers ----
  function setOpacity(v) {
    ball.style.opacity = String(v);
  }

  function markActive() {
    setOpacity(ACTIVE_OPACITY);
  }

  function goIdle() {
    setOpacity(IDLE_OPACITY);
  }

  function resetIdleTimer() {
    if (idleTimer) clearTimeout(idleTimer);
    idleTimer = setTimeout(goIdle, IDLE_AFTER_MS);
  }

  // ---- Drag (IPC-window level, with bounds clamp on main side) ----
  function onMouseDown(e) {
    e.preventDefault();
    dragging = true;
    dragMoved = false;
    clickGuardUntil = Date.now() + 250;
    lastX = e.screenX;
    lastY = e.screenY;
    markActive();
    ball.classList.add('dragging');
  }

  function onMouseMove(e) {
    if (!dragging) return;
    const dx = e.screenX - lastX;
    const dy = e.screenY - lastY;
    if (Math.abs(dx) + Math.abs(dy) >= DRAG_THRESHOLD) dragMoved = true;
    lastX = e.screenX;
    lastY = e.screenY;
    // Move the entire BrowserWindow via IPC. Main process clamps to screen.
    bridge.ball.move(dx, dy);
  }

  async function onMouseUp() {
    if (!dragging) return;
    dragging = false;
    ball.classList.remove('dragging');
    // Get current bounds + screen size in one call
    const info = await bridge.ball.getBounds();
    if (!info) return;
    const cx = info.x + info.size / 2;
    const cy = info.y + info.size / 2;
    const snapToLeft = cx < info.screenW / 2;
    const snapTop = cy < info.screenH / 2;
    const m = info.margin;
    const s = info.size;
    const finalX = snapToLeft ? m : info.screenW - s - m;
    const finalY = snapTop ? m : info.screenH - s - m;
    // Tell main to set absolute position
    bridge.ball.move(finalX - info.x, finalY - info.y);
    // Then axis-snap for confirmation
    await bridge.ball.snapToEdge('both');
    resetIdleTimer();
  }

  // ---- Click (after drag release) ----
  function onClick() {
    if (Date.now() < clickGuardUntil) return;
    if (dragMoved) return;
    // Toggle the long-bar dialog
    const dlg = document.getElementById('ball-dialog');
    if (!dlg) return;
    dlg.classList.toggle('show');
    resetIdleTimer();
  }

  // ---- Dialog actions ----
  function setupDialog() {
    const dlg = document.getElementById('ball-dialog');
    if (!dlg) return;
    dlg.addEventListener('click', (e) => {
      e.stopPropagation();
      const btn = e.target.closest('[data-action]');
      if (!btn) return;
      const action = btn.dataset.action;
      if (action === 'close') {
        dlg.classList.remove('show');
      } else if (action === 'open-main') {
        dlg.classList.remove('show');
        bridge.ball.showMain(false);
      } else if (action === 'open-wide') {
        dlg.classList.remove('show');
        bridge.ball.showMain(true);
      }
    });
  }

  // ---- Hover / idle ----
  ball.addEventListener('mouseenter', () => { markActive(); });
  ball.addEventListener('mouseleave', () => { resetIdleTimer(); });

  // ---- Wire up ----
  ball.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
  ball.addEventListener('click', onClick);

  // Keyboard accessibility: Space / Enter triggers expand
  ball.setAttribute('tabindex', '0');
  ball.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onClick();
    }
  });

  // Initial position is set by main.js (bottom-right). Start idle watcher.
  setupDialog();
  resetIdleTimer();
})();
