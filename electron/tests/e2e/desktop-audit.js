"use strict";

const crypto = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const { _electron: electron } = require("playwright-core");

const electronRoot = path.resolve(__dirname, "..", "..");
const projectRoot = path.resolve(electronRoot, "..");
const evidenceRoot = path.resolve(
  process.env.AERIE_QA_EVIDENCE_DIR
    || path.join(projectRoot, ".codex-temp", "desktop-audit"),
);
const runtimeRoot = path.join(evidenceRoot, "runtime");
const phaseRoot = path.join(evidenceRoot, "phases");
const backendPort = String(process.env.AERIE_TEST_BACKEND_PORT || "7896");
const pythonExe = process.env.AERIE_TEST_PYTHON
  || path.join(projectRoot, ".venv", "Scripts", "python.exe");
const electronExe = path.join(electronRoot, "node_modules", "electron", "dist", "electron.exe");
const AUDIT_SCHEMA_VERSION = 2;
const REQUIRED_STATES = ["loading", "empty", "success", "error", "stale", "disabled", "filled"];
const RUNTIME_FLOW_SELECTORS = new Set([
  "#btn-minimize",
  "#btn-maximize",
  "#chat-brief-btn",
  "#chat-office-btn",
  "#cal-add-btn",
  "#knowledge-add-btn",
  "#persona-hub-create-btn",
]);
const SECRET_SELECTOR = [
  'input[type="password"]',
  '[id*="api-key" i]',
  '[id*="apikey" i] input',
  '[id*="token" i]',
  '[id*="secret" i]',
  '#yaml-editor',
  '[data-sensitive="true"]',
].join(",");

const DEDICATED_RULES = [
  {
    pattern: /#btn-close\b|\bwindow[-_ ]?close\b/i,
    category: "window-close",
    reason: "Closing the application would terminate the audit before evidence is finalized.",
  },
  {
    pattern: /settings-restart-app|restart entire app|重启整个应用|重启应用/i,
    category: "application-restart",
    reason: "Application restart is owned by a separate isolated lifecycle test.",
  },
  {
    pattern: /settings-restart-btn|stale-banner-restart|restart python|restart backend|重启后端/i,
    category: "backend-restart",
    reason: "Backend restart would invalidate the current network and DOM evidence window.",
  },
  {
    pattern: /napcat-|status-qq|\bqq\b|二维码|扫码/i,
    category: "qq-connectivity",
    reason: "QQ is disabled for the generic UI audit; connection-only verification has its own redacted stage.",
  },
  {
    pattern: /chat-send|btn-send|发送消息|\bsend\b/i,
    category: "model-message",
    reason: "The generic UI audit must not consume a real-model call or send user content.",
  },
  {
    pattern: /chat-mic|voice|语音|microphone/i,
    category: "microphone",
    reason: "The audit does not capture host microphone input.",
  },
  {
    pattern: /media-(?:play|pause|next|prev)|播放|下一首|上一首/i,
    category: "host-media",
    reason: "Host media controls are not changed by an isolated application audit.",
  },
  {
    pattern: /chat-attach-btn|chat-file-input/i,
    category: "attachment-picker",
    reason: "The native picker is replaced by the synthetic in-memory attachment fixture flow.",
  },
  {
    pattern: /avatar-upload|editor-upload|import-btn|office-dir-(?:browse|open)|openDirectory|\bimport\b|\bupload\b|导入|上传|更换头像|打开当前文件夹|选择文件夹/i,
    category: "native-file-dialog",
    reason: "Native file and directory dialogs are not opened during unattended QA.",
  },
  {
    pattern: /settings-(?:save|reset|reload)|yaml-(?:save|backup)|office-dir-(?:save|reset)|provider.*save|(?:persona|user)-save|di-settings-(?:apply|reset)|cal-save|knowledge-save|\bsave\b|\bapply\b|保存|应用到|恢复默认|热重载|备份当前/i,
    category: "persistent-configuration",
    reason: "Persistent host configuration is preserved; the control is covered by its dedicated configuration tests.",
  },
  {
    pattern: /test.*(?:provider|connection|api)|(?:provider|connection|api).*test|测试连接|连通性测试/i,
    category: "external-provider-test",
    reason: "Provider connectivity is outside the zero-model-call generic UI audit.",
  },
  {
    pattern: /world-dashboard-(?:enable|disable|start|stop|pause|resume|restart)|world-candidate-approve/i,
    category: "world-lifecycle",
    reason: "World lifecycle mutations are verified by the isolated supervisor lifecycle suite.",
  },
  {
    pattern: /delete|remove|clear|reset|approve|reject|执行|允许|删除|清空|移除|撤回|恢复出厂/i,
    category: "destructive-or-persistent",
    reason: "Potentially destructive controls require a purpose-built synthetic-data flow.",
  },
  {
    pattern: /download|export|导出|下载/i,
    category: "host-download",
    reason: "The audit does not write downloads outside its evidence directory.",
  },
];

function mkdir(target) {
  fs.mkdirSync(target, { recursive: true });
}

function nowIso() {
  return new Date().toISOString();
}

function safeName(value) {
  return String(value || "unknown")
    .normalize("NFKC")
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 96) || "unknown";
}

function sha256(value) {
  return crypto.createHash("sha256").update(String(value || ""), "utf8").digest("hex");
}

function redactText(value) {
  return String(value == null ? "" : value)
    .replace(/C:\\Users\\[^\\\s]+\\/gi, "C:\\Users\\<redacted>\\")
    .replace(/\b(?:sk|gho|ghp|github_pat)_[A-Za-z0-9_-]{8,}\b/g, "<redacted-token>")
    .replace(/\bBearer\s+[A-Za-z0-9._~+\/-]{8,}\b/gi, "Bearer <redacted>")
    .replace(/\b(API[_ -]?KEY|TOKEN|SECRET|PASSWORD)\s*[:=]\s*[^\s,;]+/gi, "$1=<redacted>")
    .replace(/\b(qq|self[_ -]?qq)\s*[:=]\s*\d{5,12}\b/gi, "$1=<redacted>");
}

function redactValue(value, depth = 0, key = "") {
  if (depth > 12) return "<max-depth>";
  if (/key|token|secret|password|authorization|cookie/i.test(String(key))) {
    return "<redacted>";
  }
  if (typeof value === "string") return redactText(value);
  if (Array.isArray(value)) return value.map((item) => redactValue(item, depth + 1));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([childKey, childValue]) => [
      childKey,
      redactValue(childValue, depth + 1, childKey),
    ]));
  }
  return value;
}

function writeJson(target, value) {
  mkdir(path.dirname(target));
  fs.writeFileSync(
    target,
    JSON.stringify(redactValue(value), null, 2) + "\n",
    "utf8",
  );
}

function appendProgress(value) {
  mkdir(evidenceRoot);
  fs.appendFileSync(
    path.join(evidenceRoot, "progress.jsonl"),
    JSON.stringify(redactValue({ ...value, at: nowIso() })) + "\n",
    "utf8",
  );
}

function sanitizeUrl(rawUrl) {
  try {
    const parsed = new URL(String(rawUrl));
    parsed.hash = "";
    for (const [key, value] of parsed.searchParams.entries()) {
      if (/key|token|secret|password|authorization|qq|user/i.test(key)) {
        parsed.searchParams.set(key, "<redacted>");
      } else if (value.length > 160) {
        parsed.searchParams.set(key, `${value.slice(0, 80)}...<truncated>`);
      }
    }
    return redactText(parsed.toString());
  } catch (_) {
    return redactText(rawUrl);
  }
}

function describeControlForPolicy(control) {
  return [
    control && control.locator && control.locator.selector,
    control && control.id,
    control && control.accessibleName,
    control && control.text,
    control && control.title,
    control && control.name,
  ].filter(Boolean).join(" ");
}

function classifyDedicatedControl(control) {
  if (control && control.sensitive) {
    return {
      category: "sensitive-field",
      reason: "Sensitive fields are presence-tested without reading or changing their value.",
    };
  }
  const description = describeControlForPolicy(control);
  return DEDICATED_RULES.find((rule) => rule.pattern.test(description)) || null;
}

function isAllowedSafeSkip(control, classification) {
  if (!classification) return false;
  if (control && control.locator && control.locator.selector === "#btn-minimize") return false;
  if (control && control.locator && control.locator.selector === "#btn-maximize") return false;
  return true;
}

function installAuditHooks() {
  const listenerCounts = new WeakMap();
  const originalAdd = EventTarget.prototype.addEventListener;
  const originalRemove = EventTarget.prototype.removeEventListener;
  EventTarget.prototype.addEventListener = function auditAdd(type, listener, options) {
    let byType = listenerCounts.get(this);
    if (!byType) {
      byType = new Map();
      listenerCounts.set(this, byType);
    }
    byType.set(String(type), (byType.get(String(type)) || 0) + 1);
    return originalAdd.call(this, type, listener, options);
  };
  EventTarget.prototype.removeEventListener = function auditRemove(type, listener, options) {
    const byType = listenerCounts.get(this);
    if (byType && byType.has(String(type))) {
      byType.set(String(type), Math.max(0, byType.get(String(type)) - 1));
    }
    return originalRemove.call(this, type, listener, options);
  };
  Object.defineProperty(window, "__aerieAuditListenerTypes", {
    configurable: false,
    enumerable: false,
    value: (node) => {
      const byType = listenerCounts.get(node);
      return byType
        ? Array.from(byType.entries()).filter((entry) => entry[1] > 0).map((entry) => entry[0]).sort()
        : [];
    },
  });
  const mutations = [];
  const observe = () => {
    if (!document.documentElement) return;
    const observer = new MutationObserver((records) => {
      for (const record of records.slice(0, 50)) {
        const target = record.target && record.target.nodeType === 1
          ? record.target
          : record.target && record.target.parentElement;
        mutations.push({
          at: new Date().toISOString(),
          type: record.type,
          tag: target && target.tagName ? target.tagName.toLowerCase() : "",
          id: target && target.id ? target.id : "",
          attribute: record.attributeName || "",
          added: record.addedNodes ? record.addedNodes.length : 0,
          removed: record.removedNodes ? record.removedNodes.length : 0,
        });
      }
      if (mutations.length > 5000) mutations.splice(0, mutations.length - 5000);
    });
    observer.observe(document.documentElement, {
      attributes: true,
      childList: true,
      subtree: true,
    });
  };
  if (document.documentElement) observe();
  else document.addEventListener("DOMContentLoaded", observe, { once: true });
  Object.defineProperty(window, "__aerieAuditMutations", {
    configurable: false,
    enumerable: false,
    value: mutations,
  });
}

