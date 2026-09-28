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
    @pytest.fixture(autouse=True)
    def open_napcat_port(self):
        with patch("communication.qq_client._port_is_open", return_value=True) as port_probe:
            yield port_probe

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

    def test_closed_port_returns_false(self, tmp_path, open_napcat_port):
        target = tmp_path / "a.txt"
        target.write_text("x", encoding="utf-8")
        client = _client(tmp_path)
        client._rpc_call = AsyncMock(return_value={"status": "ok"})
        open_napcat_port.return_value = False
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
        return comp

    def test_enqueues_reply_with_file(self, tmp_path):
        """§九-b：投递目标是**请求级来源端口**（由 pipeline 在工具执行窗口绑定）。"""
        from core import delivery_routing

        comp = self._companion_with_queue()
        token = delivery_routing.bind(
            delivery_routing.DeliveryContext(channel="qq", user_id=3489352115)
        )
        try:
            comp._notify_file_delivery({"path": str(tmp_path / "r.docx"), "note": "给你"})
        finally:
            delivery_routing.unbind(token)

        assert len(comp.queue.sent) == 1
        reply = comp.queue.sent[0]
        assert reply.user_id == 3489352115
        assert reply.channel == "qq"
        assert reply.file_paths == [str(tmp_path / "r.docx")]
        assert reply.content == "给你"

    def test_no_origin_does_not_enqueue_but_records_receipt(self, tmp_path):
        """无来源端口 → 不投递，但**不静默丢件**：落一条未决回执让模型知道。"""
        from core.delivery_ledger import get_ledger

        ledger = get_ledger()
        ledger.clear()
        comp = self._companion_with_queue()
        comp._notify_file_delivery({"path": str(tmp_path / "r.docx")})

        assert comp.queue.sent == []
        assert ledger.has_pending(0) is True
        ledger.clear()

    def test_blank_path_is_ignored(self):
        comp = self._companion_with_queue()
        comp._notify_file_delivery({"path": "   "})
        assert comp.queue.sent == []


# ══════════════════════════════════════════════════════
# 4. office_tools.send_file_to_user：Agent 工具入口
# ══════════════════════════════════════════════════════

