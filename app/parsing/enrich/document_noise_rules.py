import re
from dataclasses import dataclass
from typing import Any

_NOISE_PATTERNS: tuple[tuple[str, str, re.Pattern[str]], ...] = (
    ("pdf_export_noise", "wechat2pdf", re.compile(r"(wechat2pdf|微信文章在线转\s*pdf|在线转\s*pdf)", re.IGNORECASE)),
    (
        "watermark_text",
        "confidential",
        re.compile(r"(watermark|company confidential|for internal use only)", re.IGNORECASE),
    ),
    ("watermark_text", "cn_confidential", re.compile(r"(仅供内部使用|机密|保密)", re.IGNORECASE)),
    ("pdf_export_noise", "page_footer", re.compile(r"^\s*(page\s*)?\d+\s*/\s*\d+\s*$", re.IGNORECASE)),
)

_COMMON_SHORT_REPEAT_TEXT = {"项目", "名称", "序号", "日期", "金额", "备注", "合计", "小计"}


@dataclass(frozen=True, slots=True)
class DocumentNoiseMatch:
    kind: str
    rule: str
    text: str

    def to_metadata(self) -> dict[str, Any]:
        return {"kind": self.kind, "rule": self.rule, "text": self.text}


def classify_document_noise_text(text: str) -> DocumentNoiseMatch | None:
    raw = str(text or "").strip()
    if not raw or raw in _COMMON_SHORT_REPEAT_TEXT:
        return None
    for kind, rule, pattern in _NOISE_PATTERNS:
        if pattern.search(raw):
            return DocumentNoiseMatch(kind=kind, rule=rule, text=raw)
    return None


def is_known_document_noise_text(text: str) -> bool:
    return classify_document_noise_text(text) is not None


__all__ = ["DocumentNoiseMatch", "classify_document_noise_text", "is_known_document_noise_text"]
