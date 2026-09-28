"""注册桌面应用的确定性工作流；每一步复用统一操控权限。"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

import yaml

from core.computer_control import ComputerController, ControlResult
from core.paths import data_dir, project_root


def load_apps() -> dict:
    """读取随应用分发的桌面应用注册表。"""
    with (project_root() / "config" / "desktop_apps.yaml").open(encoding="utf-8") as stream:
        return yaml.safe_load(stream) or {}


class DesktopAITask:
    """启动、投递及回读；返回真实步骤结果，不推断任务语义成功。"""

    def __init__(self, controller: ComputerController | None = None, *, apps=None, output_dir=None, analyzer=None):
        if controller is None:
            from core.companion import get_companion
            companion = get_companion()
            controller = getattr(companion, "computer_controller", None)
        if controller is None:
            raise RuntimeError("统一电脑操控器不可用")
        self.controller = controller
        self.apps = load_apps() if apps is None else apps
        self.output_dir = Path(output_dir) if output_dir else data_dir() / "desktop_ai"
        self.analyzer = analyzer
        self._lock = asyncio.Lock()

    def _config(self, app: str) -> dict:
        if app not in self.apps or not app.replace("_", "").isalnum():
            raise ValueError("应用未注册")
        config = self.apps[app]
        if not isinstance(config.get("args", []), list) or not all(isinstance(arg, str) for arg in config.get("args", [])):
            raise ValueError("args 必须是字符串列表")
        if not config.get("window_title") or not 0 < float(config.get("ready_timeout", 15)) <= 120:
            raise ValueError("窗口标题或 ready_timeout 配置无效")
        keys = config.get("send_keys", [])
        if not isinstance(keys, list) or not keys or not all(isinstance(key, str) and key for key in keys):
            raise ValueError("send_keys 必须为非空按键列表")
        return config

    @staticmethod
    def _failure(error: Exception | str) -> dict:
        return {"success": False, "error": str(error)}

    def _window(self, config: dict) -> ControlResult:
        return self.controller.wait_for_window(config["window_title"], int(float(config["ready_timeout"]) * 1000))

    async def launch(self, app: str) -> dict:
        """启动已配置应用并等待唯一窗口。"""
        async with self._lock:
            return await self._launch(app)

    async def _launch(self, app: str) -> dict:
        try:
            config = self._config(app)
            launched = self.controller.app_launch(config.get("exe", ""), config.get("args", []))
            if not launched.success:
                return launched.to_dict()
            window = self._window(config)
            return window.to_dict()
        except Exception as exc:
            return self._failure(exc)

    async def send(self, app: str, text: str) -> dict:
        """聚焦唯一输入框后粘贴并发送，不重试发送。"""
        async with self._lock:
            return self._send(app, text)

    def _send(self, app: str, text: str) -> dict:
        try:
            if not text:
                raise ValueError("输入文本为空")
            config = self._config(app)
            window = self._window(config)
            if not window.success:
                return window.to_dict()
            handle = window.data["windows"][0]["hwnd"]
            for operation in (
                lambda: self.controller.focus_window(handle),
                lambda: self.controller.uia_action("focus_input", {"handle": handle, "input_hint": config.get("input_hint", "")}),
                lambda: self.controller.type_text(text),
                lambda: self.controller.hotkey(config["send_keys"]),
            ):
                result = operation()
                if not result.success:
                    return result.to_dict()
            return {"success": True, "app": app, "sent": True}
        except Exception as exc:
            return self._failure(exc)

    async def read_output(self, app: str, mode: str = "uia") -> dict:
        """读取 UIA 文本或经多模态识别的窗口截图，保存真实产物。"""
        async with self._lock:
            return await self._read(app, mode)

    async def _read(self, app: str, mode: str, *, persist: bool = True) -> dict:
        try:
            if mode not in {"uia", "screenshot"}:
                raise ValueError("mode 仅支持 uia / screenshot")
            config = self._config(app)
            result = self.controller.wait_for_window(config["window_title"], 0)
            if not result.success:
                return result.to_dict()
            window = result.data["windows"][0]
            folder = self.output_dir / app
            stamp = f"{time.time_ns()}_{uuid.uuid4().hex[:8]}"
            artifacts = []
            if mode == "uia":
                result = self.controller.uia_action("read_text", {"handle": window["hwnd"]})
                if not result.success:
                    return result.to_dict()
                text = result.data.get("text", "").strip()
            else:
                result = self.controller.focus_window(window["hwnd"])
                if not result.success:
                    return result.to_dict()
                if window["width"] <= 0 or window["height"] <= 0:
                    raise ValueError("窗口截图区域无效")
                result = self.controller.take_screenshot((window["x"], window["y"], window["x"] + window["width"], window["y"] + window["height"]))
                if not result.success:
                    return result.to_dict()
                source = Path(result.data.get("path", ""))
                if not source.is_file():
                    raise ValueError("截图未生成文件")
                folder.mkdir(parents=True, exist_ok=True)
                image_path = folder / f"{stamp}.png"
                from PIL import Image
                with Image.open(source) as image:
                    image.save(image_path, format="PNG")
                artifacts.append(str(image_path))
                if self.analyzer is None:
                    from core.multimodal_input import ImageAnalyzer
                    self.analyzer = ImageAnalyzer()
                text = await asyncio.wait_for(self.analyzer.describe(str(image_path)), timeout=30)
                if not text.strip():
                    return {"success": False, "error": "视觉回读不可用或未返回文本", "artifacts": artifacts}
            if not text:
                raise ValueError("未读到窗口文本")
            if persist:
                folder.mkdir(parents=True, exist_ok=True)
                text_path = folder / f"{stamp}.txt"
                text_path.write_text(text, encoding="utf-8")
                artifacts.append(str(text_path))
            return {"success": True, "app": app, "mode": mode, "text": text,
                    "artifacts": artifacts, "scope": "visible_window_text"}
        except Exception as exc:
            return self._failure(exc)

    async def run(self, app: str, text: str, mode: str = "uia", timeout: float = 60, quiet_period: float = 2) -> dict:
        """启动→记录基线→投递→等待变化后静默→回读；超时不报告成功。"""
        async with self._lock:
            if mode not in {"uia", "screenshot"} or not 0 < quiet_period < timeout <= 120:
                return self._failure("等待参数或回读模式无效")
            launched = await self._launch(app)
            if not launched.get("success"):
                return launched
            baseline = await self._read(app, mode, persist=False)
            if not baseline.get("success"):
                return baseline
            sent = self._send(app, text)
            if not sent.get("success"):
                return sent
            deadline = time.monotonic() + timeout
            previous = baseline["text"]
            changed = False
            stable_since = time.monotonic()
            while time.monotonic() < deadline:
                await asyncio.sleep(min(0.5, max(0, deadline - time.monotonic())))
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                try:
                    result = await asyncio.wait_for(self._read(app, mode, persist=False), timeout=remaining)
                except TimeoutError:
                    break
                if not result.get("success"):
                    return result
                current = result["text"]
                if current != previous:
                    changed = current != baseline["text"] and current.strip() != text.strip()
                    previous = current
                    stable_since = time.monotonic()
                elif changed and time.monotonic() - stable_since >= quiet_period:
                    folder = self.output_dir / app
                    folder.mkdir(parents=True, exist_ok=True)
                    artifact = folder / f"{time.time_ns()}.txt"
                    artifact.write_text(current, encoding="utf-8")
                    result["artifacts"].append(str(artifact))
                    result["completion"] = "window_quiet"
                    return result
            return self._failure("等待产出变化及静默期超时")