async function waitForMainWindow(app) {
  const deadline = Date.now() + 30000;
  while (Date.now() < deadline) {
    for (const page of app.windows()) {
      try {
        const url = (await page.url()).replace(/\\/g, "/");
        if (url.endsWith("/src/renderer/index.html") || await page.locator("#app .sidebar-tab").count()) {
          return page;
        }
      } catch (_) {}
    }
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error("main_window_timeout");
}

async function waitForBackend(page) {
  const deadline = Date.now() + 30000;
  let latest = null;
  while (Date.now() < deadline) {
    try {
      latest = await page.evaluate(() => window.aerie.electron.getHealth());
      if (latest && latest.ready) return latest;
    } catch (_) {}
    await page.waitForTimeout(500);
  }
  throw new Error(`backend_ready_timeout:${JSON.stringify(redactValue(latest))}`);
}

async function collectSurface(page) {
  return page.evaluate(() => {
    const INTERACTIVE_TAGS = new Set(["button", "input", "select", "textarea", "a", "summary", "details"]);
    const INTERACTIVE_ROLES = new Set([
      "button", "checkbox", "combobox", "link", "listbox", "menuitem", "option", "radio",
      "searchbox", "slider", "spinbutton", "switch", "tab", "textbox", "treeitem",
    ]);
    const SENSITIVE = /(?:api[-_ ]?key|apikey|token|secret|password|authorization|cookie|yaml-editor)/i;
    const STATE_CLASSES = new Set([
      "active", "hidden", "visible", "selected", "disabled", "open", "is-open", "is-active",
      "is-visible", "is-selected", "loading", "error", "success", "stale",
    ]);
    const rectObject = (rect) => ({
      x: round(rect.x), y: round(rect.y), width: round(rect.width), height: round(rect.height),
      top: round(rect.top), right: round(rect.right), bottom: round(rect.bottom), left: round(rect.left),
    });
    function round(value) { return Math.round(Number(value || 0) * 100) / 100; }
    function attributeSelectorValue(value) {
      return String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    }
    function unique(selector) {
      try { return document.querySelectorAll(selector).length === 1; }
      catch (_) { return false; }
    }
    function selectorFor(element) {
      if (element.id) {
        const selector = `#${CSS.escape(element.id)}`;
        if (unique(selector)) return { strategy: "id", selector, unique: true, quality: "strong" };
      }
      const stableAttributes = ["data-testid", "data-qa", "data-tab", "data-sub", "data-mode", "data-cog-tab", "name", "aria-label"];
      for (const attribute of stableAttributes) {
        const value = element.getAttribute(attribute);
        if (!value) continue;
        const selector = `${element.tagName.toLowerCase()}[${attribute}="${attributeSelectorValue(value)}"]`;
        if (unique(selector)) return { strategy: attribute, selector, unique: true, quality: "strong" };
      }
      const tag = element.tagName.toLowerCase();
      const stableClasses = Array.from(element.classList || []).filter((name) => !STATE_CLASSES.has(name)).slice(0, 3);
      if (stableClasses.length) {
        const selector = `${tag}.${stableClasses.map((name) => CSS.escape(name)).join(".")}`;
        if (unique(selector)) return { strategy: "class", selector, unique: true, quality: "medium" };
      }
      const parts = [];
      let current = element;
      while (current && current !== document.body && parts.length < 8) {
        const parent = current.parentElement;
        if (!parent) break;
        let part = current.tagName.toLowerCase();
        if (current.id) {
          part = `#${CSS.escape(current.id)}`;
          parts.unshift(part);
          break;
        }
        const siblings = Array.from(parent.children).filter((item) => item.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
        parts.unshift(part);
        current = parent;
      }
      const selector = `body > ${parts.join(" > ")}`;
      return {
        strategy: "structural",
        selector,
        unique: unique(selector),
        quality: "fallback",
      };
    }
    function isStyleVisible(element) {
      let current = element;
      while (current && current.nodeType === 1) {
        const style = getComputedStyle(current);
        if (current.hidden || current.getAttribute("aria-hidden") === "true"
          || style.display === "none" || style.visibility === "hidden" || Number(style.opacity || 1) === 0) {
          return false;
        }
        current = current.parentElement;
      }
      const rect = element.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    }
    function inViewport(rect) {
      return rect.bottom > 0 && rect.right > 0 && rect.top < innerHeight && rect.left < innerWidth;
    }
    function effectiveRole(element) {
      const explicit = element.getAttribute("role");
      if (explicit) return explicit;
      const tag = element.tagName.toLowerCase();
      if (tag === "button") return "button";
      if (tag === "a" && element.hasAttribute("href")) return "link";
      if (tag === "textarea") return "textbox";
      if (tag === "select") return element.multiple ? "listbox" : "combobox";
      if (tag === "input") {
        const type = String(element.type || "text").toLowerCase();
        if (type === "checkbox") return "checkbox";
        if (type === "radio") return "radio";
        if (type === "range") return "slider";
        if (type === "number") return "spinbutton";
        if (type === "search") return "searchbox";
        if (type !== "hidden") return "textbox";
      }
      if (tag === "summary") return "button";
      return "";
    }
    function accessibleName(element) {
      const labelledBy = String(element.getAttribute("aria-labelledby") || "").trim();
      if (labelledBy) {
        const text = labelledBy.split(/\s+/).map((id) => {
          const label = document.getElementById(id);
          return label ? label.textContent.trim() : "";
        }).filter(Boolean).join(" ");
        if (text) return text;
      }
      const explicit = element.getAttribute("aria-label");
      if (explicit && explicit.trim()) return explicit.trim();
      if (element.labels && element.labels.length) {
        const text = Array.from(element.labels).map((label) => label.textContent.trim()).filter(Boolean).join(" ");
        if (text) return text;
      }
      if (element.alt && String(element.alt).trim()) return String(element.alt).trim();
      if (element.title && String(element.title).trim()) return String(element.title).trim();
      const text = (element.innerText || "").trim();
      if (text) return text;
      if ("value" in element && element.value && element.type !== "password") return String(element.value).trim();
      return String(element.placeholder || "").trim();
    }
    function isSensitive(element) {
      return element.type === "password"
        || SENSITIVE.test([element.id, element.name, element.getAttribute("aria-label"), element.placeholder].filter(Boolean).join(" "));
    }
    function listenerTypes(element) {
      try {
        return typeof window.__aerieAuditListenerTypes === "function"
          ? window.__aerieAuditListenerTypes(element)
          : [];
      } catch (_) { return []; }
    }
    function looksInteractive(element, listeners, style) {
      const tag = element.tagName.toLowerCase();
      const role = effectiveRole(element);
      const semanticAncestor = element.closest('button, input, select, textarea, a[href], summary, [role], [tabindex], [contenteditable="true"]');
      const pointerSurface = style.cursor === "pointer"
        && (!semanticAncestor || semanticAncestor === element)
        && !["svg", "use", "path", "circle", "rect", "line", "polyline", "polygon", "span"].includes(tag);
      return INTERACTIVE_TAGS.has(tag)
        || INTERACTIVE_ROLES.has(role)
        || element.hasAttribute("tabindex")
        || element.isContentEditable
        || typeof element.onclick === "function"
        || listeners.some((type) => ["click", "change", "input", "keydown", "pointerdown", "mousedown", "submit"].includes(type))
        || pointerSurface;
    }
    function occlusion(element, rect, visible) {
      if (!visible || !inViewport(rect)) return { occluded: false, blockedPoints: 0, sampledPoints: 0, blockers: [] };
      const insetX = Math.min(Math.max(rect.width * 0.15, 1), Math.max(rect.width / 2, 1));
      const insetY = Math.min(Math.max(rect.height * 0.15, 1), Math.max(rect.height / 2, 1));
      const points = [
        [rect.left + rect.width / 2, rect.top + rect.height / 2],
        [rect.left + insetX, rect.top + insetY],
        [rect.right - insetX, rect.top + insetY],
        [rect.left + insetX, rect.bottom - insetY],
        [rect.right - insetX, rect.bottom - insetY],
      ].filter(([x, y]) => x >= 0 && y >= 0 && x < innerWidth && y < innerHeight);
      const blockers = [];
      let blockedPoints = 0;
      for (const [x, y] of points) {
        const top = document.elementFromPoint(x, y);
        if (top && top !== element && !element.contains(top)) {
          blockedPoints += 1;
          blockers.push(selectorFor(top).selector);
        }
      }
      return {
        occluded: points.length > 0 && blockedPoints >= Math.ceil(points.length * 0.6),
        blockedPoints,
        sampledPoints: points.length,
        blockers: Array.from(new Set(blockers)).slice(0, 5),
      };
    }
    function clippedByAncestors(element, rect) {
      let current = element.parentElement;
      const ancestors = [];
      while (current && current !== document.body) {
        const style = getComputedStyle(current);
        if (["hidden", "clip", "scroll", "auto"].includes(style.overflowX)
          || ["hidden", "clip", "scroll", "auto"].includes(style.overflowY)) {
          const parentRect = current.getBoundingClientRect();
          if (rect.left < parentRect.left - 1 || rect.right > parentRect.right + 1
            || rect.top < parentRect.top - 1 || rect.bottom > parentRect.bottom + 1) {
            ancestors.push(selectorFor(current).selector);
          }
        }
        current = current.parentElement;
      }
      return ancestors;
    }
    const allElements = Array.from(document.querySelectorAll("body *"));
    const domIndices = new Map(allElements.map((element, index) => [element, index]));
    const elements = [];
    for (let domIndex = 0; domIndex < allElements.length; domIndex += 1) {
      const element = allElements[domIndex];
      const style = getComputedStyle(element);
      const listeners = listenerTypes(element);
      const interactive = looksInteractive(element, listeners, style);
      const semantic = interactive
        || element.hasAttribute("id")
        || element.hasAttribute("role")
        || ["img", "canvas", "svg", "video", "audio"].includes(element.tagName.toLowerCase());
      if (!semantic) continue;
      const rect = element.getBoundingClientRect();
      const visible = isStyleVisible(element);
      const locator = selectorFor(element);
      const sensitive = isSensitive(element);
      const text = sensitive ? "<redacted>" : (element.innerText || "").trim().slice(0, 1000);
      const name = accessibleName(element);
      const ownOverflowClipped = visible && text.length > 0
        && ((element.scrollWidth > element.clientWidth + 1 && ["hidden", "clip"].includes(style.overflowX))
          || (element.scrollHeight > element.clientHeight + 1 && ["hidden", "clip"].includes(style.overflowY)));
      const occluded = occlusion(element, rect, visible);
      const clippingAncestors = clippedByAncestors(element, rect);
      elements.push({
        key: `${locator.selector}|${element.tagName.toLowerCase()}|${effectiveRole(element)}`,
        domIndex,
        parentDomIndex: element.parentElement ? (domIndices.get(element.parentElement) ?? -1) : -1,
        locator,
        id: element.id || "",
        tag: element.tagName.toLowerCase(),
        role: effectiveRole(element),
        accessibleName: sensitive ? "<redacted-sensitive-field>" : name,
        text,
        name: element.name || "",
        type: element.type || "",
        placeholder: sensitive ? "<redacted>" : (element.getAttribute("placeholder") || ""),
        title: sensitive ? "<redacted>" : (element.getAttribute("title") || ""),
        href: element.tagName.toLowerCase() === "a" ? String(element.getAttribute("href") || "") : "",
        listenerTypes: listeners,
        interactive,
        sensitive,
        visible,
        actionable: visible && style.pointerEvents !== "none",
        inViewport: visible && inViewport(rect),
        disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
        readOnly: Boolean(element.readOnly || element.getAttribute("aria-readonly") === "true"),
        required: Boolean(element.required || element.getAttribute("aria-required") === "true"),
        checked: "checked" in element ? Boolean(element.checked) : null,
        selected: "selected" in element ? Boolean(element.selected) : null,
        expanded: element.getAttribute("aria-expanded"),
        pressed: element.getAttribute("aria-pressed"),
        current: element.getAttribute("aria-current"),
        invalid: element.getAttribute("aria-invalid"),
        busy: element.getAttribute("aria-busy"),
        tabIndex: Number(element.tabIndex),
        focused: document.activeElement === element,
        value: sensitive ? "<redacted>" : ("value" in element ? String(element.value || "").slice(0, 1000) : ""),
        rect: rectObject(rect),
        scroll: {
          clientWidth: element.clientWidth,
          clientHeight: element.clientHeight,
          scrollWidth: element.scrollWidth,
          scrollHeight: element.scrollHeight,
        },
        style: {
          display: style.display,
          visibility: style.visibility,
          opacity: style.opacity,
          overflowX: style.overflowX,
          overflowY: style.overflowY,
          whiteSpace: style.whiteSpace,
          textOverflow: style.textOverflow,
          wordBreak: style.wordBreak,
          overflowWrap: style.overflowWrap,
          fontFamily: style.fontFamily,
          fontSize: style.fontSize,
          lineHeight: style.lineHeight,
          letterSpacing: style.letterSpacing,
          color: style.color,
          backgroundColor: style.backgroundColor,
          cursor: style.cursor,
          pointerEvents: style.pointerEvents,
          zIndex: style.zIndex,
        },
        clipped: ownOverflowClipped || clippingAncestors.length > 0,
        clippingAncestors,
        occluded: occluded.occluded,
        occlusion: occluded,
      });
    }

    const strings = [];
    const characters = [];
    const textRuns = [];
    let stringSequence = 0;
    function stringProblems(value) {
      return {
        replacementCharacter: value.includes("\uFFFD"),
        controlCharacter: /[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F-\u009F]/u.test(value),
        suspiciousZeroWidth: /[\u200B\u200C\u2060\uFEFF]/u.test(value),
        bidiControl: /[\u202A-\u202E\u2066-\u2069]/u.test(value),
        mojibake: /(?:Ã.|Â.|â€|ï¿½|锟斤拷|閿熸枻鎷|娴滄垶|脙|脗)/u.test(value),
        brokenEntity: /&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-f]+)(?!;)/iu.test(value),
      };
    }
    function addString(source, element, rawValue, node = null) {
      const raw = String(rawValue || "");
      if (!raw.trim()) return;
      const locator = selectorFor(element);
      const stringId = `string-${++stringSequence}`;
      const value = raw.normalize("NFC");
      const problems = stringProblems(value);
      strings.push({
        id: stringId,
        source,
        selector: locator.selector,
        value,
        lengthUtf16: value.length,
        lengthCodePoints: Array.from(value).length,
        problems,
        invalid: Object.values(problems).some(Boolean),
      });
      if (node && source === "text") {
        try {
          const fullRange = document.createRange();
          fullRange.selectNodeContents(node);
          textRuns.push({
            id: stringId,
            selector: locator.selector,
            rects: Array.from(fullRange.getClientRects()).map(rectObject),
          });
        } catch (_) {}
      }
      let utf16Offset = 0;
      let codePointIndex = 0;
      for (const char of Array.from(raw)) {
        let rects = [];
        if (node) {
          try {
            const range = document.createRange();
            range.setStart(node, utf16Offset);
            range.setEnd(node, utf16Offset + char.length);
            rects = Array.from(range.getClientRects()).map(rectObject);
          } catch (_) {}
        } else {
          rects = [rectObject(element.getBoundingClientRect())];
        }
        const codePoint = char.codePointAt(0);
        const charProblems = stringProblems(char);
        characters.push({
          stringId,
          source,
          selector: locator.selector,
          index: codePointIndex,
          utf16Offset,
          character: char,
          codePoint: `U+${codePoint.toString(16).toUpperCase().padStart(4, "0")}`,
          whitespace: /^\s$/u.test(char),
          rects,
          problems: charProblems,
          invalid: Object.values(charProblems).some(Boolean),
        });
        utf16Offset += char.length;
        codePointIndex += 1;
      }
    }
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = walker.nextNode())) {
      if (node.parentElement && isStyleVisible(node.parentElement) && !isSensitive(node.parentElement)) {
        addString("text", node.parentElement, node.nodeValue, node);
      }
    }
    for (const element of allElements) {
      if (isSensitive(element)) continue;
      for (const attribute of ["placeholder", "title", "aria-label", "alt"]) {
        const value = element.getAttribute(attribute);
        if (value) addString(attribute, element, value);
      }
      if (element.tagName === "OPTION") addString("option", element, element.textContent);
      if (isStyleVisible(element)) {
        for (const pseudo of ["::before", "::after"]) {
          const content = getComputedStyle(element, pseudo).content;
          if (content && content !== "none" && content !== "normal" && content !== '""') {
            addString(pseudo, element, content.replace(/^['\"]|['\"]$/g, ""));
          }
        }
      }
    }
    const interactiveElements = elements.filter((item) => item.interactive);
    return {
      url: location.href,
      title: document.title,
      viewport: { width: innerWidth, height: innerHeight, devicePixelRatio },
      document: {
        readyState: document.readyState,
        language: document.documentElement.lang || "",
        allElements: allElements.length,
        bodyTextLength: (document.body.innerText || "").length,
      },
      elements,
      strings,
      characters,
      textRuns,
      mutations: Array.isArray(window.__aerieAuditMutations)
        ? window.__aerieAuditMutations.slice(-500)
        : [],
      summary: {
        allElements: allElements.length,
        semanticElements: elements.length,
        interactiveElements: interactiveElements.length,
        visibleInteractiveElements: interactiveElements.filter((item) => item.actionable).length,
        hiddenInteractiveElements: interactiveElements.filter((item) => !item.actionable).length,
        listenerBackedElements: interactiveElements.filter((item) => item.listenerTypes.length).length,
        invalidStrings: strings.filter((item) => item.invalid).length,
        invalidCharacters: characters.filter((item) => item.invalid).length,
        clippedVisibleElements: elements.filter((item) => item.interactive && item.actionable && item.clipped).length,
        occludedVisibleElements: elements.filter((item) => item.interactive && item.actionable && item.occluded).length,
        unnamedVisibleControls: interactiveElements.filter((item) => item.actionable && !item.accessibleName && item.type !== "hidden").length,
        nonUniqueLocators: interactiveElements.filter((item) => !item.locator.unique).length,
        fallbackLocators: interactiveElements.filter((item) => item.locator.quality === "fallback").length,
        keyboardUnreachable: interactiveElements.filter((item) => item.actionable && !item.disabled && item.tabIndex < 0
          && !["input", "select", "textarea"].includes(item.tag)
          && !(["button", "link"].includes(item.role))).length,
      },
    };
  });
}

function intersection(first, second) {
  const left = Math.max(first.left, second.left);
  const top = Math.max(first.top, second.top);
  const right = Math.min(first.right, second.right);
  const bottom = Math.min(first.bottom, second.bottom);
  if (right <= left || bottom <= top) return null;
  return { left, top, right, bottom, width: right - left, height: bottom - top, area: (right - left) * (bottom - top) };
}

function detectOverlaps(surface) {
  const controls = surface.elements.filter((item) => item.interactive && item.visible && item.inViewport);
  const controlOverlaps = [];
  for (let i = 0; i < controls.length; i += 1) {
    for (let j = i + 1; j < controls.length; j += 1) {
      const first = controls[i];
      const second = controls[j];
      if (first.parentDomIndex === second.domIndex || second.parentDomIndex === first.domIndex) continue;
      const overlap = intersection(first.rect, second.rect);
      if (!overlap || overlap.area < 4) continue;
      const firstArea = Math.max(1, first.rect.width * first.rect.height);
      const secondArea = Math.max(1, second.rect.width * second.rect.height);
      const ratio = overlap.area / Math.min(firstArea, secondArea);
      if (ratio >= 0.15) {
        controlOverlaps.push({
          first: first.locator.selector,
          second: second.locator.selector,
          ratio: Math.round(ratio * 1000) / 1000,
          intersection: overlap,
        });
      }
    }
  }
  const textRects = surface.textRuns.flatMap((run) => run.rects.map((rect) => ({ ...rect, id: run.id, selector: run.selector })));
  const textOverlaps = [];
  for (let i = 0; i < textRects.length; i += 1) {
    for (let j = i + 1; j < textRects.length; j += 1) {
      const first = textRects[i];
      const second = textRects[j];
      if (first.id === second.id || first.selector === second.selector) continue;
      const overlap = intersection(first, second);
      if (!overlap || overlap.area < 2) continue;
      const minArea = Math.max(1, Math.min(first.width * first.height, second.width * second.height));
      const ratio = overlap.area / minArea;
      if (ratio >= 0.25) {
        textOverlaps.push({ first: first.selector, second: second.selector, ratio: Math.round(ratio * 1000) / 1000 });
      }
      if (textOverlaps.length >= 250) break;
    }
    if (textOverlaps.length >= 250) break;
  }
  return { controlOverlaps, textOverlaps };
}

function surfaceFailures(surface, overlaps, options = {}) {
  const failures = [];
  if (!surface.document.bodyTextLength) failures.push("blank_page");
  if (surface.summary.invalidStrings) failures.push(`invalid_strings:${surface.summary.invalidStrings}`);
  if (surface.summary.invalidCharacters) failures.push(`invalid_characters:${surface.summary.invalidCharacters}`);
  if (surface.summary.unnamedVisibleControls) failures.push(`unnamed_visible_controls:${surface.summary.unnamedVisibleControls}`);
  if (surface.summary.nonUniqueLocators) failures.push(`non_unique_locators:${surface.summary.nonUniqueLocators}`);
  if (surface.summary.clippedVisibleElements) failures.push(`clipped_visible_controls:${surface.summary.clippedVisibleElements}`);
  if (surface.summary.occludedVisibleElements) failures.push(`occluded_visible_controls:${surface.summary.occludedVisibleElements}`);
  if (overlaps.controlOverlaps.length) failures.push(`overlapping_controls:${overlaps.controlOverlaps.length}`);
  if (overlaps.textOverlaps.length) failures.push(`overlapping_text:${overlaps.textOverlaps.length}`);
  if (options.expectedSelector && (!options.expectedSelectorCount || !options.expectedSelectorVisible)) {
    failures.push(`expected_selector_missing:${options.expectedSelector}`);
  }
  if (options.expectedText && !options.expectedTextFound) {
    failures.push(`expected_text_missing:${options.expectedText}`);
  }
  if (options.expectedValue && !options.expectedValueFound) {
    failures.push(`expected_value_missing:${options.expectedValue}`);
  }
  return failures;
}

async function expectedEvidence(page, options) {
  const output = {};
  if (options.expectedSelector) {
    output.expectedSelector = options.expectedSelector;
    output.expectedSelectorCount = await page.locator(options.expectedSelector).count();
    output.expectedSelectorVisible = output.expectedSelectorCount
      ? await page.locator(options.expectedSelector).first().isVisible().catch(() => false)
      : false;
  }
  if (options.expectedText) {
    output.expectedText = options.expectedText;
    output.expectedTextFound = await page.locator("body").evaluate(
      (body, expected) => (body.innerText || "").includes(expected),
      options.expectedText,
    ).catch(() => false);
  }
  if (options.expectedValue) {
    output.expectedValue = options.expectedValue;
    output.expectedValueFound = await page.locator(options.expectedSelector || "input, textarea, select")
      .first().inputValue().then((value) => value === options.expectedValue).catch(() => false);
  }
  return output;
}

function registerCatalog(catalog, surface, phaseId) {
  for (const element of surface.elements.filter((item) => item.interactive)) {
    const existing = catalog.get(element.key);
    if (!existing) {
      catalog.set(element.key, {
        key: element.key,
        firstSeenPhase: phaseId,
        lastSeenPhase: phaseId,
        seenPhases: [phaseId],
        visiblePhases: element.visible ? [phaseId] : [],
        descriptor: element,
      });
      continue;
    }
    existing.lastSeenPhase = phaseId;
    if (!existing.seenPhases.includes(phaseId)) existing.seenPhases.push(phaseId);
    if (element.visible && !existing.visiblePhases.includes(phaseId)) existing.visiblePhases.push(phaseId);
    existing.descriptor = element;
  }
}

function screenshotMasks(page) {
  return [page.locator(SECRET_SELECTOR)];
}

async function capturePhase(page, context, phaseId, options = {}) {
  const target = path.join(phaseRoot, ...String(phaseId).split("/").map(safeName));
  mkdir(target);
  const networkStart = options.networkStart == null ? 0 : options.networkStart;
  const consoleStart = options.consoleStart == null ? 0 : options.consoleStart;
  const surface = await collectSurface(page);
  const overlaps = detectOverlaps(surface);
  const expected = await expectedEvidence(page, options);
  const failures = surfaceFailures(surface, overlaps, expected);
  let screenshotError = "";
  try {
    await page.screenshot({
      path: path.join(target, "screenshot.png"),
      fullPage: false,
      animations: "disabled",
      caret: "hide",
      mask: screenshotMasks(page),
      maskColor: "#ff00ff",
    });
  } catch (error) {
    screenshotError = String(error.message || error);
    failures.push("screenshot_failed");
  }
  registerCatalog(context.catalog, surface, phaseId);
  const assertions = {
    ...surface.summary,
    controlOverlaps: overlaps.controlOverlaps.length,
    textOverlaps: overlaps.textOverlaps.length,
    expected,
    screenshotCaptured: !screenshotError,
    screenshotError,
  };
  const result = {
    schemaVersion: AUDIT_SCHEMA_VERSION,
    phaseId,
    state: options.state || "default",
    provenance: options.provenance || "live-electron",
    status: failures.length ? "failed" : "passed",
    failures,
    url: sanitizeUrl(surface.url),
    title: surface.title,
    viewport: surface.viewport,
    assertions,
    evidenceFiles: [
      "result.json", "elements.json", "characters.json", "strings.json", "overlaps.json",
      "mutations.json", "network.json", "console.json", "screenshot.png",
    ],
    capturedAt: nowIso(),
  };
  writeJson(path.join(target, "elements.json"), surface.elements);
  writeJson(path.join(target, "characters.json"), surface.characters);
  writeJson(path.join(target, "strings.json"), surface.strings);
  writeJson(path.join(target, "overlaps.json"), overlaps);
  writeJson(path.join(target, "mutations.json"), surface.mutations);
  writeJson(path.join(target, "network.json"), context.network.slice(networkStart));
  writeJson(path.join(target, "console.json"), context.console.slice(consoleStart));
  writeJson(path.join(target, "result.json"), result);
  appendProgress({ type: "phase", phaseId, status: result.status });
  context.phases.push(result);
  if (options.state) {
    context.states.set(options.state, {
      phaseId,
      status: result.status,
      expected,
      capturedAt: result.capturedAt,
    });
  }
  if (process.env.AERIE_QA_QUIET !== "1") {
    process.stdout.write(`[desktop-audit] ${phaseId}: ${result.status}\n`);
  }
  return { result, surface };
}

async function captureDomState(page, selector) {
  const raw = await page.evaluate((targetSelector) => {
    const SENSITIVE = /(?:api[-_ ]?key|apikey|token|secret|password|authorization|cookie|yaml-editor)/i;
    const target = (() => {
      try { return document.querySelector(targetSelector); }
      catch (_) { return null; }
    })();
    const summarize = (element) => {
      if (!element) return null;
      const sensitive = element.type === "password"
        || SENSITIVE.test([element.id, element.name, element.getAttribute("aria-label")].filter(Boolean).join(" "));
      const attributes = {};
      for (const name of [
        "id", "class", "role", "type", "name", "title", "aria-label", "aria-pressed", "aria-expanded",
        "aria-disabled", "aria-hidden", "data-state", "data-tab", "data-sub", "data-mode",
      ]) {
        const value = element.getAttribute(name);
        if (value != null) attributes[name] = sensitive ? "<redacted>" : value;
      }
      const clone = element.cloneNode(true);
      for (const field of clone.querySelectorAll("input, textarea, select, [contenteditable]")) {
        const fieldSensitive = field.type === "password"
          || SENSITIVE.test([field.id, field.name, field.getAttribute("aria-label")].filter(Boolean).join(" "));
        field.removeAttribute("value");
        if (fieldSensitive) field.textContent = "<redacted>";
      }
      for (const media of clone.querySelectorAll("img, source, video, audio, a")) {
        media.removeAttribute("src");
        media.removeAttribute("href");
      }
      return {
        tag: element.tagName.toLowerCase(),
        attributes,
        text: sensitive ? "<redacted>" : (element.innerText || "").trim().slice(0, 2000),
        value: sensitive ? "<redacted>" : ("value" in element ? String(element.value || "").slice(0, 1000) : ""),
        disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
        checked: "checked" in element ? Boolean(element.checked) : null,
        outerHtml: clone.outerHTML.slice(0, 5000),
      };
    };
    const activePanel = document.querySelector(".tab-panel.active");
    const dialogs = Array.from(document.querySelectorAll('[role="dialog"], .modal, [class*="modal"], [class*="drawer"]'))
      .filter((element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && Number(style.opacity || 1) > 0
          && rect.width > 0 && rect.height > 0;
      })
      .map((element) => ({ id: element.id || "", className: String(element.className || "").slice(0, 500) }))
      .slice(0, 100);
    return {
      target: summarize(target),
      activeElement: summarize(document.activeElement),
      activePanel: activePanel ? {
        id: activePanel.id,
        className: activePanel.className,
        text: (activePanel.innerText || "").trim().slice(0, 5000),
        interactiveCount: activePanel.querySelectorAll('button, input, select, textarea, a[href], [role], [tabindex], [contenteditable="true"]').length,
      } : null,
      visibleDialogs: dialogs,
      bodyClass: document.body.className,
      url: location.href,
    };
  }, selector);
  const serialized = JSON.stringify(redactValue(raw));
  return { ...redactValue(raw), sha256: sha256(serialized) };
}

function interactionCounts(context, networkStart, consoleStart) {
  return {
    networkEvents: context.network.length - networkStart,
    consoleEvents: context.console.length - consoleStart,
    networkRange: { start: networkStart, end: context.network.length },
    consoleRange: { start: consoleStart, end: context.console.length },
  };
}

async function recordClick(page, context, control, action, options = {}) {
  const selector = control.locator.selector;
  const locator = page.locator(selector).first();
  const networkStart = context.network.length;
  const consoleStart = context.console.length;
  const before = await captureDomState(page, selector);
  const startedAt = nowIso();
  let status = "passed";
  let error = "";
  let after = null;
  try {
    if (!(await locator.isVisible().catch(() => false))) {
      throw new Error("control_became_hidden_before_interaction");
    }
    await locator.scrollIntoViewIfNeeded({ timeout: 750 });
    await locator.click({ timeout: options.timeout || 2500 });
    await page.waitForTimeout(options.settleMs == null ? 150 : options.settleMs);
    after = await captureDomState(page, selector);
  } catch (caught) {
    status = "failed";
    error = String(caught.message || caught);
    after = await captureDomState(page, selector).catch(() => null);
  }
  const record = {
    controlKey: control.key,
    selector,
    locator: control.locator,
    module: options.module || "unknown",
    action,
    status,
    error,
    before,
    after,
    domChanged: Boolean(before && after && before.sha256 !== after.sha256),
    ...interactionCounts(context, networkStart, consoleStart),
    startedAt,
    completedAt: nowIso(),
  };
  context.interactions.push(record);
  context.covered.add(control.key);
  appendProgress({ type: "interaction", selector, action, status, module: record.module });
  return record;
}

function recordSafeSkip(context, control, module, classification, extra = {}) {
  const record = {
    controlKey: control.key,
    selector: control.locator.selector,
    locator: control.locator,
    module,
    action: "safe-skip",
    status: "safe-skipped",
    category: classification.category,
    reason: classification.reason,
    before: null,
    after: null,
    domChanged: false,
    networkEvents: 0,
    consoleEvents: 0,
    startedAt: nowIso(),
    completedAt: nowIso(),
    ...extra,
  };
  context.interactions.push(record);
  context.covered.add(control.key);
  appendProgress({ type: "interaction", selector: record.selector, action: record.action, status: record.status, module });
  return record;
}

async function recordInputInteraction(page, context, control, module) {
  const selector = control.locator.selector;
  const locator = page.locator(selector).first();
  const networkStart = context.network.length;
  const consoleStart = context.console.length;
  const before = await captureDomState(page, selector);
  const startedAt = nowIso();
  let status = "passed";
  let action = "fill-restore";
  let observed = {};
  let error = "";
  try {
    if (!(await locator.isVisible().catch(() => false))) {
      throw new Error("control_became_hidden_before_interaction");
    }
    const tag = control.tag;
    const type = String(control.type || "text").toLowerCase();
    if (control.readOnly) {
      action = "assert-readonly";
      observed = { readOnly: true };
    } else if (["checkbox", "radio"].includes(type)) {
      action = "toggle-restore";
      const beforeChecked = await locator.isChecked();
      let priorGroup = null;
      if (type === "radio" && control.name) {
        priorGroup = await page.locator(`input[type="radio"][name="${control.name.replace(/"/g, '\\"')}"]:checked`).getAttribute("id").catch(() => null);
      }
      await locator.click({ timeout: 2500 });
      const afterChecked = await locator.isChecked();
      if (type === "checkbox" && afterChecked !== beforeChecked) await locator.click({ timeout: 2500 });
      if (type === "radio" && !beforeChecked && priorGroup) await page.locator(`#${priorGroup}`).click().catch(() => {});
      observed = { beforeChecked, afterChecked };
      if (type === "checkbox" && beforeChecked === afterChecked) status = "failed";
    } else if (tag === "select") {
      action = "select-restore";
      const beforeValue = await locator.inputValue();
      const values = await locator.locator("option").evaluateAll((options) => options.map((item) => item.value));
      const alternative = values.find((value) => value !== beforeValue);
      if (alternative !== undefined) await locator.selectOption(alternative);
      const afterValue = await locator.inputValue();
      if (values.includes(beforeValue)) await locator.selectOption(beforeValue);
      observed = { beforeValue, afterValue, alternative: alternative == null ? null : alternative };
      if (alternative !== undefined && afterValue !== alternative) status = "failed";
    } else if (control.tag === "input" || control.tag === "textarea") {
      const beforeValue = await locator.inputValue();
      const sample = type === "date" ? "2026-07-26"
        : type === "time" ? "13:24"
        : type === "number" || type === "range" ? "1"
        : type === "color" ? "#336699"
        : "Aerie QA synthetic input";
      await locator.fill(sample);
      const afterValue = await locator.inputValue();
      await locator.fill(beforeValue);
      observed = { beforeValue, afterValue, sample };
      if (afterValue !== sample) status = "failed";
    } else if (control.tag === "a") {
      action = "focus-link";
      await locator.focus();
      observed = { focused: await locator.evaluate((node) => document.activeElement === node) };
      if (!observed.focused) status = "failed";
    } else {
      action = "focus-contenteditable";
      await locator.focus();
      observed = { focused: await locator.evaluate((node) => document.activeElement === node) };
      if (!observed.focused) status = "failed";
    }
  } catch (caught) {
    status = "failed";
    error = String(caught.message || caught);
  }
  const after = await captureDomState(page, selector).catch(() => null);
  const record = {
    controlKey: control.key,
    selector,
    locator: control.locator,
    module,
    action,
    status,
    error,
    observed,
    before,
    after,
    domChanged: Boolean(before && after && before.sha256 !== after.sha256),
    ...interactionCounts(context, networkStart, consoleStart),
    startedAt,
    completedAt: nowIso(),
  };
  context.interactions.push(record);
  context.covered.add(control.key);
  appendProgress({ type: "interaction", selector, action, status, module });
  return record;
}

async function exerciseVisibleControls(page, context, module) {
  const surface = await collectSurface(page);
  registerCatalog(context.catalog, surface, `discovery/${module}`);
  const controls = surface.elements.filter((item) => item.interactive && item.actionable);
  for (const control of controls) {
    if (context.covered.has(control.key)) continue;
    if (RUNTIME_FLOW_SELECTORS.has(control.locator.selector)) continue;
    if (["data-tab", "data-sub", "data-mode", "data-cog-tab", "data-window"].includes(control.locator.strategy)
      || control.role === "tab") continue;
    const classification = classifyDedicatedControl(control);
    if (classification && isAllowedSafeSkip(control, classification)) {
      recordSafeSkip(context, control, module, classification);
      continue;
    }
    if (control.disabled) {
      context.interactions.push({
        controlKey: control.key,
        selector: control.locator.selector,
        locator: control.locator,
        module,
        action: "assert-disabled",
        status: "passed",
        observed: { disabled: true },
        before: await captureDomState(page, control.locator.selector).catch(() => null),
        after: null,
        domChanged: false,
        networkEvents: 0,
        consoleEvents: 0,
        startedAt: nowIso(),
        completedAt: nowIso(),
      });
      context.covered.add(control.key);
      continue;
    }
    if (control.tag === "input" && String(control.type).toLowerCase() === "file") {
      recordSafeSkip(context, control, module, {
        category: "file-input",
        reason: "File inputs are only populated by the synthetic attachment fixture flow.",
      });
      continue;
    }
    if (["input", "textarea", "select", "a"].includes(control.tag) || control.readOnly) {
      await recordInputInteraction(page, context, control, module);
      continue;
    }
    await recordClick(page, context, control, "click", { module });
    await page.keyboard.press("Escape").catch(() => {});
  }
}

async function describeControl(page, selector) {
  return page.locator(selector).first().evaluate((element) => {
    const STATE_CLASSES = new Set([
      "active", "hidden", "visible", "selected", "disabled", "open", "is-open", "is-active",
      "is-visible", "is-selected", "loading", "error", "success", "stale",
    ]);
    const attributeValue = (value) => String(value).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
    const unique = (value) => {
      try { return document.querySelectorAll(value).length === 1; }
      catch (_) { return false; }
    };
    const locatorFor = () => {
      if (element.id) {
        const value = `#${CSS.escape(element.id)}`;
        if (unique(value)) return { strategy: "id", selector: value, unique: true, quality: "strong" };
      }
      for (const attribute of ["data-testid", "data-qa", "data-tab", "data-sub", "data-mode", "data-cog-tab", "name", "aria-label"]) {
        const value = element.getAttribute(attribute);
        if (!value) continue;
        const candidate = `${element.tagName.toLowerCase()}[${attribute}="${attributeValue(value)}"]`;
        if (unique(candidate)) return { strategy: attribute, selector: candidate, unique: true, quality: "strong" };
      }
      const tag = element.tagName.toLowerCase();
      const classes = Array.from(element.classList || []).filter((name) => !STATE_CLASSES.has(name)).slice(0, 3);
      if (classes.length) {
        const candidate = `${tag}.${classes.map((name) => CSS.escape(name)).join(".")}`;
        if (unique(candidate)) return { strategy: "class", selector: candidate, unique: true, quality: "medium" };
      }
      const parts = [];
      let current = element;
      while (current && current !== document.body && parts.length < 8) {
        const parent = current.parentElement;
        if (!parent) break;
        let part = current.tagName.toLowerCase();
        const siblings = Array.from(parent.children).filter((item) => item.tagName === current.tagName);
        if (siblings.length > 1) part += `:nth-of-type(${siblings.indexOf(current) + 1})`;
        parts.unshift(part);
        current = parent;
      }
      const candidate = `body > ${parts.join(" > ")}`;
      return { strategy: "structural", selector: candidate, unique: unique(candidate), quality: "fallback" };
    };
    const role = element.getAttribute("role") || (() => {
      const tag = element.tagName.toLowerCase();
      if (tag === "button") return "button";
      if (tag === "a" && element.hasAttribute("href")) return "link";
      if (["input", "textarea"].includes(tag)) return "textbox";
      if (tag === "select") return "combobox";
      return "";
    })();
    const locator = locatorFor();
    const labels = element.labels && element.labels.length
      ? Array.from(element.labels).map((label) => label.textContent.trim()).filter(Boolean).join(" ")
      : "";
    const accessibleName = element.getAttribute("aria-label") || labels || element.title
      || (element.innerText || "").trim() || element.placeholder || "";
    const sensitive = element.type === "password"
      || /(?:api[-_ ]?key|apikey|token|secret|password|authorization|cookie|yaml-editor)/i
        .test([element.id, element.name, element.getAttribute("aria-label")].filter(Boolean).join(" "));
    return {
      key: `${locator.selector}|${element.tagName.toLowerCase()}|${role}`,
      locator,
      id: element.id || "",
      tag: element.tagName.toLowerCase(),
      role,
      accessibleName: sensitive ? "<redacted-sensitive-field>" : accessibleName,
      text: sensitive ? "<redacted>" : (element.innerText || "").trim().slice(0, 1000),
      name: element.name || "",
      type: element.type || "",
      title: sensitive ? "<redacted>" : (element.title || ""),
      sensitive,
      visible: true,
      disabled: Boolean(element.disabled || element.getAttribute("aria-disabled") === "true"),
      readOnly: Boolean(element.readOnly || element.getAttribute("aria-readonly") === "true"),
    };
  }).catch(() => null);
}

async function findControl(page, selector) {
  return describeControl(page, selector);
}

async function recordKnownClick(page, context, selector, module, action = "click", options = {}) {
  const control = await findControl(page, selector);
  if (!control) {
    context.interactions.push({
      controlKey: `${selector}|missing`,
      selector,
      locator: { strategy: "provided", selector, unique: false, quality: "provided" },
      module,
      action,
      status: "failed",
      error: "control_not_found",
      startedAt: nowIso(),
      completedAt: nowIso(),
    });
    return null;
  }
  return recordClick(page, context, control, action, { module, ...options });
}

async function auditWindowControls(app, page, context) {
  const maximize = await findControl(page, "#btn-maximize");
  if (maximize) {
    const beforeNative = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) => item.webContents.getURL().includes("renderer/index.html"));
      return win ? { maximized: win.isMaximized(), minimized: win.isMinimized(), visible: win.isVisible() } : null;
    });
    const record = await recordClick(page, context, maximize, "toggle-maximize", { module: "window-controls", settleMs: 250 });
    const toggledNative = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) => item.webContents.getURL().includes("renderer/index.html"));
      return win ? { maximized: win.isMaximized(), minimized: win.isMinimized(), visible: win.isVisible() } : null;
    });
    await page.locator("#btn-maximize").click().catch(() => {});
    await page.waitForTimeout(200);
    const restoredNative = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) => item.webContents.getURL().includes("renderer/index.html"));
      return win ? { maximized: win.isMaximized(), minimized: win.isMinimized(), visible: win.isVisible() } : null;
    });
    record.observedNative = { before: beforeNative, toggled: toggledNative, restored: restoredNative };
    if (!beforeNative || !toggledNative || beforeNative.maximized === toggledNative.maximized
      || restoredNative.maximized !== beforeNative.maximized) {
      record.status = "failed";
      record.error = record.error || "maximize_state_did_not_toggle_and_restore";
    }
  }

  const minimize = await findControl(page, "#btn-minimize");
  if (minimize) {
    const record = await recordClick(page, context, minimize, "minimize-and-restore", {
      module: "window-controls",
      settleMs: 200,
    });
    const minimizedNative = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) => item.webContents.getURL().includes("renderer/index.html"));
      return win ? { minimized: win.isMinimized(), visible: win.isVisible() } : null;
    });
    await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) => item.webContents.getURL().includes("renderer/index.html"));
      if (win) {
        if (win.isMinimized()) win.restore();
        win.show();
        win.focus();
      }
    });
    await page.waitForTimeout(250);
    const restoredNative = await app.evaluate(({ BrowserWindow }) => {
      const win = BrowserWindow.getAllWindows().find((item) => item.webContents.getURL().includes("renderer/index.html"));
      return win ? { minimized: win.isMinimized(), visible: win.isVisible() } : null;
    });
    record.observedNative = { minimized: minimizedNative, restored: restoredNative };
    if (!minimizedNative || !minimizedNative.minimized || !restoredNative || restoredNative.minimized || !restoredNative.visible) {
      record.status = "failed";
      record.error = record.error || "minimize_state_did_not_restore";
    }
  }
}

