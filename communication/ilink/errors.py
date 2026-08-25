class ILinkError(RuntimeError):
    code = "ilink_error"


class ILinkHTTPError(ILinkError):
    code = "http_error"

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"iLink HTTP request failed with status {status_code}")


class ILinkProtocolError(ILinkError):
    code = "protocol_error"


class ILinkSessionExpired(ILinkError):
    code = "session_expired"


class ILinkRateLimitError(ILinkHTTPError):
    code = "rate_limited"

    def __init__(self, retry_after: float | None = None) -> None:
        self.retry_after = retry_after
        super().__init__(429)


class ILinkMediaError(ILinkError):
    code = "media_error"
