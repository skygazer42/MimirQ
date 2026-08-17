"""
Email (.eml/.msg) parser adapter.

Phase 1 goals:
- Extract key headers + body into Markdown.
- Avoid heavyweight dependencies (stdlib only).
- Be resilient to common encodings and multipart payloads.

Notes:
- Attachments are not extracted in Phase 1 (future work).
"""


import re
from email import policy
from email.message import Message
from email.parser import BytesParser
from html import unescape
from pathlib import Path
from typing import Any

from langchain_core.documents import Document

from app.core.optional_deps import require_dependency
from app.rag.core.logging import get_logger

logger = get_logger("parsing.email")


_RE_SCRIPT_STYLE = re.compile(r"(?is)<(script|style)\b[^>]*>.*?</\1\s*>")
_RE_TAGS = re.compile(r"(?is)<[^>]+>")
_RE_WS = re.compile(r"\s+")
_MIME_TEXT_PLAIN = "text/plain"
_MIME_TEXT_HTML = "text/html"


def _collapse_ws(text: str) -> str:
    return _RE_WS.sub(" ", (text or "").strip())


def _strip_html(html_text: str) -> str:
    """
    Best-effort HTML -> text without optional deps.
    Keeps this intentionally conservative to avoid mangling content.
    """
    raw = str(html_text or "")
    if not raw.strip():
        return ""
    raw = _RE_SCRIPT_STYLE.sub(" ", raw)
    raw = _RE_TAGS.sub(" ", raw)
    raw = unescape(raw)
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    # Keep some readability while bounding whitespace noise.
    lines = [line.strip() for line in raw.split("\n")]
    lines = [line for line in lines if line]
    return "\n".join(lines).strip()


def _safe_header(msg: Message, key: str) -> str:
    try:
        val = msg.get(key, "")
    except Exception:
        val = ""
    return _collapse_ws(str(val or ""))


def _iter_message_parts(msg: Message) -> list[Message]:
    try:
        return list(msg.walk()) if msg.is_multipart() else [msg]
    except Exception:
        return [msg]


def _is_multipart_part(part: Message) -> bool:
    try:
        return bool(part.is_multipart())
    except Exception as exc:
        logger.debug("Ignoring non-critical email parser fallback failure: %s", exc)
        return False


def _part_content_type(part: Message) -> str:
    try:
        return str(part.get_content_type() or "").lower()
    except Exception:
        return ""


def _part_is_attachment(part: Message) -> bool:
    try:
        return str(part.get_content_disposition() or "").lower() == "attachment"
    except Exception:
        return False


def _decode_message_part(part: Message, warnings: list[str]) -> str | None:
    try:
        payload = part.get_content()
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"part_decode_failed:{exc.__class__.__name__}")
        return None
    if not isinstance(payload, str) or not payload.strip():
        return None
    return payload