async function navigateTab(page, context, tabName) {
  const selector = `.sidebar-tab[data-tab="${tabName}"]`;
  const record = await recordKnownClick(page, context, selector, `tab:${tabName}`, "activate-tab", { settleMs: 300 });
  return record && record.status === "passed";
}

async function auditStateCoverage(page, context) {
  await capturePhase(page, context, "states/success", {
    state: "success",
    provenance: "live-backend",
    expectedSelector: "#status-dot.status-dot--ok",
    expectedText: "后端已连接",
  });

  await navigateTab(page, context, "chat");
  await capturePhase(page, context, "states/empty", {
    state: "empty",
    provenance: "isolated-empty-database",
    expectedSelector: ".chat-empty",
  });

  const chatInput = page.locator("#chat-input");
  const originalValue = await chatInput.inputValue().catch(() => "");
  await chatInput.fill("Aerie QA synthetic filled state");
  await capturePhase(page, context, "states/filled", {
    state: "filled",
    provenance: "synthetic-ephemeral-input",
    expectedSelector: "#chat-input",
    expectedValue: "Aerie QA synthetic filled state",
  });
  await chatInput.fill(originalValue);

  await navigateTab(page, context, "data");
  await capturePhase(page, context, "states/disabled", {
    state: "disabled",
    provenance: "isolated-empty-pagination",
    expectedSelector: "#data-prev-btn:disabled",
  });

  await page.evaluate(() => {
    if (typeof window._setStaleState === "function") {
      window._setStaleState({
        stale: true,
        modified: ["qa_synthetic_module.py"],
        started_at: "2026-07-26T00:00:00Z",
      });
    }
  });
  await capturePhase(page, context, "states/stale", {
    state: "stale",
    provenance: "controlled-renderer-state",
    expectedSelector: ".stale-banner",
    expectedText: "qa_synthetic_module.py",
  });
  await page.evaluate(() => {
    if (typeof window._setStaleState === "function") window._setStaleState({ stale: false });
  });

  await page.evaluate(() => {
    if (!window.briefDrawer) return;
    window.briefDrawer.close();
    window.briefDrawer._cached = null;
    window.briefDrawer._loading = true;
    window.briefDrawer.open();
    if (typeof window.briefDrawer._showSkeleton === "function") window.briefDrawer._showSkeleton();
  });
  await capturePhase(page, context, "states/loading", {
    state: "loading",
    provenance: "controlled-production-renderer-path",
    expectedSelector: ".brief-drawer__skeleton",
  });

  await page.evaluate(() => {
    if (!window.briefDrawer) return;
    window.briefDrawer._loading = false;
    window.briefDrawer.open();
    if (typeof window.briefDrawer._renderError === "function") {
      window.briefDrawer._renderError("QA synthetic unavailable state");
    }
  });
  await capturePhase(page, context, "states/error", {
    state: "error",
    provenance: "controlled-production-renderer-path",
    expectedSelector: ".brief-drawer__error",
    expectedText: "QA synthetic unavailable state",
  });
  await page.evaluate(() => { if (window.briefDrawer) window.briefDrawer.close(); });
}

