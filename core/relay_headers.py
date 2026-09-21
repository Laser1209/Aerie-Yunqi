"""Aerie 中转请求的公共头来源。

为什么需要这个头：
Aerie 的 LLM 请求大多经自建中转网关（Cloudflare Worker，`api.etta.top`）转发，真实
上游 API Key 存在 Worker 的 secret 里，客户端只持有一枚「门卡」令牌——而门卡按设计是
随安装包公开分发的，所以防护必须做在服务端。Worker 需要知道「正在说话的是哪个版本的
客户端」，才能淘汰旧版本、识别非官方客户端。客户端版本因此必须随每个中转请求上报。

收敛到这一处的意义：此前 5、6 个位置各自构造客户端，若各写各的版本头，改版本号时
必然漏改。这里只做两件事——给出公共头、判断是否走中转，保持纯函数、无状态、无缓存。

只给中转请求加头：直连官方 API（dashscope / deepseek 等）不需要、也不该硬塞。
"""

from __future__ import annotations

from urllib.parse import urlparse

from core.version import APP_VERSION

# 中转网关域名：Aerie 自建 Cloudflare Worker。命中这里（含子域）才带版本头。
_RELAY_HOST = "etta.top"
_RELAY_HEADER_NAME = "X-Aerie-Version"


def relay_headers() -> dict[str, str]:
    """返回需要随中转请求上报的公共头。"""
    return {_RELAY_HEADER_NAME: APP_VERSION}


def is_relay_base_url(url: str | None) -> bool:
    """判断某个 base_url 是否指向中转网关（etta.top 及其子域）。

    识别不出（None / 空串 / 非法 URL / 官方直连域名）一律返回 False。
    """
    if not url or not isinstance(url, str):
        return False
    host = urlparse(url).hostname
    if not host:
        return False
    host = host.lower()
    return host == _RELAY_HOST or host.endswith("." + _RELAY_HOST)