class TestSendFileToUserTool:
    @pytest.fixture(autouse=True)
    def clean_ledger(self):
        """隔离进程内投递台账，避免用例之间互相看到回执。"""
        from core.delivery_ledger import get_ledger

        get_ledger().clear()
        yield
        get_ledger().clear()

    @staticmethod
    def _fake_companion(ledger, *, outcome: tuple[bool, str] | None):
        """假 companion：登记回执并按 outcome 立即落定（None = 永不落定）。"""
        calls: list[dict] = []

        def _notify(payload):
            calls.append(payload)
            did = ledger.record_pending(
                user_id=1, channel="ilink", path=payload.get("path", ""),
            )
            if outcome is not None:
                ledger.record_outcome(did, ok=outcome[0], detail=outcome[1])
            return did

        return SimpleNamespace(_notify_file_delivery=_notify), calls

    def test_rejects_path_outside_allowed_roots(self, tmp_path):
        from core import office_tools

        outside = tmp_path / "outside.txt"
        outside.write_text("secret", encoding="utf-8")
        with patch.object(office_tools, "_resolve_write_target", return_value=None):
            result = asyncio.run(office_tools.tool_send_file_to_user(str(outside)))
        assert result["success"] is False
        assert "不在允许发送的目录内" in result["error"]
        # 越界必须带 reason，否则 write_approval 的"弹审批→加根→重试"桥不会介入。
        assert result["reason"] == "outside_workspace_roots"

    def test_rejects_missing_file(self):
        from core import office_tools

        with patch.object(office_tools, "_resolve_write_target",
                          return_value=Path(r"C:\nope\missing.txt")):
            result = asyncio.run(office_tools.tool_send_file_to_user("missing.txt"))
        assert result["success"] is False
        # 在授权根内但不存在：这是"文件不存在"，不是越界 —— 不该触发授权流程。
        assert "reason" not in result

    def test_blank_path_rejected(self):
        from core import office_tools

        result = asyncio.run(office_tools.tool_send_file_to_user("   "))
        assert result["success"] is False

    def test_reports_delivered_after_channel_confirms(self, tmp_path):
        """通道回执 ok → 工具说 delivered，模型才有资格说"发出去了"。

        历史 bug：入队即返回（6ms），模型把"已入队"当"已送达"，
        投递失败时照旧宣称已送达（§十四 #67 的假成功）。
        """
        from core import office_tools
        from core.delivery_ledger import get_ledger

        target = tmp_path / "report.docx"
        target.write_text("body", encoding="utf-8")
        fake, calls = self._fake_companion(get_ledger(), outcome=(True, ""))

        with patch.object(office_tools, "_resolve_write_target", return_value=target), \
                patch("core.companion.get_companion", return_value=fake):
            result = asyncio.run(
                office_tools.tool_send_file_to_user(str(target), note="给你的")
            )

        assert result["status"] == "delivered"
        assert result["delivered"] is True
        assert result["name"] == "report.docx"
        assert calls == [{"path": str(target), "note": "给你的"}]

    def test_reports_failure_when_channel_refuses(self, tmp_path):
        """通道确认失败 → 工具必须报失败并带上原因，不得报成功。"""
        from core import office_tools
        from core.delivery_ledger import get_ledger

        target = tmp_path / "report.docx"
        target.write_text("body", encoding="utf-8")
        fake, _calls = self._fake_companion(get_ledger(), outcome=(False, "上传超时"))

        with patch.object(office_tools, "_resolve_write_target", return_value=target), \
                patch("core.companion.get_companion", return_value=fake):
            result = asyncio.run(office_tools.tool_send_file_to_user(str(target)))

        assert result["success"] is False
        assert result["delivered"] is False
        assert result["status"] == "failed"
        assert "上传超时" in result["error"]

    def test_reports_unknown_when_no_receipt(self, tmp_path):
        """时限内没有回执 → 报"结果未知"，而不是替它断言已送达。"""
        from core import office_tools
        from core.delivery_ledger import get_ledger

        target = tmp_path / "report.docx"
        target.write_text("body", encoding="utf-8")
        fake, _calls = self._fake_companion(get_ledger(), outcome=None)

        with patch.object(office_tools, "_resolve_write_target", return_value=target), \
                patch.object(office_tools, "_FILE_DELIVERY_WAIT_SEC", 0.0), \
                patch("core.companion.get_companion", return_value=fake):
            result = asyncio.run(office_tools.tool_send_file_to_user(str(target)))

        assert result["success"] is False
        assert result["delivered"] is False
        assert result["status"] == "unknown"

    def test_no_delivery_port_reports_failure(self, tmp_path):
        """来源端口发不了文件（无端口/桌面端）→ 立刻报失败，不进"未知"排队。"""
        from core import office_tools

        target = tmp_path / "report.docx"
        target.write_text("body", encoding="utf-8")
        fake = SimpleNamespace(_notify_file_delivery=lambda payload: "")

        with patch.object(office_tools, "_resolve_write_target", return_value=target), \
                patch("core.companion.get_companion", return_value=fake):
            result = asyncio.run(office_tools.tool_send_file_to_user(str(target)))

        assert result["success"] is False
        assert result["status"] == "failed"
        assert "没有可用的投递端口" in result["error"]

    def test_no_companion_reports_failure(self, tmp_path):
        from core import office_tools

        target = tmp_path / "report.docx"
        target.write_text("body", encoding="utf-8")
        with patch.object(office_tools, "_resolve_write_target", return_value=target), \
                patch("core.companion.get_companion", return_value=None):
            result = asyncio.run(office_tools.tool_send_file_to_user(str(target)))
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