async function auditSubTabs(page, context, tabName, phasePrefix) {
  const groups = [
    { selector: ".emh-window", attribute: "data-window", name: "emotion-window" },
    { selector: ".data-subtab", attribute: "data-sub", name: "data-subtab" },
    { selector: ".settings-mode-tab", attribute: "data-mode", name: "settings-mode" },
    { selector: ".cog-tab", attribute: "data-cog-tab", name: "cognition-tab" },
    { selector: ".cal-filter-btn", attribute: "data-type", name: "calendar-filter" },
  ];
  for (const group of groups) {
    const candidates = await page.locator(`${group.selector}:visible`).evaluateAll((nodes, attribute) => nodes.map((node) => ({
      value: node.getAttribute(attribute) || (node.innerText || "").trim(),
      text: (node.innerText || "").trim(),
    })), group.attribute).catch(() => []);
    for (const candidate of candidates) {
      const selector = `${group.selector}[${group.attribute}="${String(candidate.value).replace(/"/g, '\\"')}"]`;
      await recordKnownClick(page, context, selector, `tab:${tabName}`, "activate-subtab", { settleMs: 250 });
      await capturePhase(page, context, `${phasePrefix}/subtabs/${group.name}-${safeName(candidate.value)}`, {
        provenance: "live-electron-subtab",
        expectedSelector: selector,
      });
    }
  }
}

