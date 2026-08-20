"""Aerie QQ 引擎 — OneBot11 协议层（自研实现）。

本包是 Aerie 对 OneBot11 协议的独立实现，不依赖任何第三方 OneBot SDK：

- :mod:`actions`   : OneBot11 标准动作 + QQ 引擎扩展动作常量表
- :mod:`messages`  : 消息段（segment）构造工具
- :mod:`events`    : 上行事件模型与类型常量
- :mod:`client`    : OneBot11 WebSocket 客户端（连接/心跳/echo 匹配/事件分发）

对外只暴露 :class:`~communication.onebot11.client.OneBot11Client`。
业务层（communication.qq_client）包装本客户端，提供 Aerie 场景的语义。
"""
