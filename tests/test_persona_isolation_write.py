"""Write-path persona isolation tests (portal B)."""

from core.conversation_repository import (
    active_persona_id,
    resolve_conversation_id,
)


def test_active_persona_id_returns_id_or_none():
    # 不抛异常即可；返回 None 或字符串
    assert active_persona_id() is None or isinstance(active_persona_id(), str)


def test_conversation_id_differs_by_persona():
    base = dict(actor_id="a", channel="desktop", channel_account_id="local", user_id=7)
    c0 = resolve_conversation_id(**base)
    c1 = resolve_conversation_id(**base, persona_id="yita_default")
    c2 = resolve_conversation_id(**base, persona_id="sena")
    assert c0 != c1
    assert c1 != c2
    # NULL persona 与不传一致（共享语义）
    assert resolve_conversation_id(**base, persona_id=None) == c0