async function auditMainTabs(page, context) {
  const tabs = await page.locator(".sidebar-tab").evaluateAll((nodes) => nodes.map((node) => ({
    tab: node.getAttribute("data-tab"),
    text: (node.innerText || "").trim(),
  }))).then((items) => items.filter((item) => item.tab));
  context.tabs = tabs;
  for (let index = 0; index < tabs.length; index += 1) {
    const tab = tabs[index];
    await navigateTab(page, context, tab.tab);
    const prefix = `panels/${String(index + 1).padStart(2, "0")}-${safeName(tab.tab)}`;
    await capturePhase(page, context, `${prefix}/default`, {
      provenance: "live-electron-panel",
      expectedSelector: `#panel-${tab.tab}.active`,
    });
    await auditSubTabs(page, context, tab.tab, prefix);
    await exerciseVisibleControls(page, context, `tab:${tab.tab}`);
    await page.evaluate(() => {
      if (window.briefDrawer) window.briefDrawer.close();
      document.querySelectorAll(".cal-modal:not(.hidden), .data-modal:not(.hidden)").forEach((element) => element.classList.add("hidden"));
    }).catch(() => {});
  }
}

async function auditBriefDrawer(page, context) {
  await navigateTab(page, context, "chat");
  await recordKnownClick(page, context, "#chat-brief-btn", "runtime:brief", "open-brief", { settleMs: 350 });
  await capturePhase(page, context, "runtime/brief/live", {
    provenance: "live-electron-runtime",
    expectedSelector: ".brief-drawer.is-open",
  });
  await exerciseVisibleControls(page, context, "runtime:brief");
  await page.evaluate(() => { if (window.briefDrawer) window.briefDrawer.close(); });
}

