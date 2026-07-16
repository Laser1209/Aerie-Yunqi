"use strict";
/* Chat uploader: drag-and-drop / paste / file-picker */

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const ALLOWED_EXT = new Set([
  // images
  "jpg","jpeg","png","gif","webp",
  // docs
  "pdf","doc","docx","xls","xlsx","ppt","pptx","txt",
  // archives
  "zip","rar","7z",
  // audio
  "mp3","wav","m4a","opus",
  // video
  "mp4","mov","avi",
  // executables
  "exe","apk",
]);

function classifyType(ext) {
  ext = ext.toLowerCase();
  if (["jpg","jpeg","png","gif","webp"].includes(ext)) return "image";
  if (["mp3","wav","m4a","opus"].includes(ext)) return "audio";
  if (["mp4","mov","avi"].includes(ext)) return "video";
  return "file";
}

class ChatUploader {
  constructor(chat) {
    this._chat = chat;
    this._input = document.getElementById("chat-input");
    this._messages = document.getElementById("chat-messages");
    this._init();
  }

  _init() {
    // Add attach button to input area (Phase 7: paperclip SVG icon)
    const inputArea = document.querySelector(".chat-input-area");
    if (inputArea && !document.getElementById("chat-attach-btn")) {
      const toolbar = document.createElement("div");
      toolbar.className = "chat-input-toolbar";
      toolbar.innerHTML = `<button class="chat-input-toolbar__btn" id="chat-attach-btn" title="发送附件"><svg class="icon icon--18" aria-hidden="true"><use href="#icon-ui-attach"/></svg></button>`;
      inputArea.parentNode.insertBefore(toolbar, inputArea);

      const btn = document.getElementById("chat-attach-btn");
      btn.addEventListener("click", () => this._openPicker());
    }

    // Hidden file input
    if (!document.getElementById("chat-file-input")) {
      const fi = document.createElement("input");
      fi.type = "file";
      fi.id = "chat-file-input";
      fi.multiple = true;
      fi.style.display = "none";
      document.body.appendChild(fi);
      fi.addEventListener("change", (e) => {
        for (const f of e.target.files) this._handleFile(f);
        fi.value = "";
      });
    }

    // Paste handler on input
    if (this._input) {
      this._input.addEventListener("paste", (e) => {
        const items = (e.clipboardData || window.clipboardData).items || [];
        for (const it of items) {
          if (it.kind === "file") {
            const file = it.getAsFile();
            if (file) this._handleFile(file);
          }
        }
      });
    }

    // Drag-and-drop on messages container
    if (this._messages) {
      this._messages.addEventListener("dragover", (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._messages.classList.add("chat-messages--drag");
      });
      this._messages.addEventListener("dragleave", (e) => {
        if (!this._messages.contains(e.relatedTarget)) {
          this._messages.classList.remove("chat-messages--drag");
        }
      });
      this._messages.addEventListener("drop", (e) => {
        e.preventDefault();
        e.stopPropagation();
        this._messages.classList.remove("chat-messages--drag");
        for (const f of e.dataTransfer.files) this._handleFile(f);
      });
    }
  }

  _openPicker() {
    const fi = document.getElementById("chat-file-input");
    if (fi) fi.click();
  }

  async _handleFile(file) {
    if (!file || !file.name) return;
    const ext = (file.name.split(".").pop() || "").toLowerCase();
    if (!ALLOWED_EXT.has(ext)) {
      alert("不支持的文件类型: " + ext);
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      alert("文件太大（>20MB）");
      return;
    }

    // Upload
    try {
      const form = new FormData();
      form.append("file", file);
      let respData;
      if (window.aerie) {
        // Use IPC: send multipart via fetch (preload exposes only generic)
        const r = await fetch("http://127.0.0.1:7890/api/upload", { method: "POST", body: form });
        respData = await r.json();
      } else {
        const r = await fetch("http://127.0.0.1:7890/api/upload", { method: "POST", body: form });
        respData = await r.json();
      }
      if (respData.error) {
        alert("上传失败: " + respData.error);
        return;
      }
      // Append to pending attachments
      this._chat._pendingAttachments.push({
        name: file.name,
        size: file.size,
        type: classifyType(ext),
        url: respData.url.replace(/^\//, ""),   // strip leading slash
        content_type: file.type || "",
      });
      this._chat._renderAttachmentPreviews();
      if (this._input) this._input.focus();
    } catch (err) {
      alert("上传失败: " + err.message);
    }
  }
}

window.ChatUploader = ChatUploader;