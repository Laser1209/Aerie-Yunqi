"""Aerie · 云栖 — RecallAdapter 端口撤回抽象层 (Gate 1).

将「撤回」从单一 user_id 绑定中解耦, 按 channel(端口) 分派:
  - QQ     : 通过 NapCat delete_msg 真实撤回
  - local  : 仅本地 DB 标记 + 前端事件 (无真实协议撤回)
  - clawbot: 微信端预留桩 (未来接入 iLink ClawBot)
"""
