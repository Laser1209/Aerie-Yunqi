"""P1-B.4 办公最小闭环（剪贴板翻译、截图问图、时间天气状态）.

TDD 契约：
- 剪贴板翻译：读取 clipboard_candidate 文本，调用注入的翻译 handler，返回结果
- 剪贴板翻译安全边界：clipboard 为空或包含敏感内容时不触发翻译
- 截图问图：复用 ImageWorkflow.understand_image 返回 ImageObservation
- 时间天气状态：返回结构化时间/天气/网络/电池
- 时间天气状态不包含敏感路径
- 办公模式下可用，陪伴模式下不可用
- 所有闭环操作写入审计日志
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from PIL import Image

from core.image_service import (
    ImageSafetyPolicy,
    ImageVisionResult,
    ImageWorkflow,
    JsonImageWorkflowStore,
)
from core.office_loops import (
    OfficeLoopError,
    OfficeLoops,
    TranslationProvider,
)
from core.office_mode import OfficeMode, OfficeModeManager
from core.action_registry import ActionRegistry


# ── helpers ───────────────────────────────────────────────────

def _png_bytes(size=(6, 4), color=(90, 140, 210)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class FakeTranslationProvider(TranslationProvider):
    provider_id = "fake_translation"
    model = "fake-translate"

    def __init__(self, result: str = "FAKE_TRANSLATION") -> None:
        self._result = result
        self.calls: list[dict] = []

    def translate(self, *, text: str, target_lang: str, source_lang: str, request_id: str, owner_id: str) -> dict:
        self.calls.append({
            "text": text,
            "target_lang": target_lang,
            "source_lang": source_lang,
            "request_id": request_id,
            "owner_id": owner_id,
        })
        return {
            "status": "ok",
            "provider_id": self.provider_id,
            "model": self.model,
            "original_text": text,
            "translated_text": self._result,
            "source_lang": source_lang,
            "target_lang": target_lang,
        }


class FakeImageVisionProvider:
    provider_id = "fake_vision"
    model = "fake-vision"

    def __init__(self, answer: str = "a screenshot showing code"):
        self.answer = answer
        self.calls: list[dict] = []

    def analyze(self, *, image_path: str, question: str, request_id: str, owner_id: str):
        self.calls.append({
            "image_path": image_path,
            "question": question,
            "request_id": request_id,
            "owner_id": owner_id,
        })
        return ImageVisionResult(
            status="ok",
            answer=self.answer,
            provider_id=self.provider_id,
            model=self.model,
            metadata={"scene": {"summary": self.answer}},
        )


@pytest.fixture()
def uploads(tmp_path: Path) -> Path:
    base = tmp_path / "uploads"
    base.mkdir(parents=True, exist_ok=True)
    return base


@pytest.fixture()
def audit_log(tmp_path: Path) -> list[dict]:
    return []


@pytest.fixture()
def loops(uploads: Path, audit_log: list[dict]) -> OfficeLoops:
    mode_manager = OfficeModeManager()
    mode_manager.set_mode(OfficeMode.OFFICE)
    vision = FakeImageVisionProvider()
    workflow = ImageWorkflow(
        upload_base=uploads,
        feature_enabled=True,
        vision_provider=vision,
        safety_policy=ImageSafetyPolicy(),
        store=JsonImageWorkflowStore(uploads / ".image_assets" / "image_workflows.json"),
        id_factory=lambda prefix: f"{prefix}_fixed",
        clock=lambda: "2026-07-28T09:00:00+00:00",
    )
    translator = FakeTranslationProvider()
    loops = OfficeLoops(
        mode_manager=mode_manager,
        action_registry=ActionRegistry(),
        image_workflow=workflow,
        translation_provider=translator,
        weather_provider=lambda: {"city": "上海", "temp": "26", "desc": "多云", "humidity": "60", "wind": "微风"},
        system_probe=lambda: {"network": "online", "battery_percent": 87, "power_plugged": True},
        audit_sink=audit_log.append,
    )
    loops._vision_provider = vision  # type: ignore[attr-defined]
    loops._translator = translator  # type: ignore[attr-defined]
    return loops


# ── clipboard translation ─────────────────────────────────────

class TestClipboardTranslation:
    def test_translates_when_clipboard_has_text(self, loops: OfficeLoops, audit_log):
        result = loops.translate_clipboard(
            clipboard_candidate="Hello, world!",
            target_lang="zh",
            idempotency_key="clip-1",
        )
        assert result["status"] == "ok"
        assert result["translated_text"] == "FAKE_TRANSLATION"
        assert result["original_text"] == "Hello, world!"
        assert len(loops._translator.calls) == 1
        # audit log written
        assert any(entry["operation"] == "clipboard_translate" for entry in audit_log)

    def test_skips_when_clipboard_empty(self, loops: OfficeLoops, audit_log):
        result = loops.translate_clipboard(
            clipboard_candidate="   ",
            target_lang="zh",
            idempotency_key="clip-empty",
        )
        assert result["status"] == "skipped"
        assert result["reason"] == "empty_clipboard"
        assert len(loops._translator.calls) == 0
        # no translation attempted; audit should mark skip
        assert any(entry["operation"] == "clipboard_translate" for entry in audit_log)

    def test_rejects_sensitive_content(self, loops: OfficeLoops, audit_log):
        result = loops.translate_clipboard(
            clipboard_candidate="my api key is sk-abcdef123456",
            target_lang="zh",
            idempotency_key="clip-secret",
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "sensitive_content"
        assert len(loops._translator.calls) == 0

    def test_rejects_long_content(self, loops: OfficeLoops):
        long_text = "x" * 5000
        result = loops.translate_clipboard(
            clipboard_candidate=long_text,
            target_lang="zh",
            idempotency_key="clip-long",
        )
        assert result["status"] == "rejected"

    def test_unavailable_in_companion_mode(self, loops: OfficeLoops):
        loops._mode_manager.set_mode(OfficeMode.CHAT)
        with pytest.raises(OfficeLoopError) as exc_info:
            loops.translate_clipboard(
                clipboard_candidate="Hello",
                target_lang="zh",
                idempotency_key="clip-chat",
            )
        assert exc_info.value.code == "mode_denied"


# ── screenshot inquiry ────────────────────────────────────────

class TestScreenshotInquiry:
    def test_inquire_screenshot_returns_observation(self, loops: OfficeLoops, uploads: Path, audit_log):
        shot = uploads / "screenshot.png"
        shot.write_bytes(_png_bytes())

        result = loops.inquire_screenshot(
            screenshot_path=str(shot),
            question="图里是什么？",
            idempotency_key="shot-1",
        )
        assert result["status"] == "completed"
        assert "observation" in result
        obs = result["observation"]
        assert "scene" in obs
        assert obs["source"]["image_url"].startswith("/uploads/")
        assert len(loops._vision_provider.calls) == 1
        assert any(entry["operation"] == "screenshot_inquire" for entry in audit_log)

    def test_missing_screenshot_path_rejected(self, loops: OfficeLoops):
        result = loops.inquire_screenshot(
            screenshot_path="",
            question="?",
            idempotency_key="shot-missing",
        )
        assert result["status"] == "rejected"
        assert result["reason"] == "missing_path"

    def test_path_traversal_rejected(self, loops: OfficeLoops):
        result = loops.inquire_screenshot(
            screenshot_path="../../../etc/passwd",
            question="?",
            idempotency_key="shot-traverse",
        )
        assert result["status"] in ("rejected", "failed")

    def test_unavailable_in_companion_mode(self, loops: OfficeLoops, uploads: Path):
        loops._mode_manager.set_mode(OfficeMode.CHAT)
        shot = uploads / "screenshot.png"
        shot.write_bytes(_png_bytes())
        with pytest.raises(OfficeLoopError) as exc_info:
            loops.inquire_screenshot(
                screenshot_path=str(shot),
                question="?",
                idempotency_key="shot-chat",
            )
        assert exc_info.value.code == "mode_denied"


# ── status snapshot ───────────────────────────────────────────

class TestStatusSnapshot:
    def test_returns_structured_status(self, loops: OfficeLoops, audit_log):
        snap = loops.get_status_snapshot()
        assert snap["status"] == "ok"
        assert "time" in snap
        assert "weather" in snap
        assert "network" in snap
        assert "battery" in snap
        # weather data comes from fake provider
        assert snap["weather"]["city"] == "上海"
        assert snap["battery"]["percent"] == 87
        assert any(entry["operation"] == "status_snapshot" for entry in audit_log)

    def test_no_sensitive_paths_in_snapshot(self, loops: OfficeLoops):
        snap = loops.get_status_snapshot()
        raw = json.dumps(snap, ensure_ascii=False)
        for forbidden in ("/home/", "/Users/", "C:\\\\Users\\\\", "~\\\"", "secret", "api_key", "password"):
            assert forbidden not in raw
        # office dir path should NOT leak
        assert "AerieOffice" not in raw

    def test_audit_log_written(self, loops: OfficeLoops, audit_log):
        loops.get_status_snapshot()
        assert any(
            entry["operation"] == "status_snapshot"
            for entry in audit_log
        )

    def test_unavailable_in_companion_mode(self, loops: OfficeLoops):
        loops._mode_manager.set_mode(OfficeMode.CHAT)
        with pytest.raises(OfficeLoopError) as exc_info:
            loops.get_status_snapshot()
        assert exc_info.value.code == "mode_denied"


# ── audit log coverage ────────────────────────────────────────

class TestAuditLogging:
    def test_audit_entries_have_required_fields(self, loops: OfficeLoops, uploads: Path):
        loops.translate_clipboard(
            clipboard_candidate="hello",
            target_lang="zh",
            idempotency_key="audit-1",
        )
        shot = uploads / "audit.png"
        shot.write_bytes(_png_bytes())
        loops.inquire_screenshot(screenshot_path=str(shot), question="?", idempotency_key="audit-2")
        loops.get_status_snapshot()
        # every entry has operation + timestamp + status + request_id
        for entry in loops.audit_log:
            assert "operation" in entry
            assert "timestamp" in entry
            assert "status" in entry
            assert "request_id" in entry
