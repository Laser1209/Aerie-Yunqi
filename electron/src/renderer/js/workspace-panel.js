/* Aerie · 云栖 — v0.4.1 工作区侧边栏面板。
 *
 * 折叠式侧边栏:工具栏"工作区"按钮展开/收起。
 * 三个视图:
 *   files  — 文件树(懒加载,目录点击展开)
 *   images — 图片缩略图网格(当前目录下图片)
 *   log    — DSH 操作日志时间线(轮询刷新)
 * 所有路径操作走后端 /api/workspace/*(渲染层无 nodeIntegration)。
 */
(function () {
  "use strict";

  const API = "http://127.0.0.1:7890";

  const state = {
    root: "",            // 当前根目录
    openDirs: new Set(), // 已展开的目录路径
    pollTimer: null,
    rootsInfo: [],       // [{path, source}] 来源标记(自定义目录可删)
    permMode: "",        // 写操作权限模式(与电脑操控共用): manual/auto/full/custom
  };

  function request(opts) {
    if (window.aerie) {
      try {
        return window.aerie.api.request(opts);
      } catch (_) {}
    }
    const init = {
      method: opts.method || "GET",
      headers: { "Content-Type": "application/json" },
    };
    if (opts.body) init.body = JSON.stringify(opts.body);
    return fetch(API + opts.path, init).then(async (r) => {
      if (opts.binary) return r;
      const text = await r.text();
      let data;
      try { data = JSON.parse(text); } catch (_) { data = { raw: text }; }
      return { status: r.status, data };
    });
  }

  const $ = (id) => document.getElementById(id);

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  /* ── 打开/收起侧边栏 ───────────────────────────── */
  function open() {
    const sidebar = $("workspace-sidebar");
    if (!sidebar) return;
    sidebar.hidden = false;
    const btn = $("chat-workspace-btn");
    if (btn) btn.setAttribute("aria-pressed", "true");
    loadRoots();
    loadPermission();
    startPolling();
  }

  function close() {
    const sidebar = $("workspace-sidebar");
    if (sidebar) sidebar.hidden = true;
    const btn = $("chat-workspace-btn");
    if (btn) btn.setAttribute("aria-pressed", "false");
    stopPolling();
  }

  function toggle() {
    const sidebar = $("workspace-sidebar");
    if (sidebar && sidebar.hidden) open();
    else close();
  }

  /* ── 写操作权限(与电脑操控共用同一套状态) ─────── */
  const _PERM_LABELS = {
    manual: "手动审批",
    auto: "自动批阅",
    full: "完全访问",
    custom: "自定义",
  };

  async function loadPermission() {
    const box = $("workspace-perm-levels");
    if (!box) return;
    try {
      const res = await request({ path: "/api/workspace/permission" });
      const mode = (res.data && res.data.mode) || "manual";
      renderPermission(mode);
    } catch (_) {
      renderPermission(state.permMode || "manual");
    }
  }

  function renderPermission(mode) {
    state.permMode = mode;
    const box = $("workspace-perm-levels");
    if (box) {
      box.querySelectorAll(".ws-perm-level").forEach((el) => {
        const active = el.getAttribute("data-level") === mode;
        el.classList.toggle("active", active);
        el.setAttribute("aria-checked", String(active));
      });
    }
    const cur = $("workspace-perm-current");
    if (cur) cur.textContent = _PERM_LABELS[mode] || mode;
  }

  async function setPermissionMode(mode) {
    if (!mode || mode === state.permMode) return;
    renderPermission(mode); // 先即时更新选中态,再异步同步后端
    try {
      const res = await request({
        method: "PUT",
        path: "/api/computer_control/mode",
        body: { mode },
      });
      if (res.data && res.data.mode) renderPermission(res.data.mode);
    } catch (_) {}
  }

  /* ── 根目录下拉 ───────────────────────────────── */
  async function loadRoots() {
    const select = $("workspace-root-select");
    if (!select) return;
    let roots = [];
    let rootsInfo = [];
    let activeRoot = "";
    try {
      const res = await request({ path: "/api/workspace/roots" });
      roots = (res.data && res.data.roots) || [];
      rootsInfo = (res.data && res.data.roots_info) || [];
      activeRoot = (res.data && res.data.active_root) || "";
    } catch (e) {
      renderTreeError("无法连接后端");
      return;
    }
    state.rootsInfo = rootsInfo;
    // 优先恢复后端记录的激活工作区(跨重启保留)
    const current = activeRoot || state.root || roots[0] || "";
    select.innerHTML = "";
    roots.forEach((r) => {
      const opt = document.createElement("option");
      opt.value = r;
      opt.textContent = r;
      select.appendChild(opt);
    });
    if (roots.length === 0) {
      renderTreeError("暂无工作区目录");
      return;
    }
    select.value = current;
    state.root = current;
    updateRemoveButton();
    refreshAll();
  }

  async function setActiveRoot(path) {
    if (!path) return;
    try {
      const res = await request({
        path: "/api/workspace/active",
        method: "POST",
        body: { path },
      });
      const active = res.data && res.data.active_root;
      if (active) state.root = active;
    } catch (_) {}
  }

  function updateRemoveButton() {
    const btn = $("workspace-root-remove");
    if (!btn) return;
    const info = (state.rootsInfo || []).find((r) => r.path === state.root);
    const removable = info && info.source === "custom";
    btn.disabled = !removable;
    btn.title = removable ? "移除该自定义目录" : "预设目录不可移除";
  }

  async function addCustomRoot() {
    let path = "";
    const input = $("workspace-root-input");
    // 优先弹系统文件夹选择框;Electron 环境(preload 注入 dialog)可用。
    // 非 Electron(纯浏览器调试)退回输入框内容。
    try {
      if (window.aerie && window.aerie.electron && window.aerie.electron.dialog
          && window.aerie.electron.dialog.openDirectory) {
        const picked = await window.aerie.electron.dialog.openDirectory({
          title: "选择工作区文件夹",
        });
        if (!picked) return; // 用户取消
        path = picked;
      } else if (input && input.value.trim()) {
        path = input.value.trim();
      }
    } catch (_) {
      if (input && input.value.trim()) path = input.value.trim();
    }
    if (!path) return;

    try {
      const res = await request({
        path: "/api/workspace/roots/temp",
        method: "POST",
        body: { path },
      });
      const added = res.data && res.data.added;
      state.rootsInfo = (res.data && res.data.roots_info) || [];
      if (input) input.value = "";
      if (!added) {
        if (input) input.placeholder = "该目录已存在，换个路径试试";
        return;
      }
      if (!state.root) state.root = path;
      await loadRoots();
      state.root = path; // 选中刚添加的目录
      const select = $("workspace-root-select");
      if (select) select.value = path;
      setActiveRoot(path); // 新添加的目录立即激活,让 Agent 感知
      updateRemoveButton();
      refreshAll();
    } catch (_) {}
  }

  async function removeCustomRoot() {
    if (!state.root) return;
    const info = (state.rootsInfo || []).find((r) => r.path === state.root);
    if (!info || info.source !== "custom") return;
    try {
      const res = await request({
        path: "/api/workspace/roots/remove",
        method: "POST",
        body: { path: state.root },
      });
      state.rootsInfo = (res.data && res.data.roots_info) || [];
      state.openDirs.clear();
      await loadRoots();
    } catch (_) {}
  }

  /* ── 文件树 ───────────────────────────────────── */
  async function loadTree(path) {
    const res = await request({
      path: "/api/workspace/tree?path=" + encodeURIComponent(path),
    });
    if (res.status !== 200) throw new Error((res.data && res.data.error) || "tree failed");
    return res.data;
  }

  function renderTreeError(msg) {
    const el = $("workspace-tree");
    if (el) el.innerHTML = `<div class="workspace-tree-empty">${esc(msg)}</div>`;
  }

  async function refreshTree() {
    const el = $("workspace-tree");
    if (!el) return;
    if (!state.root) { renderTreeError("暂无工作区目录"); return; }
    try {
      const tree = await loadTree(state.root);
      const items = tree.entries || [];
      const dirs = items.filter((e) => e.is_dir);
      const files = items.filter((e) => !e.is_dir);
      const ordered = [...dirs, ...files];
      if (ordered.length === 0) {
        el.innerHTML = `<div class="workspace-tree-empty">(空目录)</div>`;
        return;
      }
      el.innerHTML = ordered.map((e) =>
        e.is_dir
          ? renderDir(state.root, e)
          : renderFile(state.root, e)
      ).join("");
      bindTreeEvents(el);
    } catch (e) {
      renderTreeError(e.message);
    }
  }

  function renderDir(parentPath, e) {
    const full = joinPath(parentPath, e.name);
    const open = state.openDirs.has(full);
    return `<div class="ws-tree-dir ${open ? "open" : ""}" data-path="${esc(full)}">
      <span class="ws-tree-dir__arrow">▶</span>
      <span class="ws-tree-dir__icon">📁</span>
      <span class="ws-tree-dir__name">${esc(e.name)}</span>
    </div>
    <div class="ws-tree-children" ${open ? "" : "hidden"} data-path="${esc(full)}">
      <div class="workspace-tree-loading">加载中…</div>
    </div>`;
  }

  function renderFile(parentPath, e) {
    const full = joinPath(parentPath, e.name);
    const icon = e.is_image ? "🖼️" : "📄";
    return `<div class="ws-tree-file" data-path="${esc(full)}" data-open="1">
      <span class="ws-tree-file__icon">${icon}</span>
      <span class="ws-tree-file__name">${esc(e.name)}</span>
      <span class="ws-tree-file__size">${e.is_image ? "" : esc(e.size_human || "")}</span>
    </div>`;
  }

  function joinPath(parent, name) {
    if (!parent) return name;
    return parent.replace(/[\\/]+$/, "") + "\\" + name;
  }

  function bindTreeEvents(rootEl) {
    rootEl.querySelectorAll(".ws-tree-dir").forEach((dirEl) => {
      dirEl.addEventListener("click", async () => {
        const path = dirEl.getAttribute("data-path");
        const childrenEl = rootEl.querySelector(`.ws-tree-children[data-path="${CSS.escape(path)}"]`);
        if (state.openDirs.has(path)) {
          state.openDirs.delete(path);
          dirEl.classList.remove("open");
          if (childrenEl) childrenEl.hidden = true;
          return;
        }
        state.openDirs.add(path);
        dirEl.classList.add("open");
        if (childrenEl) {
          childrenEl.hidden = false;
          try {
            const tree = await loadTree(path);
            const dirs = (tree.entries || []).filter((e) => e.is_dir);
            const files = (tree.entries || []).filter((e) => !e.is_dir);
            const ordered = [...dirs, ...files];
            if (ordered.length === 0) {
              childrenEl.innerHTML = `<div class="workspace-tree-empty">(空)</div>`;
            } else {
              childrenEl.innerHTML = ordered.map((e) =>
                e.is_dir ? renderDir(path, e) : renderFile(path, e)
              ).join("");
              bindTreeEvents(childrenEl);
            }
          } catch (e) {
            childrenEl.innerHTML = `<div class="workspace-tree-empty">${esc(e.message)}</div>`;
          }
        }
      });
    });
    rootEl.querySelectorAll(".ws-tree-file").forEach((fileEl) => {
      fileEl.addEventListener("click", () => openPath(fileEl.getAttribute("data-path")));
    });
  }

  /* ── 图片缩略图 ───────────────────────────────── */
  async function refreshImages() {
    const el = $("workspace-images");
    if (!el) return;
    if (!state.root) { el.innerHTML = `<div class="ws-img-empty">暂无工作区目录</div>`; return; }
    try {
      const tree = await loadTree(state.root);
      const imgs = (tree.entries || []).filter((e) => !e.is_dir && e.is_image);
      if (imgs.length === 0) {
        el.innerHTML = `<div class="ws-img-empty">当前目录没有图片</div>`;
        return;
      }
      el.innerHTML = imgs.map((e) => {
        const full = joinPath(state.root, e.name);
        const thumb = API + "/api/workspace/thumbnail?path=" + encodeURIComponent(full);
        return `<div class="ws-img" data-path="${esc(full)}" title="${esc(e.name)}">
          <img src="${thumb}" alt="${esc(e.name)}" loading="lazy">
          <div class="ws-img__name">${esc(e.name)}</div>
        </div>`;
      }).join("");
      el.querySelectorAll(".ws-img").forEach((imgEl) => {
        imgEl.addEventListener("click", () => openPath(imgEl.getAttribute("data-path")));
      });
    } catch (e) {
      el.innerHTML = `<div class="ws-img-empty">${esc(e.message)}</div>`;
    }
  }

  /* ── 操作日志 ─────────────────────────────────── */
  async function refreshLog() {
    const el = $("workspace-log");
    if (!el) return;
    try {
      const res = await request({ path: "/api/workspace/activities" });
      const acts = (res.data && res.data.activities) || [];
      if (acts.length === 0) {
        el.innerHTML = `<div class="ws-log-empty">暂无操作记录</div>`;
        return;
      }
      el.innerHTML = acts.map((a) => {
        const t = fmtTime(a.ts);
        const cls = a.kind === "execute" ? "ws-log-item--execute"
          : a.kind === "error" ? "ws-log-item--error"
          : a.kind === "open" ? "ws-log-item--open"
          : "";
        return `<div class="ws-log-item ${cls}">
          <span class="ws-log-item__time">${t}</span>
          <span class="ws-log-item__detail">${esc(a.detail || "")}</span>
        </div>`;
      }).join("");
    } catch (_) {
      el.innerHTML = `<div class="ws-log-empty">无法加载日志</div>`;
    }
  }

  function fmtTime(ts) {
    if (!ts) return "";
    const d = new Date(ts * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function refreshAll() {
    refreshTree();
    refreshImages();
    refreshLog();
  }

  /* ── 打开文件/文件夹 ─────────────────────────── */
  async function openPath(path) {
    if (!path) return;
    try {
      await request({
        path: "/api/workspace/open",
        method: "POST",
        body: { path },
      });
      refreshLog();
    } catch (_) {}
  }

  /* ── 日志轮询(侧边栏可见时每 4s) ─────────────── */
  function startPolling() {
    stopPolling();
    state.pollTimer = setInterval(() => {
      refreshLog();
      loadPermission(); // 与大脑面板轮询同步,保证权限模式状态始终一致
    }, 4000);
  }

  function stopPolling() {
    if (state.pollTimer) {
      clearInterval(state.pollTimer);
      state.pollTimer = null;
    }
  }

  /* ── 视图切换 ────────────────────────────────── */
  function bindTabs() {
    document.querySelectorAll(".workspace-tab").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".workspace-tab").forEach((b) => b.classList.remove("active"));
        document.querySelectorAll(".workspace-view").forEach((v) => v.classList.remove("active"));
        btn.classList.add("active");
        const view = btn.getAttribute("data-wtab");
        const el = document.querySelector(`.workspace-view[data-wview="${view}"]`);
        if (el) el.classList.add("active");
      });
    });
  }

  /* ── 初始化 ──────────────────────────────────── */
  function init() {
    const btn = $("chat-workspace-btn");
    if (!btn) return;
    btn.addEventListener("click", toggle);
    const closeBtn = $("workspace-sidebar-close");
    if (closeBtn) closeBtn.addEventListener("click", close);
    const addBtn = $("workspace-root-add-btn");
    if (addBtn) addBtn.addEventListener("click", addCustomRoot);
    const addInput = $("workspace-root-input");
    if (addInput) addInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") addCustomRoot();
    });
    const removeBtn = $("workspace-root-remove");
    if (removeBtn) removeBtn.addEventListener("click", removeCustomRoot);
    const select = $("workspace-root-select");
    if (select) select.addEventListener("change", () => {
      state.root = select.value;
      state.openDirs.clear();
      setActiveRoot(select.value); // 通知后端,让 Agent 感知当前工作区
      updateRemoveButton();
      refreshAll();
    });
    const permBox = $("workspace-perm-levels");
    if (permBox) {
      permBox.querySelectorAll(".ws-perm-level").forEach((el) => {
        el.addEventListener("click", () => setPermissionMode(el.getAttribute("data-level")));
      });
    }
    bindTabs();
    loadPermission(); // 初始化拉取当前权限模式(与电脑操控共用状态)
  }

  document.addEventListener("DOMContentLoaded", init);

  window.WorkspacePanel = {
    open,
    close,
    toggle,
    refresh: refreshAll,
  };
})();
