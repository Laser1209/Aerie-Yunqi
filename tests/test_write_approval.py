"""1.2b 越界写入授权桥（core/write_approval.py）单元测试。"""
import asyncio

import pytest

from core import write_approval


class _Registry:
    """记录被执行的工具调用，返回可配置结果。"""

    def __init__(self, result=None):
        self.calls = []
        self._result = {"success": True} if result is None else result

    async def execute(self, name, args):
        self.calls.append((name, args))
        return self._result


@pytest.fixture(autouse=True)
def _clean_pending():
    write_approval.clear()
    yield
    write_approval.clear()


def test_resolve_unknown_id_returns_false():
    assert write_approval.resolve("wappr_missing", True) is False


def test_pending_lists_and_resolve_clears():
    async def go():
        req_id = write_approval.request(r"D:\x\y.txt", "file_write")
        assert [item["id"] for item in write_approval.pending()] == [req_id]
        assert write_approval.resolve(req_id, False) is True
        assert write_approval.pending() == []

    asyncio.run(go())


def test_wait_timeout_is_treated_as_reject():
    async def go():
        req_id = write_approval.request(r"D:\x\y.txt", "file_write")
        assert await write_approval.wait(req_id, timeout=0.05) is False

    asyncio.run(go())


def test_wait_returns_decision():
    async def go():
        req_id = write_approval.request(r"D:\x\y.txt", "file_write")

        async def approve():
            await asyncio.sleep(0.01)
            write_approval.resolve(req_id, True)

        task = asyncio.create_task(approve())
        assert await write_approval.wait(req_id, timeout=1.0) is True
        await task

    asyncio.run(go())


@pytest.mark.asyncio
async def test_flag_disabled_keeps_original_result(monkeypatch):
    monkeypatch.setenv("AERIE_FEATURE_WRITE_APPROVAL_V1", "false")
    registry = _Registry()
    result = {"success": False, "reason": "outside_workspace_roots", "error": "blocked"}

    out, ok = await write_approval.maybe_retry_after_block(
        registry, "file_write", {"destination": r"D:\a\b.txt"}, result, False
    )

    assert out is result
    assert ok is False
    assert registry.calls == []


@pytest.mark.asyncio
async def test_other_reason_is_ignored(monkeypatch):
    monkeypatch.setenv("AERIE_FEATURE_WRITE_APPROVAL_V1", "true")
    registry = _Registry()
    result = {"success": False, "reason": "blocked_by_blacklist", "error": "blocked"}

    out, ok = await write_approval.maybe_retry_after_block(
        registry, "file_write", {"destination": r"D:\a\b.txt"}, result, False
    )

    assert out is result
    assert ok is False
    assert registry.calls == []


@pytest.mark.asyncio
async def test_approved_adds_root_and_retries_once(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_FEATURE_WRITE_APPROVAL_V1", "true")
    added: list[str] = []
    emitted: list[tuple] = []

    class _Workspace:
        def add_temp_root(self, root):
            added.append(root)
            return True

    monkeypatch.setattr("core.workspace.get_workspace_manager", lambda: _Workspace())
    monkeypatch.setattr(
        "core.chat_events.emit", lambda event_type, **payload: emitted.append((event_type, payload))
    )

    registry = _Registry(result={"success": True, "path": "written"})
    target = str(tmp_path / "out" / "a.txt")
    result = {"success": False, "reason": "outside_workspace_roots", "error": "blocked"}

    async def approve_soon():
        await asyncio.sleep(0.05)
        for item in write_approval.pending():
            write_approval.resolve(item["id"], True)

    task = asyncio.create_task(approve_soon())
    out, ok = await write_approval.maybe_retry_after_block(
        registry, "file_write", {"destination": target}, result, False
    )
    await task

    assert ok is True
    assert out == {"success": True, "path": "written"}
    assert registry.calls == [("file_write", {"destination": target})]
    assert added == [str(tmp_path / "out")]
    assert emitted and emitted[0][0] == "write_auth_required"
    assert emitted[0][1]["path"] == target


@pytest.mark.asyncio
async def test_rejected_keeps_original_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_FEATURE_WRITE_APPROVAL_V1", "true")
    monkeypatch.setattr("core.chat_events.emit", lambda event_type, **payload: None)
    registry = _Registry()
    result = {"success": False, "reason": "outside_workspace_roots", "error": "blocked"}
    target = str(tmp_path / "a.txt")

    async def reject_soon():
        await asyncio.sleep(0.05)
        for item in write_approval.pending():
            write_approval.resolve(item["id"], False)

    task = asyncio.create_task(reject_soon())
    out, ok = await write_approval.maybe_retry_after_block(
        registry, "file_write", {"destination": target}, result, False
    )
    await task

    assert out is result
    assert ok is False
    assert registry.calls == []


@pytest.mark.asyncio
async def test_root_registration_failure_keeps_original_error(monkeypatch, tmp_path):
    monkeypatch.setenv("AERIE_FEATURE_WRITE_APPROVAL_V1", "true")
    monkeypatch.setattr("core.chat_events.emit", lambda event_type, **payload: None)

    class _Workspace:
        def add_temp_root(self, root):
            return False

    monkeypatch.setattr("core.workspace.get_workspace_manager", lambda: _Workspace())
    registry = _Registry()
    result = {"success": False, "reason": "outside_workspace_roots", "error": "blocked"}
    target = str(tmp_path / "a.txt")

    async def approve_soon():
        await asyncio.sleep(0.05)
        for item in write_approval.pending():
            write_approval.resolve(item["id"], True)

    task = asyncio.create_task(approve_soon())
    out, ok = await write_approval.maybe_retry_after_block(
        registry, "file_write", {"destination": target}, result, False
    )
    await task

    assert out is result
    assert ok is False
    assert registry.calls == []
