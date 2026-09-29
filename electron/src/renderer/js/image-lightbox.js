/* 图片放大查看（lightbox）。
 *
 * 为什么单独一个文件：它只干"点开聊天里的图看大图"这一件事。chat.js 已经
 * 2300+ 行、管着消息渲染与历史分页，把纯粹的光箱交互塞进去只会让那块更难改。
 *
 * 为什么用事件委托而不是逐个绑 click：消息是动态插入的（历史分页、SSE 推送、
 * 重渲染），逐个绑会在每次重渲染后失效或重复绑定。挂在 document 上一次性解决。
 *
 * 覆盖两类图：
 *   .chat-attach-card__image-wrap img  —— 附件卡片（生成图/上传图）
 *   .chat-bubble img                   —— Markdown 内联图
 */
(function () {
  "use strict";

  var TRIGGER_SELECTOR = ".chat-attach-card__image-wrap img, .chat-bubble img";
  var OPEN_CLASS = "is-open";
  var BODY_LOCK_CLASS = "image-lightbox-open";

  var root = null;
  var imgEl = null;
  var lastFocused = null;

  function elements() {
    if (root) return true;
    root = document.getElementById("image-lightbox");
    if (!root) return false;
    imgEl = root.querySelector(".image-lightbox__img");
    return Boolean(imgEl);
  }

  function prefersReducedMotion() {
    try {
      return Boolean(
        window.matchMedia &&
        window.matchMedia("(prefers-reduced-motion: reduce)").matches,
      );
    } catch (_) {
      return false;
    }
  }

  function open(src, alt) {
    if (!src || !elements()) return;
    lastFocused = document.activeElement;
    imgEl.setAttribute("src", src);
    imgEl.setAttribute("alt", alt || "");
    root.hidden = false;
    // 先去掉 hidden 再加重绘一帧，CSS 过渡才有起点（直接加 class 会瞬现）
    void root.offsetWidth;
    root.classList.add(OPEN_CLASS);
    document.body.classList.add(BODY_LOCK_CLASS);
    var btn = root.querySelector(".image-lightbox__close");
    if (btn && typeof btn.focus === "function") btn.focus();
  }

  function close() {
    if (!elements() || !root.classList.contains(OPEN_CLASS)) return;
    root.classList.remove(OPEN_CLASS);
    document.body.classList.remove(BODY_LOCK_CLASS);

    var finish = function () {
      // 关闭后清空 src：否则下次打开前会短暂显示上一张图
      if (!root.classList.contains(OPEN_CLASS)) {
        imgEl.removeAttribute("src");
        root.hidden = true;
      }
    };
    if (prefersReducedMotion()) finish();
    else window.setTimeout(finish, 160);

    if (lastFocused && typeof lastFocused.focus === "function") {
      try { lastFocused.focus(); } catch (_) { /* 元素可能已被移除 */ }
    }
    lastFocused = null;
  }

  function isOpen() {
    return Boolean(root && root.classList.contains(OPEN_CLASS));
  }

  document.addEventListener("click", function (event) {
    var target = event.target;
    if (!target || target.nodeType !== 1) return;

    // 关闭：点遮罩、点关闭按钮
    if (target.closest("[data-lightbox-close]")) {
      event.preventDefault();
      close();
      return;
    }

    // 打开：点图片（裂图没有 src，不必打开）
    var img = target.closest(TRIGGER_SELECTOR);
    if (!img) return;
    if (img.closest("#image-lightbox")) return; // 点放大后的图本身不重复打开
    var src = img.getAttribute("src");
    if (!src || img.classList.contains("is-broken")) return;
    event.preventDefault();
    open(src, img.getAttribute("alt"));
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && isOpen()) {
      event.preventDefault();
      close();
    }
  });

  // 切到别的页签/最小化时顺手关掉，避免残留一层遮罩
  window.addEventListener("blur", function () {
    if (isOpen()) close();
  });

  window.AerieImageLightbox = { open: open, close: close, isOpen: isOpen };
})();