def _collect_body_parts(msg: Message) -> tuple[list[str], list[str], list[str]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    warnings: list[str] = []
    for part in _iter_message_parts(msg):
        if part is None or _is_multipart_part(part) or _part_is_attachment(part):
            continue
        payload = _decode_message_part(part, warnings)
        if payload is None:
            continue
        ctype = _part_content_type(part)
        if ctype == _MIME_TEXT_PLAIN:
            plain_parts.append(payload)
        elif ctype == _MIME_TEXT_HTML:
            html_parts.append(payload)
    return plain_parts, html_parts, warnings


def _merge_body_parts(parts: list[str]) -> str:
    return "\n\n".join([part.strip() for part in parts if part.strip()]).strip()


def _select_body_content(plain_parts: list[str], html_parts: list[str]) -> tuple[str, str]:
    if plain_parts:
        return _merge_body_parts(plain_parts), _MIME_TEXT_PLAIN
    if html_parts:
        return _strip_html(_merge_body_parts(html_parts)), _MIME_TEXT_HTML
    return "", "none"


def _parse_eml_message(file_path: Path) -> tuple[Message, dict[str, Any]]:
    raw = file_path.read_bytes()
    try:
        msg = BytesParser(policy=policy.default).parsebytes(raw)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to parse .eml: {exc.__class__.__name__}: {str(exc)[:200]}") from exc

    body, body_meta = _extract_body(msg)
    return msg, {
        "subject": _safe_header(msg, "Subject") or "Email",
        "sender": _safe_header(msg, "From"),
        "to": _safe_header(msg, "To"),
        "cc": _safe_header(msg, "Cc"),
        "date": _safe_header(msg, "Date"),
        "body": body,
        "body_content_type": str(body_meta.get("body_content_type") or "none"),
        "warnings": list(body_meta.get("warnings") or []),
    }


def _extract_msg_body(msg: Any) -> tuple[str, str]:
    body = str(getattr(msg, "body", "") or "").strip()
    if body:
        return body, _MIME_TEXT_PLAIN

    html_body = str(getattr(msg, "htmlBody", "") or getattr(msg, "html", "") or "").strip()
    if html_body:
        return _strip_html(html_body), _MIME_TEXT_HTML
    return "", "none"


def _parse_msg_message(file_path: Path) -> dict[str, Any]:
    extract_msg = require_dependency(
        "extract_msg",
        feature="email_msg_parser",
        pip_name="extract-msg",
    )
    message_cls = getattr(extract_msg, "Message", None)
    if message_cls is None:
        raise RuntimeError("extract_msg.Message missing (unsupported extract-msg version)")

    msg = message_cls(str(file_path))
    try:
        if callable(getattr(msg, "process", None)):
            msg.process()
        body, body_content_type = _extract_msg_body(msg)
        return {
            "subject": str(getattr(msg, "subject", "") or "").strip() or "Email",
            "sender": str(getattr(msg, "sender", "") or getattr(msg, "sender_email", "") or "").strip(),
            "to": str(getattr(msg, "to", "") or "").strip(),
            "cc": str(getattr(msg, "cc", "") or "").strip(),
            "date": str(getattr(msg, "date", "") or "").strip(),
            "body": body,
            "body_content_type": body_content_type,
            "warnings": [],
        }
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"Failed to parse .msg: {exc.__class__.__name__}: {str(exc)[:200]}") from exc
    finally:
        try:
            msg.close()
        except Exception as exc:
            logger.debug("Ignoring non-critical email parser fallback failure: %s", exc)


def _build_email_markdown(*, subject: str, sender: str, to: str, cc: str, date: str, body: str) -> str:
    header_lines: list[str] = []
    if sender:
        header_lines.append(f"- From: {sender}")
    if to:
        header_lines.append(f"- To: {to}")
    if cc:
        header_lines.append(f"- Cc: {cc}")
    if date:
        header_lines.append(f"- Date: {date}")

    md_parts: list[str] = [f"# {subject}"]
    if header_lines:
        md_parts.append("\n".join(header_lines))
    if body.strip():
        md_parts.append("---")
        md_parts.append(body.strip())
    return "\n\n".join([part for part in md_parts if part.strip()]).strip() + "\n"


def _build_email_metadata(
    *,
    file_path: Path,
    ext: str,
    subject: str,
    body_content_type: str,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "source": file_path.name,
        "file_type": ext.lstrip("."),
        "parser_backend": "email",
        "email_subject": subject[:200],
        "email_body_content_type": body_content_type,
        "email_warnings": list(warnings or []),
    }


def _extract_body(msg: Message) -> tuple[str, dict[str, Any]]:
    """
    Extract (body_text, meta).

    Preference order:
    1) text/plain
    2) text/html (stripped)
    """
    plain_parts, html_parts, warnings = _collect_body_parts(msg)
    body, used = _select_body_content(plain_parts, html_parts)
    meta = {"body_content_type": used, "warnings": warnings[:20]}
    return body, meta


class EmailParser:
    def parse(self, file_path: Path, **kwargs: Any) -> list[Document]:
        _ = kwargs
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")
        ext = file_path.suffix.lower()
        if ext not in {".eml", ".msg"}:
            raise ValueError(f"EmailParser supports only .eml/.msg, got: {ext}")

        if ext == ".eml":
            _, parsed = _parse_eml_message(file_path)
        else:
            parsed = _parse_msg_message(file_path)

        subject = str(parsed["subject"])
        sender = str(parsed["sender"])
        to = str(parsed["to"])
        cc = str(parsed["cc"])
        date = str(parsed["date"])
        body = str(parsed["body"])
        body_content_type = str(parsed["body_content_type"])
        warnings = list(parsed["warnings"])

        if not body.strip():
            logger.info("[email] parsed %s but body is empty", file_path.name)

        markdown = _build_email_markdown(
            subject=subject,
            sender=sender,
            to=to,
            cc=cc,
            date=date,
            body=body,
        )
        metadata = _build_email_metadata(
            file_path=file_path,
            ext=ext,
            subject=subject,
            body_content_type=body_content_type,
            warnings=warnings,
        )

        return [Document(page_content=markdown, metadata=metadata)]
