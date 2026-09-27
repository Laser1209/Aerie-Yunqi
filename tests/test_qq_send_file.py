"""QQ 出站文件投递回归测试。

背景：协议层（NapCat ``upload_private_file``）实测可用，但 Python 侧
``QQClient`` 一直没有发文件的方法，于是「让 Agent 写完文件发给我」在
QQ 通道上完全做不到。本文件锁定新增的这条链路：

    QQClient.send_file  →  OutgoingReply.file_paths  →  Companion._send_to_qq
    →  office_tools.send_file_to_user（Agent 工具入口）
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from communication.message import OutgoingReply
from communication.qq_client import QQClient
from core.companion import Companion


def _client(tmp_path: Path, *, connected: bool = True) -> QQClient:
    client = QQClient({"ws_port": 3001})
    client._disabled = False
    client._connectivity_test = False
    client._connected = connected
    return client


# ══════════════════════════════════════════════════════
# 1. QQClient.send_file
# ══════════════════════════════════════════════════════

class TestQQClientSendFile:
    def test_missing_file_short_circuits(self, tmp_path):
        client = _client(tmp_path)
        client._rpc_call = AsyncMock()
        missing = tmp_path / "nope.txt"
        assert asyncio.run(client.send_file(123, str(missing))) is False
        client._rpc_call.assert_not_awaited()

    def test_offline_returns_false(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        client = _client(tmp_path, connected=False)
        client._rpc_call = AsyncMock()
        assert asyncio.run(client.send_file(123, str(target))) is False
        client._rpc_call.assert_not_awaited()

    def test_safety_mode_skips(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        client = _client(tmp_path)
        client._disabled = True
        client._rpc_call = AsyncMock()
        assert asyncio.run(client.send_file(123, str(target))) is False
        client._rpc_call.assert_not_awaited()

    def test_success_sends_resolved_path_and_name(self, tmp_path):
        target = tmp_path / "报告.txt"
        target.write_text("hello", encoding="utf-8")
        client = _client(tmp_path)
        client._rpc_call = AsyncMock(return_value={"status": "ok", "retcode": 0})

        assert asyncio.run(client.send_file(3489352115, str(target))) is True
        args = client._rpc_call.await_args
        assert args.args[0] == "upload_private_file"
        params = args.args[1]
        assert params["user_id"] == 3489352115
        assert params["file"] == str(target.resolve())
        assert params["name"] == "报告.txt"

    def test_explicit_name_overrides_basename(self, tmp_path):
        target = tmp_path / "internal_tmp_9931.dat"
        target.write_text("x", encoding="utf-8")
        client = _client(tmp_path)
        client._rpc_call = AsyncMock(return_value={"status": "ok"})

        assert asyncio.run(client.send_file(1, str(target), name="周报.docx")) is True
        assert client._rpc_call.await_args.args[1]["name"] == "周报.docx"

    def test_non_ok_status_is_false(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        client = _client(tmp_path)
        client._rpc_call = AsyncMock(return_value={"status": "failed", "retcode": 100})
        assert asyncio.run(client.send_file(1, str(target))) is False

    def test_rpc_timeout_is_false(self, tmp_path):
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        client = _client(tmp_path)
        client._rpc_call = AsyncMock(return_value=None)
        assert asyncio.run(client.send_file(1, str(target))) is False


# ══════════════════════════════════════════════════════
# 2. Companion._send_to_qq：文本 + 文件
# ══════════════════════════════════════════════════════

def _bare_companion(qq) -> Companion:
    comp = Companion.__new__(Companion)
    comp.qq = qq
    return comp


class TestSendToQQ:
    def test_sends_text_then_each_file(self, tmp_path):
        qq = SimpleNamespace(
            send_message=AsyncMock(return_value=True),
            send_file=AsyncMock(return_value=True),
        )
        comp = _bare_companion(qq)
        reply = OutgoingReply(
            user_id=123, content="写好了",
            file_paths=[str(tmp_path / "a.txt"), str(tmp_path / "b.txt")],
        )
        assert asyncio.run(comp._send_to_qq(reply)) is True
        qq.send_message.assert_awaited_once_with(123, "写好了")
        assert qq.send_file.await_count == 2

    def test_file_only_reply_still_delivers_file(self, tmp_path):
        """文本为空（send_message 自行跳过）不应连累文件投递。"""
        qq = SimpleNamespace(
            send_message=AsyncMock(return_value=False),
            send_file=AsyncMock(return_value=True),
        )
        comp = _bare_companion(qq)
        reply = OutgoingReply(user_id=7, content="", file_paths=[str(tmp_path / "a.txt")])
        asyncio.run(comp._send_to_qq(reply))
        qq.send_file.assert_awaited_once_with(7, str(tmp_path / "a.txt"))

    def test_one_file_failure_does_not_block_others(self, tmp_path):
        qq = SimpleNamespace(
            send_message=AsyncMock(return_value=True),
            send_file=AsyncMock(side_effect=[False, True]),
        )
        comp = _bare_companion(qq)
        reply = OutgoingReply(
            user_id=7, content="hi", file_paths=["/p1", "/p2"],
        )
        assert asyncio.run(comp._send_to_qq(reply)) is True
        assert qq.send_file.await_count == 2

    def test_file_exception_is_contained(self, tmp_path):
        qq = SimpleNamespace(
            send_message=AsyncMock(return_value=True),
            send_file=AsyncMock(side_effect=RuntimeError("boom")),
        )
        comp = _bare_companion(qq)
        reply = OutgoingReply(user_id=7, content="hi", file_paths=["/p1"])
        assert asyncio.run(comp._send_to_qq(reply)) is True

    def test_no_files_keeps_text_only_path(self):
        qq = SimpleNamespace(send_message=AsyncMock(return_value=True))
        comp = _bare_companion(qq)
        reply = OutgoingReply(user_id=7, content="hi")
        assert asyncio.run(comp._send_to_qq(reply)) is True
        assert not hasattr(qq, "send_file") or qq.send_file.call_count == 0


# ══════════════════════════════════════════════════════
# 3. Companion._notify_file_delivery：工具 → 会话通道
# ══════════════════════════════════════════════════════

class TestNotifyFileDelivery:
    def _companion_with_queue(self):
        comp = Companion.__new__(Companion)
        comp.queue = SimpleNamespace(enqueue=lambda reply: comp.queue.sent.append(reply))
        comp.queue.sent = []
        comp._last_inbound_target = {
            "user_id": 3489352115, "source": "qq",
            "channel": "qq", "channel_account_id": "",
        }
        return comp

    def test_enqueues_reply_with_file(self, tmp_path):
        comp = self._companion_with_queue()
        comp._notify_file_delivery({"path": str(tmp_path / "r.docx"), "note": "给你"})
        assert len(comp.queue.sent) == 1
        reply = comp.queue.sent[0]
        assert reply.user_id == 3489352115
        assert reply.channel == "qq"
        assert reply.file_paths == [str(tmp_path / "r.docx")]
        assert reply.content == "给你"

    def test_no_target_does_not_enqueue(self, tmp_path):
        comp = self._companion_with_queue()
        comp._last_inbound_target = {}
        comp._notify_file_delivery({"path": str(tmp_path / "r.docx")})
        assert comp.queue.sent == []

    def test_blank_path_is_ignored(self):
        comp = self._companion_with_queue()
        comp._notify_file_delivery({"path": "   "})
        assert comp.queue.sent == []


# ══════════════════════════════════════════════════════
# 4. office_tools.send_file_to_user：Agent 工具入口
# ══════════════════════════════════════════════════════

class TestSendFileToUserTool:
    def test_rejects_path_outside_allowed_roots(self, tmp_path):
        from core import office_tools

        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        with patch.object(office_tools, "_resolve_write_target", return_value=None):
            result = office_tools.tool_send_file_to_user(str(outside))
        assert result["success"] is False
        assert "不在允许发送的目录内" in result["error"]

    def test_rejects_missing_file(self):
        from core import office_tools

        with patch.object(office_tools, "_resolve_write_target",
                          return_value=Path(r"C:\nope\missing.txt")):
            result = office_tools.tool_send_file_to_user("missing.txt")
        assert result["success"] is False

    def test_success_enqueues_through_companion(self, tmp_path):
        from core import office_tools

        target = tmp_path / "report.docx"
        target.write_text("body", encoding="utf-8")
        fake = SimpleNamespace(_notify_file_delivery=lambda payload: fake.calls.append(payload))
        fake.calls = []

        with patch.object(office_tools, "_resolve_write_target", return_value=target), \
                patch("core.companion.get_companion", return_value=fake):
            result = office_tools.tool_send_file_to_user(str(target), note="给你的")

        assert result["success"] is True
        assert result["name"] == "report.docx"
        assert fake.calls == [{"path": str(target), "note": "给你的"}]

    def test_no_companion_reports_failure(self, tmp_path):
        from core import office_tools

        target = tmp_path / "report.docx"
        target.write_text("body", encoding="utf-8")
        with patch.object(office_tools, "_resolve_write_target", return_value=target), \
                patch("core.companion.get_companion", return_value=None):
            result = office_tools.tool_send_file_to_user(str(target))
        assert result["success"] is False

    def test_tool_is_registered(self):
        from core.office_tools import _OFFICE_TOOL_SCHEMAS, register_office_tools

        assert "send_file_to_user" in _OFFICE_TOOL_SCHEMAS

        class _Reg:
            def __init__(self):
                self.names = []

            def register(self, name, func, schema, category=""):
                self.names.append(name)

        reg = _Reg()
        register_office_tools(reg)
        assert "send_file_to_user" in reg.names
