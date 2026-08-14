"use strict";

// Aerie · 云栖 — 开场动画逻辑
// 流程：全屏视频（不可跳过）→ 满屏 LOGO + 进度条 → 视频播完且后端就绪后通知主进程关闭。
(function () {
  const video = document.getElementById("splash-video");
  const logo = document.getElementById("splash-logo");
  const logoImg = document.getElementById("splash-logo-img");
  const progress = document.getElementById("splash-progress");
  const progressFill = document.getElementById("splash-progress-fill");
  const progressLabel = document.getElementById("splash-progress-label");

  const BOOT_WINDOW_MS = 20000;      // 与主进程 BOOT_TIMEOUT_MS 一致，20s 内推进到 90%
  const OFFLINE_ENTER_DELAY_MS = 2500;

  let videoEnded = false;
  let backendReady = false;
  let backendState = "booting";
  let completed = false;
  let offlineTimer = null;
  const bootStartTs = Date.now();

  function setProgress(pct) {
    const v = Math.max(0, Math.min(100, pct));
    progressFill.style.width = v + "%";
  }

  function setLabel(text) {
    progressLabel.textContent = text;
  }

  function showLogoAndProgress() {
    video.style.display = "none";
    logo.classList.remove("hidden");
    progress.classList.remove("hidden");
  }

  function complete() {
    if (completed) return;
    completed = true;
    if (progressTimer) clearInterval(progressTimer);
    setProgress(100);
    if (window.aerie && window.aerie.electron && window.aerie.electron.splash) {
      try { window.aerie.electron.splash.complete(); } catch (_) {}
    }
  }

  function tryComplete() {
    if (completed || !videoEnded || !backendReady) return;
    setLabel("启动完成");
    complete();
  }

  // offline 时展示错误态并自动「继续进入」，避免卡死在开场动画。
  // 页面无任何可点击元素，因此只能由定时器自动推进进入主窗口。
  function handleOffline() {
    if (completed || !videoEnded) return;
    progressFill.style.background = "linear-gradient(90deg, #ff5f7e, #ffb3d1)";
    setLabel("后端启动超时，即将进入应用…");
    if (offlineTimer) return;
    offlineTimer = setTimeout(complete, OFFLINE_ENTER_DELAY_MS);
  }

  function applyHealth(data) {
    if (!data) return;
    if (data.ready) backendReady = true;
    if (data.state) backendState = data.state;
    if (backendReady) {
      setProgress(100);
      tryComplete();
      return;
    }
    if (backendState === "offline") {
      handleOffline();
    }
  }

  // 不可交互：禁右键、禁拖拽
  document.addEventListener("contextmenu", (event) => event.preventDefault());
  document.addEventListener("dragstart", (event) => event.preventDefault());
  document.addEventListener("drop", (event) => event.preventDefault());

  // booting 阶段进度条 0→90% 平滑推进：min(90, elapsed/20*90)
  const progressTimer = setInterval(() => {
    if (completed || backendReady || backendState === "offline") return;
    const elapsedMs = Date.now() - bootStartTs;
    const pct = Math.min(90, (elapsedMs / BOOT_WINDOW_MS) * 90);
    setProgress(pct);
    // 到达 90% 上限后，后端可能仍在冷启动（首次安装需初始化数据库/组件），
    // 换成更友好的提示，避免用户看到停在 90% 的百分比误以为卡死。
    if (pct >= 90) {
      setLabel("首次启动 · 正在初始化本地环境，可能需要几分钟，请耐心等待…");
    } else {
      setLabel("正在启动 " + Math.round(pct) + "%");
    }
  }, 200);

  function onVideoEnded() {
    if (videoEnded) return;
    videoEnded = true;
    showLogoAndProgress();
    if (backendReady) {
      setProgress(100);
    }
    tryComplete();
    if (backendState === "offline") handleOffline();
  }

  video.addEventListener("ended", onVideoEnded);
  video.addEventListener("error", onVideoEnded);

  // 监听主进程广播的后端健康状态
  if (window.aerie && window.aerie.electron && window.aerie.electron.onHealth) {
    window.aerie.electron.onHealth(applyHealth);
  }

  (async function init() {
    // 先拉一次当前健康状态，防止后端在监听注册前就已就绪
    try {
      if (window.aerie && window.aerie.electron && window.aerie.electron.getHealth) {
        applyHealth(await window.aerie.electron.getHealth());
      }
    } catch (_) {}

    // 读取视频 / LOGO 资产路径并开始播放
    try {
      const cfg = await window.aerie.electron.splash.getConfig();
      logoImg.src = "file:///" + (cfg.logoPath || "");
      if (cfg.playVideo) {
        video.src = "file:///" + (cfg.videoPath || "");
        video.play().catch(onVideoEnded);
      } else {
        // 加载动画模式：跳过视频，直接进入 LOGO + 进度阶段
        onVideoEnded();
      }
    } catch (_) {
      // 资产读取失败：直接进入 LOGO + 进度阶段，避免黑屏卡死
      onVideoEnded();
    }
  })();
})();
