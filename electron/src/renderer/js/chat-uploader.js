"use strict";
/* Desktop attachment uploader. The server is the only capability authority. */

function attachmentApiUrl(path) {
  const value = String(path || "");
  if (/^https?:\/\//i.test(value)) return value;
  return "http://127.0.0.1:7890" + (value.startsWith("/") ? value : "/" + value);
}

function fillAttachmentTemplate(template, attachmentId) {
  return String(template || "").replace(
    "{attachmentId}",
    encodeURIComponent(String(attachmentId || "")),
  );
}

class ChatUploader {
  constructor(chat) {
    this._chat = chat;
    this._input = document.getElementById("chat-input");
    this._messages = document.getElementById("chat-messages");
    this._capabilities = null;
    this._capabilityError = "";
    this._capabilitiesPromise = this._loadCapabilities();
    this._init();
  }

  async _loadCapabilities() {
    try {
      const response = await this._chat._request({
        method: "GET",
        path: "/api/attachments/capabilities",
      });
      const payload = (response && response.data) || {};
      if (!payload || payload.version !== 1) {
        throw new Error((payload && payload.error) || "附件能力不可用");
      }
      const extensions = new Map();
      for (const capability of payload.capabilities || []) {
        for (const extension of capability.extensions || []) {
          extensions.set(String(extension).toLowerCase(), capability);
        }
      }
      this._capabilities = { ...payload, extensions };
      const input = document.getElementById("chat-file-input");
      if (input) {
        input.accept = Array.from(extensions.keys()).map((ext) => "." + ext).join(",");
      }
      return this._capabilities;
    } catch (error) {
      this._capabilityError = error.message || "附件能力不可用";
      return null;
    }
  }

  _init() {
    const button = document.getElementById("chat-attach-btn");
    if (button) button.addEventListener("click", () => this._openPicker());

    if (!document.getElementById("chat-file-input")) {
      const input = document.createElement("input");
      input.type = "file";
      input.id = "chat-file-input";
      input.multiple = true;
      input.style.display = "none";
      document.body.appendChild(input);
      input.addEventListener("change", (event) => {
        for (const file of event.target.files || []) this._handleFile(file);
        input.value = "";
      });
    }

    if (this._input) {
      this._input.addEventListener("paste", (event) => {
        const items = ((event.clipboardData || window.clipboardData).items || []);
        for (const item of items) {
          if (item.kind !== "file") continue;
          const file = item.getAsFile();
          if (file) this._handleFile(file);
        }
      });
    }

    if (this._messages) {
      this._messages.addEventListener("dragover", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._messages.classList.add("chat-messages--drag");
      });
      this._messages.addEventListener("dragleave", (event) => {
        if (!this._messages.contains(event.relatedTarget)) {
          this._messages.classList.remove("chat-messages--drag");
        }
      });
      this._messages.addEventListener("drop", (event) => {
        event.preventDefault();
        event.stopPropagation();
        this._messages.classList.remove("chat-messages--drag");
        for (const file of event.dataTransfer.files || []) this._handleFile(file);
      });
    }
  }

  async _openPicker() {
    const capabilities = await this._capabilitiesPromise;
    if (!capabilities) {
      alert(this._capabilityError || "附件能力尚未就绪");
      return;
    }
    const input = document.getElementById("chat-file-input");
    if (input) input.click();
  }

  async _handleFile(file) {
    if (!file || !file.name) return;
    const capabilities = await this._capabilitiesPromise;
    if (!capabilities) {
      alert(this._capabilityError || "附件能力尚未就绪");
      return;
    }
    const extension = (file.name.split(".").pop() || "").toLowerCase();
    const capability = capabilities.extensions.get(extension);
    if (!capability) {
      alert("不支持的文件类型: " + (extension || "无扩展名"));
      return;
    }
    if (file.size > Number(capabilities.maxFileBytes || 0)) {
      alert("文件超过服务端允许的大小");
      return;
    }

    const pending = {
      id: "upload_" + Date.now() + "_" + Math.random().toString(16).slice(2),
      name: file.name,
      size: file.size,
      type: capability.category,
      category: capability.category,
      analysisMode: capability.analysisMode,
      state: "queued",
    };
    this._chat._pendingAttachments.push(pending);
    this._chat._renderAttachmentPreviews();

    try {
      let response;
      if (
        window.aerie && window.aerie.api
        && typeof window.aerie.api.upload === "function"
      ) {
        const bytes = Array.from(new Uint8Array(await file.arrayBuffer()));
        response = await window.aerie.api.upload({
          method: "POST",
          path: capabilities.uploadEndpoint,
          filename: file.name,
          contentType: file.type || "application/octet-stream",
          bytes,
        });
      } else {
        const form = new FormData();
        form.append("file", file);
        const fallback = await fetch(attachmentApiUrl(capabilities.uploadEndpoint), {
          method: "POST",
          body: form,
        });
        response = { status: fallback.status, data: await fallback.json() };
      }
      const payload = (response && response.data) || {};
      if (!response || response.status < 200 || response.status >= 300) {
        throw new Error(payload.error || "上传失败");
      }
      const record = payload.attachment || payload;
      Object.assign(pending, record, {
        id: record.attachmentId || record.id,
        attachmentId: record.attachmentId || record.id,
        state: record.state || "queued",
      });
      this._chat._renderAttachmentPreviews();
      if (["queued", "processing"].includes(pending.state)) {
        await this._pollUntilTerminal(pending);
      }
    } catch (error) {
      pending.state = "failed";
      pending.error = { code: "upload_failed", message: error.message || "上传失败" };
      this._chat._renderAttachmentPreviews();
    }
  }

  async _pollUntilTerminal(pending) {
    const terminal = new Set(["ready", "failed", "quarantined", "unsupported"]);
    const template = this._capabilities.statusEndpointTemplate;
    for (let attempt = 0; attempt < 160 && !terminal.has(pending.state); attempt += 1) {
      await new Promise((resolve) => setTimeout(resolve, 750));
      const response = await this._chat._request({
        method: "GET",
        path: fillAttachmentTemplate(template, pending.attachmentId),
      });
      const payload = (response && response.data) || {};
      if (!payload.attachment && !payload.attachmentId && !payload.id) {
        throw new Error(payload.error || "附件状态查询失败");
      }
      Object.assign(pending, payload.attachment || payload);
      this._chat._renderAttachmentPreviews();
    }
    if (!terminal.has(pending.state)) {
      pending.state = "failed";
      pending.error = { code: "processing_timeout", message: "附件解析超时" };
      this._chat._renderAttachmentPreviews();
    }
  }

  remove(attachmentId) {
    const id = String(attachmentId || "");
    this._chat._pendingAttachments = this._chat._pendingAttachments.filter(
      (attachment) => String(attachment.attachmentId || attachment.id) !== id,
    );
    this._chat._renderAttachmentPreviews();
    if (id && this._capabilities && this._capabilities.removeEndpointTemplate) {
      const endpoint = fillAttachmentTemplate(
        this._capabilities.removeEndpointTemplate,
        id,
      );
      this._chat._request({ method: "DELETE", path: endpoint }).catch(() => {});
    }
  }

  async retry(attachmentId) {
    const pending = this._chat._pendingAttachments.find(
      (attachment) => String(attachment.attachmentId || attachment.id) === String(attachmentId),
    );
    if (!pending || !pending.attachmentId) return;
    try {
      pending.state = "queued";
      pending.error = null;
      this._chat._renderAttachmentPreviews();
      const endpoint = fillAttachmentTemplate(
        this._capabilities.retryEndpointTemplate,
        pending.attachmentId,
      );
      const response = await this._chat._request({ method: "POST", path: endpoint });
      const payload = (response && response.data) || {};
      if (!payload.attachment && !payload.attachmentId && !payload.id) {
        throw new Error(payload.error || "重试失败");
      }
      Object.assign(pending, payload.attachment || payload);
      this._chat._renderAttachmentPreviews();
      if (["queued", "processing"].includes(pending.state)) {
        await this._pollUntilTerminal(pending);
      }
    } catch (error) {
      pending.state = "failed";
      pending.error = { code: "retry_failed", message: error.message || "重试失败" };
      this._chat._renderAttachmentPreviews();
    }
  }
}

window.ChatUploader = ChatUploader;
