"use strict";
/* Chat voice input: MediaRecorder + backend ASR API.
 *
 * Flow:
 *   click mic → start recording → auto-stop after 1.5s silence → upload for transcription
 *   OR click mic again to manually stop → upload for transcription
 *   Result fills #chat-input.value
 *
 * Uses AudioContext AnalyserNode for VAD (Voice Activity Detection):
 *   - monitors RMS volume in real-time
 *   - auto-stops after 2s of continuous silence (> 0.005 RMS threshold)
 *   - max recording 30s to prevent runaway
 */

const VAD_SILENCE_MS = 2000;
const VAD_SILENCE_THRESHOLD = 0.001;
const VAD_CHECK_INTERVAL = 100;
const MAX_RECORDING_MS = 30000;

class ChatVoice {
  constructor(chat) {
    this._chat = chat;
    this._apiBase = window.__API_BASE__ || "http://127.0.0.1:7890";
    this._mediaStream = null;
    this._mediaRecorder = null;
    this._chunks = [];
    this._recording = false;
    this._startTime = 0;
    this._audioCtx = null;
    this._analyser = null;
    this._vadTimer = null;
    this._maxTimer = null;
    this._silenceStart = 0;
    this._hasSpeech = false;
    this._rmsData = null;
    this._manualStop = false;
    console.log("[ChatVoice] Constructor called, API base:", this._apiBase);
    this._init();
  }

  _init() {
    const btn = document.getElementById("chat-mic-btn");
    if (!btn) {
      console.warn("[ChatVoice] _init: chat-mic-btn not found");
      return;
    }
    console.log("[ChatVoice] _init: chat-mic-btn found");

    const supported = !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia &&
                         window.MediaRecorder && (window.AudioContext || window.webkitAudioContext));
    console.log("[ChatVoice] _init: supported=", supported, 
                "mediaDevices=", !!navigator.mediaDevices, 
                "getUserMedia=", !!navigator.mediaDevices?.getUserMedia,
                "MediaRecorder=", !!window.MediaRecorder,
                "AudioContext=", !!(window.AudioContext || window.webkitAudioContext));

    if (!supported) {
      console.log("[ChatVoice] _init: Not supported, adding error handler");
      btn.addEventListener("click", () => this._showError("浏览器不支持录音 / Recording not supported"));
      btn.setAttribute("title", "浏览器不支持 / Not supported");
      return;
    }

