"use strict";

// aerie.admin 管理平台渲染逻辑（P4b, §3.5.2）。
// 双模式：Electron 内嵌（window.admin IPC，token 由 main 注入）；
// 浏览器直连 7890 /admin.html（fetch + sessionStorage token）。
// 只读页面数据走 /api/admin/*，写操作前一律二次确认。

(function () {
  const els = {};
  const CHANNEL_LABELS = { desktop: "桌面", qq: "QQ", mobile: "移动端" };
  const ACTION_LABELS = {
    trash: "移入回收站", restore: "恢复", purge: "清理回收站",
    update_memory: "修改记忆", delete_kb: "删除知识库", reset_state: "重置状态",
  };
  let selectedConv = new Set();

  function $(id) { return document.getElementById(id); }
  const bridge = (typeof window.admin !== "undefined" && window.admin) || null;

  // ── 统一调用层 ─────────────────────────────────────────
  async function call(method, path, body) {
    if (bridge && typeof bridge.api === "function") {
      return bridge.api(method, path, body);
    }
    // 浏览器模式：token 存 sessionStorage，unlock 后携带
    const headers = { "Content-Type": "application/json" };
    const token = sessionStorage.getItem("aerie_admin_token");
    if (token) headers["X-Aerie-Admin-Token"] = token;
    try {
      const res = await fetch(path, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
      });
      let data = {};
      try { data = await res.json(); } catch (_) { data = {}; }
      return { ok: res.ok, status: res.status, data };
    } catch (err) {
      return { ok: false, status: 0, error: String((err && err.message) || err) };
    }
  }

  async function admin(method, path, body) {
    const r = await call(method, path, body);
    if (r.ok === false && r.status === 403) {
      setStatus("locked");
    }
    if (!r.ok && r.status !== 403 && r.error) {
      console.warn("[admin]", method, path, r.error);
    }
    return r;
  }

  // ── 加载进度条（4 阶段：框架→资源→数据→完成） ────────
  let progressTimer = null;
  function setProgress(label, pct) {
    if (!els.progress) return;
    els.progress.hidden = false;
    els.progressLabel.textContent = label;
    els.progressPct.textContent = Math.round(pct) + "%";
    els.progressBar.style.width = Math.max(0, Math.min(100, pct)) + "%";
    if (pct >= 100) {
      clearTimeout(progressTimer);
      setTimeout(() => { els.progress.hidden = true; }, 600);
    }
  }
  function startProgress() {
    clearTimeout(progressTimer);
    let pct = 12;
    setProgress("初始化…", pct);
    progressTimer = setInterval(() => {
      if (pct < 60) { pct += 8; setProgress("加载中…", pct); }
    }, 220);
  }
  function finishProgress() { clearTimeout(progressTimer); setProgress("完成", 100); }

  // ── 状态 ───────────────────────────────────────────────
  function setStatus(state) {
    const key = state ? "unlocked" : "locked";
    els.status.textContent = state ? "已解锁" : "未解锁";
    els.status.className = "adw-status adw-status--" + key;
    els.status.setAttribute("data-status", key);
  }

  function setUnlocked(state) {
    setStatus(state);
    els.unlockBtn.hidden = state;
    els.lockBtn.hidden = !state;
  }

  // ── 模态确认 ───────────────────────────────────────────
  function confirmBox(title, text, onOk) {
    els.modalTitle.textContent = title;
    els.modalText.textContent = text;
    els.modal.hidden = false;
    const done = () => { els.modal.hidden = true; };
    els.modalOk.onclick = () => { done(); onOk(); };
    els.modalCancel.onclick = done;
  }

  // ── 概览 ───────────────────────────────────────────────
  // 浏览器模式：门闩已解锁但本地无 token，或 token 已失效（如后端重启后 token 变化）时，
  // 幂等重新 unlock 取新 token，避免受保护接口 403 → KPI 误显 0。
  async function ensureAdminToken(force) {
    if (bridge) return;
    const status = await admin("GET", "/api/admin/status");
    if (!(status.ok && status.data && status.data.unlocked)) return;
    if (force || !sessionStorage.getItem("aerie_admin_token")) {
      const r = await admin("POST", "/api/admin/unlock", {});
      if (r.ok && r.data && r.data.token) {
        sessionStorage.setItem("aerie_admin_token", r.data.token);
      }
    }
  }

  async function loadOverview() {
    await ensureAdminToken();
    const status = await admin("GET", "/api/admin/status");
    const unlocked = !!(status.ok && status.data && status.data.unlocked);
    setUnlocked(unlocked);

    // 用 overview 端点取真实总量（SQL COUNT），非列表分页截断长度。
    let ov = await admin("GET", "/api/admin/overview");
    if (!ov.ok && ov.status === 403 && !bridge) {
      // token 失效 → 强制重新 unlock 并重试一次
      await ensureAdminToken(true);
      ov = await admin("GET", "/api/admin/overview");
    }
    const k = (ov.ok && ov.data) ? ov.data : {};
    els.overviewKpis.textContent = "";
    els.overviewKpis.appendChild(kpi("会话", fmtInt(k.conversations)));
    els.overviewKpis.appendChild(kpi("消息", fmtInt(k.messages)));
    els.overviewKpis.appendChild(kpi("记忆", fmtInt(k.memory)));
    els.overviewKpis.appendChild(kpi("回收站消息", fmtInt(k.trashed_messages)));
    els.overviewKpis.appendChild(kpi("审计", fmtInt(k.audit)));
    els.overviewKpis.appendChild(kpi("总 tokens", fmtTokens(k.total_tokens)));
  }

  function fmtTokens(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "--";
    if (n >= 1e8) return (n / 1e8).toFixed(2) + "亿";
    if (n >= 1e4) return (n / 1e4).toFixed(1) + "万";
    return String(Math.round(n));
  }

  function kpi(label, value, suffix) {
    const card = document.createElement("div");
    card.className = "adw-kpi";
    const l = document.createElement("span");
    l.className = "adw-kpi-label";
    l.textContent = label;
    const v = document.createElement("span");
    v.className = "adw-kpi-value";
    v.textContent = value;
    if (suffix) {
      const s = document.createElement("small");
      s.textContent = suffix;
      v.appendChild(s);
    }
    card.appendChild(l);
    card.appendChild(v);
    return card;
  }

  function fmtInt(v) {
    const n = Number(v);
    if (!Number.isFinite(n)) return "--";
    return n >= 10000 ? (n / 10000).toFixed(1) + "w" : String(Math.round(n));
  }

  // ── 聊天记录 ───────────────────────────────────────────
  async function loadConversations() {
    const channel = els.convChannel.value;
    const q = channel ? "&channel=" + encodeURIComponent(channel) : "";
    const r = await admin("GET", "/api/admin/conversations?limit=100" + q);
    const items = (r.ok && r.data && r.data.items) || [];
    selectedConv = new Set();
    updateConvSelected();
    els.convList.textContent = "";
    if (!items.length) {
      els.convList.appendChild(empty("暂无会话"));
      return;
    }
    items.forEach((c) => {
      const row = document.createElement("div");
      row.className = "adw-row";
      const check = document.createElement("input");
      check.type = "checkbox";
      check.className = "adw-row-check";
      check.addEventListener("change", () => {
        if (check.checked) selectedConv.add(c.conversation_id);
        else selectedConv.delete(c.conversation_id);
        updateConvSelected();
      });
      const main = document.createElement("span");
      main.className = "adw-row-main";
      const title = document.createElement("span");
      title.className = "adw-row-title";
      // 角色级隔离：会话归属按 persona 标注，不再把塞纳的会话显示成"伊塔"
      const personaTag = c.persona_name
        ? "【" + c.persona_name + "】"
        : (c.persona_id ? "【" + c.persona_id + "】" : "");
      title.textContent = personaTag
        + (CHANNEL_LABELS[c.channel] || c.channel || "--") + " · "
        + String(c.conversation_id).slice(0, 20) + "…";
      const preview = document.createElement("span");
      preview.className = "adw-row-preview";
      preview.textContent = (c.preview && c.preview.content) || "（无内容）";
      main.appendChild(title);
      main.appendChild(preview);
      const meta = document.createElement("span");
      meta.className = "adw-row-meta";
      meta.textContent = "共 " + c.message_count + " 条" + (Number(c.trashed_count) > 0 ? " · 回收站 " + c.trashed_count : "");
      const ops = document.createElement("span");
      ops.className = "adw-row-ops";
      const msgBtn = btn("消息", "adw-btn--small", () => toggleMessages(row, c.conversation_id));
      ops.appendChild(msgBtn);
      row.appendChild(check);
      row.appendChild(main);
      row.appendChild(meta);
      row.appendChild(ops);
      els.convList.appendChild(row);
    });
  }

  // 展开/收起某会话的单条消息列表（惰性加载，每条可编辑/软删/恢复）
  async function toggleMessages(row, conversationId) {
    const existing = row.querySelector(".adw-msg-wrap");
    if (existing) {
      existing.remove();
      return;
    }
    const wrap = document.createElement("div");
    wrap.className = "adw-msg-wrap";
    const loading = document.createElement("p");
    loading.className = "adw-empty";
    loading.textContent = "加载中…";
    wrap.appendChild(loading);
    row.appendChild(wrap);

    const r = await admin("GET", "/api/admin/conversations/" + encodeURIComponent(conversationId) + "/messages?limit=200&include_trashed=true");
    const msgs = (r.ok && r.data && r.data.items) || [];
    wrap.textContent = "";
    if (!msgs.length) {
      wrap.appendChild(empty("该会话暂无消息"));
      return;
    }
    msgs.forEach((m) => {
      const mrow = document.createElement("div");
      mrow.className = "adw-msg-row" + (m.deleted_at ? " adw-msg-row--trashed" : "");
      const head = document.createElement("span");
      head.className = "adw-msg-head";
      // 角色级隔离：assistant 消息按消息归属 persona 显示名字，
      // 不再硬编码"伊塔"（塞纳的消息就标塞纳）
      const aiName = m.persona_name || "AI";
      head.textContent = (m.role === "assistant" ? aiName : "你") + " · " + (m.created_at || "");
      const body = document.createElement("span");
      body.className = "adw-msg-body";
      body.textContent = String(m.content || "");
      const mops = document.createElement("span");
      mops.className = "adw-row-ops";
      if (!m.deleted_at) {
        mops.appendChild(btn("编辑", "adw-btn--small", () => editMessage(m, mrow, conversationId)));
        mops.appendChild(btn("删除", "adw-btn--small adw-btn--danger", () => {
          confirmBox("删除消息", "该消息将进入回收站，可恢复。确认？", async () => {
            await admin("DELETE", "/api/admin/messages/" + encodeURIComponent(m.message_id));
            toggleMessages(row, conversationId);
            toggleMessages(row, conversationId); // 重新展开刷新
          });
        }));
      } else {
        mops.appendChild(btn("恢复", "adw-btn--small", async () => {
          await admin("POST", "/api/admin/messages/" + encodeURIComponent(m.message_id) + "/restore");
          toggleMessages(row, conversationId);
          toggleMessages(row, conversationId);
        }));
      }
      mrow.appendChild(head);
      mrow.appendChild(body);
      mrow.appendChild(mops);
      wrap.appendChild(mrow);
    });
  }

  function editMessage(m, mrow, conversationId) {
    const content = prompt("编辑消息内容：", String(m.content || ""));
    if (content === null || content === String(m.content || "")) return;
    admin("PUT", "/api/admin/messages/" + encodeURIComponent(m.message_id), { content }).then((r) => {
      if (r.ok) {
        m.content = content;
        mrow.querySelector(".adw-msg-body").textContent = content;
        loadOverview();
      }
    });
  }

  function updateConvSelected() {
    els.convSelected.textContent = "已选 " + selectedConv.size + " 项";
    els.convTrash.disabled = selectedConv.size === 0;
    els.convRestore.disabled = selectedConv.size === 0;
  }

  function trashSelected() {
    const ids = Array.from(selectedConv);
    if (!ids.length) return;
    confirmBox(
      "移入回收站",
      "将删除 " + ids.length + " 个会话（含关联消息、摘要与长期记忆），进入回收站后 7 天内可恢复。确认？",
      async () => {
        await admin("POST", "/api/admin/conversations/trash", { conversation_ids: ids });
        loadConversations(); loadOverview();
      },
    );
  }

  function restoreSelected() {
    const ids = Array.from(selectedConv);
    if (!ids.length) return;
    confirmBox("恢复会话", "恢复 " + ids.length + " 个会话及其关联数据。确认？", async () => {
      await admin("POST", "/api/admin/conversations/restore", { conversation_ids: ids });
      loadConversations(); loadOverview();
    });
  }

  // ── 记忆 ───────────────────────────────────────────────
  async function loadMemory() {
    const layer = els.memLayer.value;
    const include = els.memTrashed.checked;
    const r = await admin("GET", "/api/admin/memory?layer=" + encodeURIComponent(layer) + "&limit=500&include_trashed=" + include);
    const items = (r.ok && r.data && r.data.items) || [];
    els.memList.textContent = "";
    if (!items.length) {
      els.memList.appendChild(empty("暂无记忆"));
      return;
    }
    items.forEach((m) => {
      const row = document.createElement("div");
      row.className = "adw-row" + (m.deleted_at ? " adw-row--trashed" : "");
      const main = document.createElement("span");
      main.className = "adw-row-main";
      const title = document.createElement("span");
      title.className = "adw-row-title";
      // 角色级隔离：记忆归属按 persona 标注（共享/无归属不标）
      const memPersona = m.persona_name ? "【" + m.persona_name + "】" : "";
      title.textContent = memPersona + "重要度 " + Number(m.importance) + " · " + String(m.memory_type || "fact");
      const preview = document.createElement("span");
      preview.className = "adw-row-preview";
      preview.textContent = String(m.content || "");
      main.appendChild(title);
      main.appendChild(preview);
      const meta = document.createElement("span");
      meta.className = "adw-row-meta";
      meta.textContent = m.deleted_at ? "回收站" : "正常";
      const ops = document.createElement("span");
      ops.className = "adw-row-ops";
      if (!m.deleted_at) {
        const edit = btn("编辑", "adw-btn--small", () => editMemory(m));
        const del = btn("删除", "adw-btn--small adw-btn--danger", () => {
          confirmBox("删除记忆", "该记忆将进入回收站，可恢复。确认？", async () => {
            await admin("DELETE", "/api/admin/memory/" + encodeURIComponent(m.id));
            loadMemory();
          });
        });
        ops.appendChild(edit);
        ops.appendChild(del);
      } else {
        const res = btn("恢复", "adw-btn--small", async () => {
          await admin("POST", "/api/admin/memory/" + encodeURIComponent(m.id) + "/restore");
          loadMemory();
        });
        ops.appendChild(res);
      }
      row.appendChild(main);
      row.appendChild(meta);
      row.appendChild(ops);
      els.memList.appendChild(row);
    });
  }

  function editMemory(m) {
    const content = prompt("编辑记忆内容：", String(m.content || ""));
    if (content === null) return;
    const importance = prompt("重要度（0-10）：", String(m.importance));
    const changes = { content };
    const n = Number(importance);
    if (Number.isFinite(n)) changes.importance = Math.max(0, Math.min(10, Math.round(n)));
    admin("PUT", "/api/admin/memory/" + encodeURIComponent(m.id), changes).then((r) => {
      if (r.ok) loadMemory();
    });
  }

  // ── 知识库 ─────────────────────────────────────────────
  async function loadKb() {
    const category = els.kbCategory.value;
    const q = category ? "&category=" + encodeURIComponent(category) : "";
    const r = await admin("GET", "/api/admin/kb?limit=500" + q);
    const items = (r.ok && r.data && r.data.items) || [];
    els.kbList.textContent = "";
    if (!items.length) {
      els.kbList.appendChild(empty("暂无知识条目"));
      return;
    }
    items.forEach((k) => {
      const row = document.createElement("div");
      row.className = "adw-row";
      const main = document.createElement("span");
      main.className = "adw-row-main";
      const title = document.createElement("span");
      title.className = "adw-row-title";
      title.textContent = "[" + k.category + "] " + String(k.title || "");
      const preview = document.createElement("span");
      preview.className = "adw-row-preview";
      preview.textContent = String(k.content || "");
      main.appendChild(title);
      main.appendChild(preview);
      const meta = document.createElement("span");
      meta.className = "adw-row-meta";
      meta.textContent = String(k.updated_at || k.created_at || "");
      const ops = document.createElement("span");
      ops.className = "adw-row-ops";
      const del = btn("删除", "adw-btn--small adw-btn--danger", () => {
        confirmBox("删除知识条目", "删除后可在知识库回收操作中立即撤销（undo 快照）。确认？", async () => {
          const rr = await admin("DELETE", "/api/admin/kb/" + k.id);
          if (rr.ok) {
            // 删除后立即提供 undo
            undoKbButton(k.id);
          }
          loadKb();
        });
      });
      ops.appendChild(del);
      row.appendChild(main);
      row.appendChild(meta);
      row.appendChild(ops);
      els.kbList.appendChild(row);
    });
  }

  function undoKbButton(id) {
    const btnEl = btn("撤销删除", "adw-btn--small", async () => {
      await admin("POST", "/api/admin/kb/" + id + "/undo");
      loadKb();
    });
    els.kbList.insertBefore(btnEl, els.kbList.firstChild);
  }

  // ── 回收站 ─────────────────────────────────────────────
  async function loadTrash() {
    const conv = await admin("GET", "/api/admin/conversations?limit=100");
    const mem = await admin("GET", "/api/admin/memory?layer=long_term&limit=500&include_trashed=true");
    const convItems = (conv.ok && conv.data && conv.data.items) || [];
    const memItems = (mem.ok && mem.data && mem.data.items) || [];
    let trashedMsg = 0;
    convItems.forEach((c) => { trashedMsg += Number(c.trashed_count) || 0; });
    const trashedMem = memItems.filter((m) => m.deleted_at).length;
    els.trashSummary.textContent = "";
    els.trashSummary.appendChild(kpi("回收站消息", String(trashedMsg)));
    els.trashSummary.appendChild(kpi("回收站记忆", String(trashedMem)));
    els.trashList.textContent = "";
    const trashedConvs = convItems.filter((c) => Number(c.trashed_count) > 0);
    if (!trashedConvs.length && !trashedMem) {
      els.trashList.appendChild(empty("回收站为空"));
      return;
    }
    trashedConvs.forEach((c) => {
      const row = document.createElement("div");
      row.className = "adw-row adw-row--trashed";
      const main = document.createElement("span");
      main.className = "adw-row-main";
      const title = document.createElement("span");
      title.className = "adw-row-title";
      title.textContent = "会话 · " + (CHANNEL_LABELS[c.channel] || c.channel || "--");
      main.appendChild(title);
      const meta = document.createElement("span");
      meta.className = "adw-row-meta";
      meta.textContent = c.trashed_count + " 条消息在回收站";
      const ops = document.createElement("span");
      ops.className = "adw-row-ops";
      ops.appendChild(btn("恢复", "adw-btn--small", async () => {
        await admin("POST", "/api/admin/conversations/restore", { conversation_ids: [c.conversation_id] });
        loadTrash(); loadOverview();
      }));
      row.appendChild(main);
      row.appendChild(meta);
      row.appendChild(ops);
      els.trashList.appendChild(row);
    });
  }

  // ── 审计 ───────────────────────────────────────────────
  async function loadAudit() {
    const r = await admin("GET", "/api/admin/audit?limit=50");
    const items = (r.ok && r.data && r.data.items) || [];
    els.auditList.textContent = "";
    if (!items.length) {
      els.auditList.appendChild(empty("暂无审计记录"));
      return;
    }
    items.forEach((a) => {
      const row = document.createElement("div");
      row.className = "adw-row";
      const main = document.createElement("span");
      main.className = "adw-row-main";
      const title = document.createElement("span");
      title.className = "adw-row-title";
      title.textContent = ACTION_LABELS[a.action] || a.action;
      const preview = document.createElement("span");
      preview.className = "adw-row-preview";
      preview.textContent = "目标 " + String(a.target_id || "--") + " · " + a.reason_code;
      main.appendChild(title);
      main.appendChild(preview);
      const meta = document.createElement("span");
      meta.className = "adw-row-meta";
      meta.textContent = formatTs(a.timestamp);
      row.appendChild(main);
      row.appendChild(meta);
      els.auditList.appendChild(row);
    });
  }

  // ── 状态文件（只读查看） ───────────────────────────────
  async function loadState() {
    const r = await admin("GET", "/api/admin/state");
    const items = (r.ok && r.data && r.data.items) || [];
    els.stateList.textContent = "";
    if (!items.length) {
      els.stateList.appendChild(empty("暂无状态文件"));
      return;
    }
    items.forEach((s) => {
      const row = document.createElement("div");
      row.className = "adw-row" + (s.exists ? "" : " adw-row--trashed");
      const main = document.createElement("span");
      main.className = "adw-row-main";
      const title = document.createElement("span");
      title.className = "adw-row-title";
      title.textContent = String(s.kind);
      const preview = document.createElement("span");
      preview.className = "adw-row-preview";
      preview.textContent = s.exists ? "大小 " + s.size + " B · 更新于 " + formatTs(s.modified_at) : "文件不存在";
      main.appendChild(title);
      main.appendChild(preview);
      const ops = document.createElement("span");
      ops.className = "adw-row-ops";
      if (s.exists) {
        ops.appendChild(btn("查看", "adw-btn--small", async () => {
          const rr = await admin("GET", "/api/admin/state/" + encodeURIComponent(s.kind));
          if (rr.ok && rr.data && rr.data.exists) {
            els.stateContent.textContent = JSON.stringify(rr.data.content, null, 2);
            els.stateContent.hidden = false;
          }
        }));
      }
      row.appendChild(main);
      row.appendChild(ops);
      els.stateList.appendChild(row);
    });
  }

  // ── 工具 ───────────────────────────────────────────────
  function btn(text, cls, onClick) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "adw-btn " + (cls || "");
    b.textContent = text;
    b.addEventListener("click", onClick);
    return b;
  }
  function empty(text) {
    const p = document.createElement("p");
    p.className = "adw-empty";
    p.textContent = text;
    return p;
  }
  function formatTs(v) {
    if (!v) return "--";
    try {
      const d = new Date(v);
      if (Number.isNaN(d.getTime())) return String(v);
      const p = (n) => String(n).padStart(2, "0");
      return p(d.getMonth() + 1) + "-" + p(d.getDate()) + " " + p(d.getHours()) + ":" + p(d.getMinutes());
    } catch (_) { return String(v); }
  }

  function switchPage(page) {
    document.querySelectorAll(".adw-nav-btn").forEach((b) => {
      b.classList.toggle("is-active", b.getAttribute("data-page") === page);
    });
    document.querySelectorAll(".adw-page").forEach((p) => {
      p.hidden = p.getAttribute("data-page-panel") !== page;
    });
    const loaders = {
      overview: loadOverview,
      conversations: loadConversations,
      memory: loadMemory,
      kb: loadKb,
      state: loadState,
      trash: loadTrash,
      audit: loadAudit,
    };
    if (loaders[page]) requestAnimationFrame(() => loaders[page]());
  }

  async function unlockAdmin() {
    const r = await admin("POST", "/api/admin/unlock", {});
    if (r.ok) {
      if (!bridge) sessionStorage.setItem("aerie_admin_token", (r.data && r.data.token) || "");
      setUnlocked(true);
      loadOverview();
    } else {
      alert("解锁失败：" + (r.error || "未知错误"));
    }
  }

  async function lockAdmin() {
    await admin("POST", "/api/admin/lock", {});
    if (!bridge) sessionStorage.removeItem("aerie_admin_token");
    setUnlocked(false);
  }

  async function purgeExpired() {
    const r = await admin("POST", "/api/admin/trash/purge", { all: false });
    if (r.ok) {
      alert("已清理过期回收站：" + JSON.stringify(r.data));
      loadTrash(); loadOverview();
    }
  }

  function purgeAll() {
    confirmBox(
      "立即清空回收站",
      "将物理删除回收站中全部数据（含向量），不可恢复。请确认。",
      async () => {
        const r = await admin("POST", "/api/admin/trash/purge", { all: true });
        if (r.ok) {
          alert("已清空回收站：" + JSON.stringify(r.data));
          loadTrash(); loadOverview();
        }
      },
    );
  }

  function init() {
    els.status = $("adw-status");
    els.progress = $("adw-progress");
    els.progressLabel = $("adw-progress-label");
    els.progressPct = $("adw-progress-pct");
    els.progressBar = $("adw-progress-bar");
    els.overviewKpis = $("adw-overview-kpis");
    els.unlockBtn = $("adw-unlock-btn");
    els.lockBtn = $("adw-lock-btn");
    els.convChannel = $("adw-conv-channel");
    els.convList = $("adw-conv-list");
    els.convTrash = $("adw-conv-trash");
    els.convRestore = $("adw-conv-restore");
    els.convSelected = $("adw-conv-selected");
    els.memLayer = $("adw-mem-layer");
    els.memTrashed = $("adw-mem-trashed");
    els.memList = $("adw-mem-list");
    els.kbCategory = $("adw-kb-category");
    els.kbList = $("adw-kb-list");
    els.stateList = $("adw-state-list");
    els.stateContent = $("adw-state-content");
    els.trashSummary = $("adw-trash-summary");
    els.trashList = $("adw-trash-list");
    els.auditList = $("adw-audit-list");
    els.modal = $("adw-modal");
    els.modalTitle = $("adw-modal-title");
    els.modalText = $("adw-modal-text");
    els.modalOk = $("adw-modal-ok");
    els.modalCancel = $("adw-modal-cancel");

    document.querySelectorAll(".adw-nav-btn").forEach((b) => {
      b.addEventListener("click", () => switchPage(b.getAttribute("data-page")));
    });
    els.unlockBtn.addEventListener("click", unlockAdmin);
    els.lockBtn.addEventListener("click", lockAdmin);
    els.convChannel.addEventListener("change", loadConversations);
    els.convTrash.addEventListener("click", trashSelected);
    els.convRestore.addEventListener("click", restoreSelected);
    els.memLayer.addEventListener("change", loadMemory);
    els.memTrashed.addEventListener("change", loadMemory);
    els.kbCategory.addEventListener("change", loadKb);
    $("adw-refresh-all").addEventListener("click", refreshAll);
    $("adw-conv-refresh").addEventListener("click", loadConversations);
    $("adw-mem-refresh").addEventListener("click", loadMemory);
    $("adw-kb-refresh").addEventListener("click", loadKb);
    $("adw-audit-refresh").addEventListener("click", loadAudit);
    $("adw-purge-expired").addEventListener("click", purgeExpired);
    $("adw-purge-all").addEventListener("click", purgeAll);
    $("adw-min").addEventListener("click", () => { if (bridge && bridge.minimize) bridge.minimize(); });
    $("adw-close").addEventListener("click", () => { if (bridge && bridge.close) bridge.close(); });

    refreshAll();
  }

  function refreshAll() {
    startProgress();
    const jobs = [loadOverview(), loadConversations(), loadMemory(), loadKb(), loadState(), loadTrash(), loadAudit()];
    Promise.allSettled(jobs).then(finishProgress);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
