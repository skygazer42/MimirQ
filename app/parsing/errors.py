"""
Typed parsing exceptions + subprocess error classification.

These errors are intended to be raised by wrappers around the parsing subprocess
runner so upstream layers (ingest pipeline / API) can:
- distinguish timeouts vs unsupported inputs vs internal failures
- apply bounded retries only when it makes sense
"""


from typing import Any


class ParsingError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        code: str,
        details: dict[str, Any] | None = None,
        log_tail: str = "",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = str(code or "unknown")
        self.details: dict[str, Any] = dict(details or {})
        self.log_tail = str(log_tail or "")
        self.retryable = bool(retryable)


class ParsingTimeoutError(ParsingError):
    def __init__(self, message: str = "worker_timeout", *, details: dict[str, Any] | None = None, log_tail: str = "") -> None:
        super().__init__(message, code="timeout", details=details, log_tail=log_tail, retryable=False)


class ParsingUnsupportedError(ParsingError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None, log_tail: str = "") -> None:
        super().__init__(message, code="unsupported", details=details, log_tail=log_tail, retryable=False)


class ParsingInternalError(ParsingError):
    def __init__(self, message: str, *, details: dict[str, Any] | None = None, log_tail: str = "") -> None:
        super().__init__(message, code="internal", details=details, log_tail=log_tail, retryable=True)


def classify_parser_subprocess_error(exc: Exception) -> ParsingError:
    """
    Map low-level subprocess failures to stable typed parsing errors.

    Avoid importing subprocess runner types here to keep this module dependency-light
    and safe to use across the parsing stack.
    """

    if isinstance(exc, ParsingError):
        return exc

    message = (str(exc) or exc.__class__.__name__).strip() or "worker_failed"
    details_raw = getattr(exc, "details", None)
    details = details_raw if isinstance(details_raw, dict) else {}
    log_tail_raw = getattr(exc, "log_tail", "")
    log_tail = log_tail_raw if isinstance(log_tail_raw, str) else str(log_tail_raw)

    norm = message.lower().strip()

    if norm == "worker_timeout":
        return ParsingTimeoutError(message, details=details, log_tail=log_tail)

    if norm in {"payload_too_large", "worker_result_too_large", "worker_log_too_large"}:
        return ParsingUnsupportedError(message, details=details, log_tail=log_tail)

    if (
        "unsupported file type" in norm
        or "unsupported parser backend" in norm
        or norm.startswith("unsupported action")
        or norm.startswith("unsupported ")
    ):
        return ParsingUnsupportedError(message, details=details, log_tail=log_tail)

    return ParsingInternalError(message, details=details, log_tail=log_tail)

