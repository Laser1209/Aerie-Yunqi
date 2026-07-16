"use strict";
/* Floating ball: draggable, clickable, shows notification badge */

(function () {
  const ball = document.getElementById("floating-ball");
  const badge = document.getElementById("ball-badge");
  let unread = 0;

  if (!ball) return;

  // Listen for chat messages to update badge
  if (window.aerie && window.aerie.api) {
    window.aerie.api.onMessage((msg) => {
      if (msg.role === "assistant") {
        unread++;
        updateBadge();
      }
    });
  }

  function updateBadge() {
    if (!badge) return;
    if (unread > 0) {
      badge.textContent = unread > 99 ? "99+" : unread;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }
  }

  // Click to open main / chat window
  ball.addEventListener("click", () => {
    if (window.aerie && window.aerie.electron) {
      // Clear badge on click
      unread = 0;
      updateBadge();
    }
  });

  // Drag
  let dragging = false, startX, startY, startLeft, startTop;
  ball.addEventListener("mousedown", (e) => {
    dragging = true;
    startX = e.screenX;
    startY = e.screenY;
    startLeft = ball.offsetLeft;
    startTop = ball.offsetTop;
    ball.style.transition = "none";
  });
  document.addEventListener("mousemove", (e) => {
    if (!dragging) return;
    const dx = e.screenX - startX;
    const dy = e.screenY - startY;
    ball.style.left = (startLeft + dx) + "px";
    ball.style.top = (startTop + dy) + "px";
  });
  document.addEventListener("mouseup", () => {
    if (dragging) {
      dragging = false;
      ball.style.transition = "";
    }
  });
})();