async function auditOfficeMenu(page, context) {
  await navigateTab(page, context, "chat");
  const original = await page.locator(".office-menu__item--active").getAttribute("data-mode").catch(() => null);
  const modes = ["auto", "chat", "office"];
  for (const mode of modes) {
    await recordKnownClick(page, context, "#chat-office-btn", "runtime:office", "open-office-menu", { settleMs: 100 });
    await capturePhase(page, context, `runtime/office/menu-${mode}`, {
      provenance: "live-electron-runtime",
      expectedSelector: ".office-menu.office-menu--visible",
    });
    const selector = `.office-menu__item[data-mode="${mode}"]`;
    await recordKnownClick(page, context, selector, "runtime:office", "select-office-mode", { settleMs: 150 });
  }
  if (original && modes.includes(original)) {
    await page.locator("#chat-office-btn").click().catch(() => {});
    await page.locator(`.office-menu__item[data-mode="${original}"]`).click().catch(() => {});
  }
}

async function auditCalendarModal(page, context) {
  await navigateTab(page, context, "memorial");
  const opened = await recordKnownClick(page, context, "#cal-add-btn", "runtime:calendar", "open-add-event", { settleMs: 150 });
  if (!opened || opened.status !== "passed") return;
  await capturePhase(page, context, "runtime/calendar/add-modal", {
    provenance: "live-electron-runtime",
    expectedSelector: "#cal-event-modal:not(.hidden)",
  });
  await exerciseVisibleControls(page, context, "runtime:calendar-modal");
  await page.locator("#cal-event-modal .cal-modal-close").click().catch(() => {});
}