    console.log("[ChatVoice] _init: Adding click listener to btn");
    btn.addEventListener("click", () => this._toggle());
    this._checkStatus();
  }

  async _checkStatus() {
    try {
      const result = await window.aerie.api.request({
        path: "/api/audio/status",
        method: "GET",
      });
      if (result && result.status === 200 && result.data) {
        const data = result.data;
        const btn = document.getElementById("chat-mic-btn");
        if (btn) {
          if (data.has_local) {
            btn.setAttribute("title", "语音输入（本地识别）/ Voice Input (Local)");
          } else if (data.available) {
            btn.setAttribute("title", "语音输入 / Voice Input");
          } else {
            btn.setAttribute("title", "请先在设置中配置ASR服务 / Configure ASR in settings");
          }
        }
      }
    } catch (_) {}
  }

  async _toggle() {
    console.log("[ChatVoice] _toggle called, recording=", this._recording);
    if (this._recording) {
      this._manualStop = true;
      this._stop();
      return;
    }
    await this._start();
  }

  async _start() {
    console.log("[ChatVoice] _start called");
    this._chunks = [];
    this._manualStop = false;

    try {
      const audioConstraints = {
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          channelCount: 1,
          sampleRate: 16000,
        }
      };
      this._mediaStream = await navigator.mediaDevices.getUserMedia(audioConstraints);
      console.log("[ChatVoice] getUserMedia success: tracks=", this._mediaStream.getTracks().length, 
                  "active=", this._mediaStream.active);
      const audioTracks = this._mediaStream.getAudioTracks();
      if (audioTracks.length > 0) {
        console.log("[ChatVoice] Audio track: label=", audioTracks[0].label, 
                    "enabled=", audioTracks[0].enabled, 
                    "muted=", audioTracks[0].muted);
      }
    } catch (err) {
      console.warn("[ChatVoice] getUserMedia failed:", err);
      if (err.name === "NotAllowedError" || err.name === "PermissionDeniedError") {
        this._showError("麦克风权限被拒绝\n请检查系统设置 / Microphone permission denied");
      } else if (err.name === "NotFoundError" || err.name === "DevicesNotFoundError") {
        this._showError("未找到麦克风 / Microphone not found");
      } else {
        this._showError("无法启动录音 / Failed to start recording");
      }
      return;
    }

    try {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      this._audioCtx = new AudioCtx();
      await this._audioCtx.resume();
      console.log("[ChatVoice] AudioContext created: state=", this._audioCtx.state, 
                  "sampleRate=", this._audioCtx.sampleRate);
      const source = this._audioCtx.createMediaStreamSource(this._mediaStream);
      this._analyser = this._audioCtx.createAnalyser();
      this._analyser.fftSize = 256;
      this._analyser.smoothingTimeConstant = 0.3;
      source.connect(this._analyser);
      this._rmsData = new Float32Array(this._analyser.fftSize);
      console.log("[ChatVoice] Analyser setup: fftSize=", this._analyser.fftSize, 
                  "bufferLength=", this._rmsData.length);
      this._hasSpeech = false;
      this._silenceStart = 0;

      let mime = "audio/webm";
      if (MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
        mime = "audio/webm;codecs=opus";
      } else if (MediaRecorder.isTypeSupported("audio/webm")) {
        mime = "audio/webm";
      }

      this._mediaRecorder = new MediaRecorder(this._mediaStream, { mimeType: mime });

      this._mediaRecorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) {
          this._chunks.push(e.data);
          console.log("[ChatVoice] Chunk received: size=", e.data.size, "totalChunks=", this._chunks.length);
        }
      };

      this._mediaRecorder.onstop = () => {
        this._onRecordingStopped();
      };

      this._mediaRecorder.onerror = (e) => {
        console.warn("[ChatVoice] recorder error:", e);
        this._showError("录音出错 / Recording error");
        this._cleanup();
      };

      this._mediaRecorder.start(100);
      this._recording = true;
      this._startTime = Date.now();

      const btn = document.getElementById("chat-mic-btn");
      if (btn) {
        btn.classList.add("is-recording");
        btn.setAttribute("aria-pressed", "true");
      }
      const status = document.getElementById("chat-mic-status");
      if (status) status.hidden = false;
      this._setStatus("正在听… / Listening…", "listening");

      this._startVadLoop();
      this._maxTimer = setTimeout(() => {
        if (this._recording) this._stop();
      }, MAX_RECORDING_MS);

    } catch (err) {
      console.warn("[ChatVoice] start failed:", err);
      this._showError("启动录音失败 / Failed to start recording");
      this._cleanup();
    }
  }

  _startVadLoop() {
    const check = () => {
      if (!this._recording || !this._analyser) return;

      this._analyser.getFloatTimeDomainData(this._rmsData);
      let sumSq = 0;
      for (let i = 0; i < this._rmsData.length; i++) {
        sumSq += this._rmsData[i] * this._rmsData[i];
      }
      const rms = Math.sqrt(sumSq / this._rmsData.length);
      console.debug("[ChatVoice] VAD: RMS=%f, threshold=%f, hasSpeech=%s", 
                    rms, VAD_SILENCE_THRESHOLD, this._hasSpeech);

      if (rms >= VAD_SILENCE_THRESHOLD) {
        if (!this._hasSpeech) {
          this._hasSpeech = true;
          console.log("[ChatVoice] VAD: Speech detected, RMS=%f", rms);
        }
        this._silenceStart = 0;
        this._setStatus("正在听… / Hearing…", "audio");
      } else {
        if (this._hasSpeech) {
          if (this._silenceStart === 0) {
            this._silenceStart = Date.now();
            console.log("[ChatVoice] VAD: Silence started");
          }
          const silentMs = Date.now() - this._silenceStart;
          if (silentMs >= VAD_SILENCE_MS) {
            console.log("[ChatVoice] VAD: Auto-stop after %dms silence", silentMs);
            this._stop();
            return;
          }
          const remain = Math.max(0, Math.ceil((VAD_SILENCE_MS - silentMs) / 1000));
          this._setStatus("等待中… " + remain + "s / Waiting…", "listening");
        }
      }

      this._vadTimer = setTimeout(check, VAD_CHECK_INTERVAL);
    };
    this._vadTimer = setTimeout(check, VAD_CHECK_INTERVAL);
  }

  _stop() {
    if (!this._recording || !this._mediaRecorder) {
      this._cleanup();
      return;
    }
    if (this._vadTimer) clearTimeout(this._vadTimer);
    if (this._maxTimer) clearTimeout(this._maxTimer);
    try {
      this._mediaRecorder.stop();
    } catch (_) {
      this._cleanup();
    }
  }

  async _onRecordingStopped() {
    const duration = (Date.now() - this._startTime) / 1000;
    console.log("[ChatVoice] Recording stopped: duration=%fs, chunks=%d, hasSpeech=%s, manual=%s", 
                duration, this._chunks.length, this._hasSpeech, this._manualStop);

    if (!this._hasSpeech && !this._manualStop) {
      console.warn("[ChatVoice] No speech detected during recording");
      this._showError("未检测到语音\n请靠近麦克风说话 / No speech detected");
      this._cleanup();
      return;
    }

    if (!this._chunks.length || duration < 0.3) {
      console.warn("[ChatVoice] Recording too short: duration=%fs", duration);
      this._showError("录音太短 / Recording too short");
      this._cleanup();
      return;
    }

    this._setStatus("识别中… / Transcribing…", "speech");

    try {
      const blob = new Blob(this._chunks, { type: this._mediaRecorder.mimeType || "audio/webm" });
      console.log("[ChatVoice] Uploading audio: size=%d bytes, type=%s", blob.size, blob.type);

      const arrayBuffer = await blob.arrayBuffer();
      const bytes = Array.from(new Uint8Array(arrayBuffer));

      const path = "/api/audio/transcribe?language=" + encodeURIComponent(this._detectLanguage());
      console.log("[ChatVoice] Upload via IPC:", path);

      const result = await window.aerie.api.upload({
        path: path,
        filename: "recording.webm",
        contentType: blob.type || "audio/webm",
        bytes: bytes,
        method: "POST",
      });
      console.log("[ChatVoice] Upload result:", JSON.stringify(result));

      if (!result || result.status === 0 || result.status >= 400) {
        throw new Error(result && result.data && result.data.error || "Upload failed");
      }

      const data = result.data;
      console.log("[ChatVoice] API result:", JSON.stringify(data));

      if (data.status !== "ok") {
        throw new Error(data.error || "Transcription failed");
      }

      const text = (data.text || "").trim();
      console.log("[ChatVoice] Transcribed text: '%s'", text || "(empty)");

      if (!text) {
        this._showError("未识别到语音内容 / No speech detected");
        this._cleanup();
        return;
      }

      const input = document.getElementById("chat-input");
      if (input) {
        input.value = text;
        input.focus();
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }

      const status = document.getElementById("chat-mic-status");
      if (status) {
        const textEl = status.querySelector(".chat-mic-status__text");
        if (textEl) textEl.textContent = "已识别 / Done";
        status.classList.add("phase-interim");
        setTimeout(() => {
          status.classList.remove("phase-interim");
          status.hidden = true;
        }, 1500);
      }

      this._cleanup();

    } catch (err) {
      console.error("[ChatVoice] Transcription failed:", err);
      this._showError("识别失败：" + (err.message || err) + " / Transcription failed");
      this._cleanup();
    }
  }

  _detectLanguage() {
    const lang = navigator.language || "zh-CN";
    if (lang.toLowerCase().startsWith("zh")) return "zh";
    if (lang.toLowerCase().startsWith("en")) return "en";
    return "auto";
  }

  _cleanup() {
    this._recording = false;
    this._hasSpeech = false;
    this._silenceStart = 0;

    if (this._vadTimer) {
      clearTimeout(this._vadTimer);
      this._vadTimer = null;
    }
    if (this._maxTimer) {
      clearTimeout(this._maxTimer);
      this._maxTimer = null;
    }

    if (this._audioCtx) {
      this._audioCtx.close().catch(() => {});
      this._audioCtx = null;
    }
    this._analyser = null;
    this._rmsData = null;

    if (this._mediaStream) {
      this._mediaStream.getTracks().forEach(t => t.stop());
      this._mediaStream = null;
    }
    this._mediaRecorder = null;
    this._chunks = [];

    const btn = document.getElementById("chat-mic-btn");
    if (btn) {
      btn.classList.remove("is-recording");
      btn.setAttribute("aria-pressed", "false");
    }
    const status = document.getElementById("chat-mic-status");
    if (status && !status.classList.contains("phase-error") && !status.classList.contains("phase-interim")) {
      status.hidden = true;
    }
  }

  _setStatus(text, phase) {
    const status = document.getElementById("chat-mic-status");
    if (!status) return;
    const textEl = status.querySelector(".chat-mic-status__text");
    if (textEl) textEl.textContent = text;
    status.classList.remove("phase-starting", "phase-listening", "phase-audio", "phase-sound", "phase-speech", "phase-interim", "phase-error");
    if (phase) status.classList.add("phase-" + phase);
  }

  _showError(msg) {
    const status = document.getElementById("chat-mic-status");
    if (!status) return;
    const textEl = status.querySelector(".chat-mic-status__text");
    const netEl = status.querySelector(".chat-mic-status__net");
    if (textEl) textEl.textContent = msg;
    if (netEl) netEl.textContent = "点击重试 / Click to retry";
    status.classList.remove("phase-starting", "phase-listening", "phase-audio", "phase-sound", "phase-speech", "phase-interim");
    status.classList.add("phase-error");
    status.hidden = false;

    const btn = document.getElementById("chat-mic-btn");
    if (btn) {
      btn.classList.remove("is-recording");
      btn.setAttribute("aria-pressed", "false");
    }

    setTimeout(() => {
      if (!this._recording) {
        status.classList.remove("phase-error");
        status.hidden = true;
        if (textEl) textEl.textContent = "正在听… / Listening…";
        if (netEl) netEl.textContent = "需联网 / Online required";
      }
    }, 4000);
  }
}

