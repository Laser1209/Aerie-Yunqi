import pytest

from communication.ilink.errors import ILinkProtocolError
from communication.ilink.models import (
    AuthPollResult,
    AuthStatus,
    GetUpdatesResponse,
    ILinkCredentials,
    MessageItemType,
    MessageState,
    MessageType,
    QRCodeChallenge,
)


def test_qrcode_challenge_requires_non_empty_strings():
    challenge = QRCodeChallenge.from_dict(
        {"qrcode": "opaque-session", "qrcode_img_content": "opaque-image-payload"}
    )

    assert challenge.qrcode == "opaque-session"
    assert challenge.image_content == "opaque-image-payload"

    with pytest.raises(ILinkProtocolError, match="qrcode_img_content"):
        QRCodeChallenge.from_dict({"qrcode": "opaque-session", "qrcode_img_content": ""})


def test_confirmed_auth_result_requires_complete_credentials():
    result = AuthPollResult.from_dict(
        {
            "status": "confirmed",
            "bot_token": "secret-token",
            "ilink_bot_id": "bot@im.bot",
            "ilink_user_id": "user@im.wechat",
            "baseurl": "https://ilinkai.weixin.qq.com",
        }
    )

    assert result.status is AuthStatus.CONFIRMED
    assert result.credentials == ILinkCredentials(
        bot_token="secret-token",
        bot_id="bot@im.bot",
        user_id="user@im.wechat",
        base_url="https://ilinkai.weixin.qq.com",
    )

    with pytest.raises(ILinkProtocolError, match="ilink_user_id"):
        AuthPollResult.from_dict(
            {
                "status": "confirmed",
                "bot_token": "secret-token",
                "ilink_bot_id": "bot@im.bot",
                "baseurl": "https://ilinkai.weixin.qq.com",
            }
        )


def test_auth_result_rejects_unknown_status():
    with pytest.raises(ILinkProtocolError, match="status"):
        AuthPollResult.from_dict({"status": "success"})


def test_get_updates_parses_messages_strictly():
    response = GetUpdatesResponse.from_dict(
        {
            "ret": 0,
            "errcode": None,
            "errmsg": None,
            "msgs": [
                {
                    "message_id": 42,
                    "from_user_id": "user@im.wechat",
                    "to_user_id": "bot@im.bot",
                    "client_id": "client-42",
                    "create_time_ms": 1_700_000_000_000,
                    "message_type": 1,
                    "message_state": 2,
                    "context_token": "context-42",
                    "item_list": [
                        {"type": 1, "text_item": {"text": "你好"}},
                    ],
                }
            ],
            "get_updates_buf": "next-cursor",
            "longpolling_timeout_ms": 35_000,
        }
    )

    assert response.cursor == "next-cursor"
    assert response.messages[0].message_type is MessageType.USER
    assert response.messages[0].message_state is MessageState.FINISH
    assert response.messages[0].items[0].type is MessageItemType.TEXT
    assert response.messages[0].items[0].text == "你好"


def test_get_updates_rejects_wrong_field_types():
    with pytest.raises(ILinkProtocolError, match="msgs"):
        GetUpdatesResponse.from_dict(
            {"ret": 0, "errcode": None, "msgs": {}, "get_updates_buf": "cursor"}
        )


# ══════════════════════════════════════════════════════
# 回归（2026-09-27 症状①）：可选字段「缺失」不能当违规
#
# iLink 的成功响应实测经常省略字段（ret 会缺）。原 _string 只放行空串、
# 对缺失仍抛错，于是 get_updates_buf 一缺 → 整批解析失败 → 游标不推进
# → 每轮重复失败，外部表现就是「已连接却永远收不到也不回复」。
# ══════════════════════════════════════════════════════

def test_get_updates_tolerates_missing_cursor():
    """缺 get_updates_buf 时游标退化为空串，不得整批失败。"""
    response = GetUpdatesResponse.from_dict({"msgs": []})
    assert response.cursor == ""
    assert response.messages == ()
    assert response.skipped_messages == 0


def test_get_updates_tolerates_missing_ret_and_errmsg():
    """成功响应不带 ret / errcode / errmsg 是实测常态。"""
    response = GetUpdatesResponse.from_dict(
        {
            "msgs": [],
            "get_updates_buf": "cursor-2",
            "longpolling_timeout_ms": 25_000,
        }
    )
    assert response.ret == 0
    assert response.errcode is None
    assert response.errmsg is None
    assert response.cursor == "cursor-2"


def test_message_tolerates_missing_client_id_and_time():
    """缺 client_id / create_time_ms 的真实用户消息不该被整条丢掉。"""
    response = GetUpdatesResponse.from_dict(
        {
            "msgs": [
                {
                    "message_id": 7,
                    "from_user_id": "user@im.wechat",
                    "to_user_id": "bot@im.bot",
                    "message_type": 1,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": "缺字段"}}],
                }
            ],
            "get_updates_buf": "cursor-3",
        }
    )
    assert len(response.messages) == 1
    assert response.messages[0].client_id == ""
    assert response.messages[0].create_time_ms == 0
    assert response.skipped_messages == 0


def test_text_item_tolerates_missing_text():
    """声明为 TEXT 但没带 text 字段：退化为空串，不炸整条消息。"""
    response = GetUpdatesResponse.from_dict(
        {
            "msgs": [
                {
                    "message_id": 8,
                    "from_user_id": "user@im.wechat",
                    "to_user_id": "bot@im.bot",
                    "message_type": 1,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {}}],
                }
            ],
            "get_updates_buf": "cursor-4",
        }
    )
    assert len(response.messages) == 1
    assert response.messages[0].items[0].text == ""


def test_malformed_message_is_skipped_without_losing_the_batch():
    """坏消息只跳自己，同批的好消息必须保住（游标才能推进）。"""
    response = GetUpdatesResponse.from_dict(
        {
            "msgs": [
                {
                    "message_id": 1,
                    "from_user_id": "u1",
                    "to_user_id": "bot",
                    "message_type": 1,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": "好的一"}}],
                },
                {"message_id": 2, "item_list": "not-an-array"},
                {
                    "message_id": 3,
                    "from_user_id": "u3",
                    "to_user_id": "bot",
                    "message_type": 1,
                    "message_state": 2,
                    "item_list": [{"type": 1, "text_item": {"text": "好的三"}}],
                },
            ],
            "get_updates_buf": "cursor-5",
        }
    )
    assert [m.items[0].text for m in response.messages] == ["好的一", "好的三"]
    assert response.skipped_messages == 1
    assert response.cursor == "cursor-5"