async function auditKnowledgeModal(page, context) {
  await navigateTab(page, context, "data");
  await recordKnownClick(page, context, '.data-subtab[data-sub="knowledge"]', "runtime:knowledge", "activate-knowledge", { settleMs: 200 });
  const opened = await recordKnownClick(page, context, "#knowledge-add-btn", "runtime:knowledge", "open-add-knowledge", { settleMs: 150 });
  if (!opened || opened.status !== "passed") return;
  await capturePhase(page, context, "runtime/knowledge/add-modal", {
    provenance: "live-electron-runtime",
    expectedSelector: "#knowledge-modal:not(.hidden)",
  });
  await exerciseVisibleControls(page, context, "runtime:knowledge-modal");
  await page.locator("#knowledge-modal [data-knowledge-close]").last().click().catch(() => {});
}

async function auditPersonaEditor(page, context) {
  await navigateTab(page, context, "persona-hub");
  await page.waitForTimeout(250);
  const opened = await recordKnownClick(page, context, "#persona-hub-create-btn", "runtime:persona", "open-persona-editor", { settleMs: 150 });
  if (!opened || opened.status !== "passed") return;
  await capturePhase(page, context, "runtime/persona/editor", {
    provenance: "live-electron-runtime",
    expectedSelector: "#persona-hub-editor-view:not(.persona-hub__editor-view--hidden)",
  });
  await exerciseVisibleControls(page, context, "runtime:persona-editor");
  await page.locator("#persona-hub-back-btn").click().catch(() => {});
}

async function auditApprovalModal(page, context) {
  await page.waitForFunction(() => window.approvalModal && typeof window.approvalModal._onNewApproval === "function", null, { timeout: 5000 }).catch(() => {});
  const injected = await page.evaluate(() => {
    if (!window.approvalModal || typeof window.approvalModal._onNewApproval !== "function") return false;
    window.approvalModal._onNewApproval({
      id: "qa-synthetic-approval",
      action_type: "qa.synthetic.inspect",
      risk_level: "low",
      params: { target: "synthetic-record" },
    });
    return true;
  });
  if (!injected) {
    context.runtimeFailures.push("approval_modal_not_initialized");
    return;
  }
  await capturePhase(page, context, "runtime/approval/synthetic", {
    provenance: "synthetic-runtime-event",
    expectedSelector: "#approval-modal-overlay.approval-modal-overlay--visible",
    expectedText: "qa.synthetic.inspect",
  });
  const reject = await findControl(page, "#approval-reject-btn");
  if (reject) {
    const classification = {
      category: "synthetic-approval-rejection",
      reason: "Executed against a non-existent synthetic approval ID in the isolated database.",
    };
    const record = await recordClick(page, context, reject, "reject-synthetic-approval", { module: "runtime:approval", settleMs: 150 });
    record.safety = classification;
  }
}

async function auditAttachmentFixture(page, context) {
  if (process.env.AERIE_QA_ATTACHMENT_FIXTURE === "0") {
    context.runtimeNotes.push("attachment_fixture_disabled_by_environment");
    return;
  }
  await navigateTab(page, context, "chat");
  const input = page.locator("#chat-file-input");
  if (!(await input.count())) {
    context.runtimeFailures.push("chat_file_input_missing");
    return;
  }
  const networkStart = context.network.length;
  const consoleStart = context.console.length;
  await input.setInputFiles({
    name: "qa-synthetic-sentinel.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("AERIE_QA_SYNTHETIC_ATTACHMENT_SENTINEL", "utf8"),
  });
  await page.waitForTimeout(100);
  await capturePhase(page, context, "runtime/attachment/queued", {
    provenance: "synthetic-in-memory-fixture",
    expectedSelector: "#chat-attach-preview",
    networkStart,
    consoleStart,
  });
  const terminal = await page.waitForFunction(() => {
    const item = window._chat && window._chat._pendingAttachments && window._chat._pendingAttachments[0];
    return item && ["ready", "failed", "quarantined", "unsupported"].includes(item.state) ? item.state : false;
  }, null, { timeout: 30000 }).then((handle) => handle.jsonValue()).catch(() => "timeout");
  await capturePhase(page, context, `runtime/attachment/${safeName(terminal)}`, {
    provenance: "synthetic-in-memory-fixture",
    expectedSelector: "#chat-attach-preview",
    networkStart,
    consoleStart,
  });
  context.interactions.push({
    controlKey: "#chat-file-input|input|textbox",
    selector: "#chat-file-input",
    locator: { strategy: "id", selector: "#chat-file-input", unique: true, quality: "strong" },
    module: "runtime:attachment",
    action: "set-synthetic-file",
    status: terminal === "ready" ? "passed" : "failed",
    observed: { terminalState: terminal, filename: "qa-synthetic-sentinel.txt" },
    ...interactionCounts(context, networkStart, consoleStart),
    startedAt: nowIso(),
    completedAt: nowIso(),
  });
  const remove = page.locator("[data-pending-attachment-remove]").first();
  if (await remove.count()) await remove.click().catch(() => {});
}

async function auditRuntimeSurfaces(page, context) {
  await auditBriefDrawer(page, context);
  await auditOfficeMenu(page, context);
  await auditCalendarModal(page, context);
  await auditKnowledgeModal(page, context);
  await auditPersonaEditor(page, context);
  await auditApprovalModal(page, context);
  await auditAttachmentFixture(page, context);
}

async function auditAuxiliaryWindows(app, mainPage, context) {
  const pages = app.windows().filter((page) => page !== mainPage);
  const windows = [];
  for (let index = 0; index < pages.length; index += 1) {
    const page = pages[index];
    await page.waitForLoadState("domcontentloaded").catch(() => {});
    const url = sanitizeUrl(await page.url());
    const name = url.includes("dynamic-island") ? "dynamic-island" : `window-${index + 1}`;
    const capture = await capturePhase(page, context, `windows/${safeName(name)}`, {
      provenance: "live-electron-window",
    });
    await exerciseVisibleControls(page, context, `window:${name}`);
    windows.push({ name, url, title: capture.surface.title, summary: capture.surface.summary });
  }
  context.windows = windows;
}

function attachPageTelemetry(page, context) {
  if (context.instrumentedPages.has(page)) return;
  context.instrumentedPages.add(page);
  page.on("console", (message) => {
    context.console.push({
      source: "renderer",
      type: message.type(),
      text: redactText(message.text()),
      url: sanitizeUrl(page.url()),
      at: nowIso(),
    });
  });
  page.on("pageerror", (error) => {
    context.console.push({
      source: "renderer",
      type: "pageerror",
      text: redactText(error.message || String(error)),
      url: sanitizeUrl(page.url()),
      at: nowIso(),
    });
  });
  page.on("dialog", async (dialog) => {
    context.dialogs.push({
      type: dialog.type(),
      message: redactText(dialog.message()),
      defaultValue: "<not-recorded>",
      action: "dismissed",
      at: nowIso(),
    });
    await dialog.dismiss().catch(() => {});
  });
  page.on("request", (request) => {
    const id = `request-${++context.requestSequence}`;
    context.requestIds.set(request, id);
    context.network.push({
      id,
      event: "request",
      method: request.method(),
      resourceType: request.resourceType(),
      url: sanitizeUrl(request.url()),
      frameUrl: sanitizeUrl(request.frame() ? request.frame().url() : ""),
      bodyRecorded: false,
      at: nowIso(),
    });
  });
  page.on("response", (response) => {
    const request = response.request();
    context.network.push({
      id: context.requestIds.get(request) || "unknown",
      event: "response",
      status: response.status(),
      statusText: response.statusText(),
      url: sanitizeUrl(response.url()),
      fromServiceWorker: response.fromServiceWorker(),
      at: nowIso(),
    });
  });
  page.on("requestfailed", (request) => {
    context.network.push({
      id: context.requestIds.get(request) || "unknown",
      event: "requestfailed",
      method: request.method(),
      resourceType: request.resourceType(),
      url: sanitizeUrl(request.url()),
      errorText: redactText((request.failure() && request.failure().errorText) || "unknown"),
      at: nowIso(),
    });
  });
}

function attachProcessTelemetry(app, context) {
  const child = app.process();
  for (const [source, stream] of [["electron-stdout", child.stdout], ["electron-stderr", child.stderr]]) {
    if (!stream) continue;
    stream.setEncoding("utf8");
    stream.on("data", (chunk) => {
      const lines = String(chunk).split(/\r?\n/).filter(Boolean);
      for (const line of lines) {
        context.console.push({ source, type: source.endsWith("stderr") ? "error" : "log", text: redactText(line), at: nowIso() });
      }
    });
  }
}