window.ChatVoice = ChatVoice;

window.testVoiceInput = async function() {
  console.log("[Test] Starting voice input test...");
  try {
    const audioConstraints = {
      audio: {
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
        channelCount: 1,
        sampleRate: 16000,
      }
    };
    const stream = await navigator.mediaDevices.getUserMedia(audioConstraints);
    console.log("[Test] getUserMedia success:", stream.getTracks().length, "tracks");
    
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    await audioCtx.resume();
    console.log("[Test] AudioContext state:", audioCtx.state);
    
    const recorder = new MediaRecorder(stream);
    const chunks = [];
    recorder.ondataavailable = (e) => {
      if (e.data && e.data.size > 0) {
        chunks.push(e.data);
        console.log("[Test] Chunk received:", e.data.size, "bytes");
      }
    };
    
    recorder.onstop = async () => {
      console.log("[Test] Recording stopped, total chunks:", chunks.length);
      if (chunks.length > 0) {
        const blob = new Blob(chunks, { type: recorder.mimeType });
        console.log("[Test] Blob size:", blob.size, "bytes");
        
        try {
          if (window.aerie && window.aerie.api && window.aerie.api.upload) {
            console.log("[Test] Uploading via IPC...");
            const arrayBuffer = await blob.arrayBuffer();
            const bytes = Array.from(new Uint8Array(arrayBuffer));
            const result = await window.aerie.api.upload({
              path: "/api/audio/transcribe?language=zh",
              filename: "test.webm",
              contentType: blob.type,
              bytes: bytes,
              method: "POST",
            });
            console.log("[Test] Upload result:", JSON.stringify(result));
          } else {
            console.error("[Test] window.aerie.api.upload is not available");
          }
        } catch (err) {
          console.error("[Test] Upload failed:", err);
        }
      }
      
      stream.getTracks().forEach(t => t.stop());
      audioCtx.close();
    };
    
    recorder.start(100);
    console.log("[Test] Recording started, will stop in 3 seconds...");
    
    setTimeout(() => {
      recorder.stop();
    }, 3000);
    
  } catch (err) {
    console.error("[Test] Error:", err);
  }
};