function reconcileCatalog(context) {
  const results = [];
  for (const entry of context.catalog.values()) {
    const descriptor = entry.descriptor;
    const existing = context.interactions.find((interaction) => interaction.controlKey === descriptor.key);
    if (existing) {
      results.push({
        ...entry,
        result: existing.status,
        action: existing.action,
        reason: existing.reason || existing.error || "",
      });
      continue;
    }
    const classification = classifyDedicatedControl(descriptor);
    if (classification) {
      const record = recordSafeSkip(context, descriptor, "catalog-reconciliation", classification, {
        visibility: descriptor.visible ? "visible" : "hidden",
      });
      results.push({ ...entry, result: record.status, action: record.action, reason: record.reason });
      continue;
    }
    const hiddenBackingInput = descriptor.tag === "input"
      && ["hidden", "file"].includes(String(descriptor.type || "").toLowerCase());
    if (hiddenBackingInput) {
      const classificationForHidden = {
        category: "hidden-backing-input",
        reason: "Hidden backing inputs are exercised only through their visible purpose-built controls.",
      };
      const record = recordSafeSkip(context, descriptor, "catalog-reconciliation", classificationForHidden, {
        visibility: "hidden",
      });
      results.push({ ...entry, result: record.status, action: record.action, reason: record.reason });
      continue;
    }
    const record = {
      controlKey: descriptor.key,
      selector: descriptor.locator.selector,
      locator: descriptor.locator,
      module: "catalog-reconciliation",
      action: "not-reached",
      status: "failed",
      error: descriptor.visible
        ? "visible_control_not_exercised"
        : "control_never_reached_a_visible_state",
      startedAt: nowIso(),
      completedAt: nowIso(),
    };
    context.interactions.push(record);
    context.covered.add(descriptor.key);
    results.push({ ...entry, result: record.status, action: record.action, reason: record.error });
  }
  return results;
}

function createContext() {
  return {
    catalog: new Map(),
    console: [],
    covered: new Set(),
    dialogs: [],
    instrumentedPages: new WeakSet(),
    interactions: [],
    network: [],
    phases: [],
    requestIds: new WeakMap(),
    requestSequence: 0,
    runtimeFailures: [],
    runtimeNotes: [],
    states: new Map(),
    tabs: [],
    windows: [],
  };
}

function prepareRuntimeEnvironment() {
  mkdir(runtimeRoot);
  mkdir(phaseRoot);
  const envFile = path.join(runtimeRoot, "qa.env");
  fs.writeFileSync(envFile, [
    "AERIE_DISABLE_QQ=1",
    "AERIE_DISABLE_PROACTIVE=1",
    "AERIE_MOBILE_GATEWAY_ENABLED=0",
    "AERIE_QA_MODE=1",
    "",
  ].join("\n"), "utf8");
  return envFile;
}

async function runAudit() {
  if (!fs.existsSync(electronExe)) throw new Error(`electron_executable_missing:${electronExe}`);
  if (!fs.existsSync(pythonExe)) throw new Error(`python_executable_missing:${pythonExe}`);
  const envFile = prepareRuntimeEnvironment();
  const context = createContext();
  const startedAt = nowIso();
  writeJson(path.join(evidenceRoot, "environment.json"), {
    schemaVersion: AUDIT_SCHEMA_VERSION,
    startedAt,
    browserPath: "playwright-core ElectronApplication",
    browserPluginReason: "The in-app Browser cannot load Electron preload or IPC surfaces.",
    backendPort,
    python: path.basename(pythonExe),
    electron: path.basename(electronExe),
    isolation: {
      userData: "runtime/electron-user-data",
      database: "runtime/data/aerie.db",
      logs: "runtime/logs",
      env: "runtime/qa.env",
      qqDisabled: true,
      proactiveDisabled: true,
      mobileGatewayDisabled: true,
    },
    realModelCallsAuthorizedByThisScript: 0,
  });

  const app = await electron.launch({
    executablePath: electronExe,
    args: [electronRoot],
    cwd: electronRoot,
    timeout: 30000,
    env: {
      ...process.env,
      AERIE_PYTHON_EXE: pythonExe,
      AERIE_BACKEND_PORT: backendPort,
      AERIE_ENV_FILE: envFile,
      AERIE_USER_DATA_DIR: path.join(runtimeRoot, "electron-user-data"),
      AERIE_DATA_DIR: path.join(runtimeRoot, "data"),
      AERIE_DB_PATH: path.join(runtimeRoot, "data", "aerie.db"),
      AERIE_LOG_DIR: path.join(runtimeRoot, "logs"),
      AERIE_PRIMARY_USER_ID: "90010001",
      AERIE_DISABLE_QQ: "1",
      AERIE_MOBILE_GATEWAY_ENABLED: "0",
      AERIE_DISABLE_PROACTIVE: "1",
      AERIE_QA_MODE: "1",
    },
  });
  attachProcessTelemetry(app, context);
  app.on("window", (page) => attachPageTelemetry(page, context));
  for (const page of app.windows()) attachPageTelemetry(page, context);

  let page;
  let catalogResults = [];
  let health = null;
  let fatal = null;
  let pageIdentity = null;
  try {
    page = await waitForMainWindow(app);
    attachPageTelemetry(page, context);
    await page.addInitScript(installAuditHooks);
    await page.reload({ waitUntil: "domcontentloaded", timeout: 30000 });
    await page.waitForSelector("#app .sidebar-tab", { timeout: 10000 });

    const initialLoadingVisible = await page.locator("#status-text.status-text--loading").isVisible().catch(() => false);
    if (initialLoadingVisible) {
      await capturePhase(page, context, "states/loading-live", {
        state: "loading",
        provenance: "live-electron-startup",
        expectedSelector: "#status-text.status-text--loading",
      });
    }

    health = await waitForBackend(page);
    writeJson(path.join(evidenceRoot, "backend-health.json"), health);
    await page.waitForTimeout(250);

    await auditWindowControls(app, page, context);
    await auditStateCoverage(page, context);
    await auditMainTabs(page, context);
    await auditRuntimeSurfaces(page, context);
    await auditAuxiliaryWindows(app, page, context);
    catalogResults = reconcileCatalog(context);
    pageIdentity = {
      title: await page.title().catch(() => ""),
      url: sanitizeUrl(await page.url().catch(() => "")),
    };
  } catch (error) {
    fatal = error && error.stack ? error.stack : String(error);
    writeJson(path.join(evidenceRoot, "fatal.json"), {
      status: "failed",
      error: fatal,
      completedAt: nowIso(),
    });
  } finally {
    await app.close().catch((error) => {
      context.runtimeFailures.push(`electron_close_failed:${String(error.message || error)}`);
    });
  }

  const missingStates = REQUIRED_STATES.filter((state) => !context.states.has(state));
  const failedInteractions = context.interactions.filter((entry) => entry.status === "failed");
  const safeSkipped = context.interactions.filter((entry) => entry.status === "safe-skipped");
  const failedPhases = context.phases.filter((entry) => entry.status === "failed");
  const relevantConsoleErrors = context.console.filter((entry) => (
    entry.type === "pageerror"
    || (entry.type === "error" && entry.source === "renderer")
  ));
  const requestFailures = context.network.filter((entry) => entry.event === "requestfailed");
  const failures = [];
  if (fatal) failures.push("fatal_error");
  if (missingStates.length) failures.push(`missing_states:${missingStates.join(",")}`);
  if (failedInteractions.length) failures.push(`failed_interactions:${failedInteractions.length}`);
  if (failedPhases.length) failures.push(`failed_phases:${failedPhases.length}`);
  if (relevantConsoleErrors.length) failures.push(`renderer_console_errors:${relevantConsoleErrors.length}`);
  if (requestFailures.length) failures.push(`request_failures:${requestFailures.length}`);
  failures.push(...context.runtimeFailures);

  const result = {
    schemaVersion: AUDIT_SCHEMA_VERSION,
    status: failures.length ? "failed" : "passed",
    failures,
    startedAt,
    completedAt: nowIso(),
    pageIdentity,
    backend: health,
    tabs: context.tabs,
    stateCoverage: Object.fromEntries(context.states.entries()),
    missingStates,
    phases: context.phases.map((phase) => ({
      phaseId: phase.phaseId,
      state: phase.state,
      provenance: phase.provenance,
      status: phase.status,
      failures: phase.failures,
    })),
    controls: {
      discovered: context.catalog.size,
      results: catalogResults.length,
      passed: context.interactions.filter((entry) => entry.status === "passed").length,
      failed: failedInteractions.length,
      safeSkipped: safeSkipped.length,
      uncovered: catalogResults.filter((entry) => !entry.result).length,
      safeSkipCategories: Array.from(new Set(safeSkipped.map((entry) => entry.category))).sort(),
    },
    telemetry: {
      consoleEvents: context.console.length,
      relevantConsoleErrors: relevantConsoleErrors.length,
      networkEvents: context.network.length,
      requestFailures: requestFailures.length,
      dialogs: context.dialogs.length,
      auxiliaryWindows: context.windows.length,
    },
    safety: {
      realModelCalls: 0,
      qqMessagesSent: 0,
      qqDisabled: true,
      persistentConfigurationPreserved: true,
      safeSkippedAreNotCountedAsPassed: true,
      notes: context.runtimeNotes,
    },
  };

  writeJson(path.join(evidenceRoot, "control-catalog.json"), catalogResults);
  writeJson(path.join(evidenceRoot, "interactions.json"), context.interactions);
  writeJson(path.join(evidenceRoot, "network.json"), context.network);
  writeJson(path.join(evidenceRoot, "console.json"), context.console);
  writeJson(path.join(evidenceRoot, "dialogs.json"), context.dialogs);
  writeJson(path.join(evidenceRoot, "windows.json"), context.windows);
  writeJson(path.join(evidenceRoot, "state-coverage.json"), Object.fromEntries(context.states.entries()));
  writeJson(path.join(evidenceRoot, "result.json"), result);
  return result;
}

if (require.main === module) {
  runAudit().then((result) => {
    if (result.status !== "passed") process.exitCode = 1;
  }).catch((error) => {
    mkdir(evidenceRoot);
    writeJson(path.join(evidenceRoot, "fatal.json"), {
      status: "failed",
      error: error && error.stack ? error.stack : String(error),
      completedAt: nowIso(),
    });
    process.exitCode = 1;
  });
}

module.exports = {
  AUDIT_SCHEMA_VERSION,
  REQUIRED_STATES,
  classifyDedicatedControl,
  detectOverlaps,
  isAllowedSafeSkip,
  redactText,
  redactValue,
  runAudit,
  safeName,
  sanitizeUrl,
  surfaceFailures,
};
