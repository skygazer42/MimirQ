"""
Governance profile registry (built-in profiles) and helpers.

This module intentionally keeps profiles declarative:
- No executable code, no dynamic imports.
- Profiles are used to patch pipeline options and provide additional regex rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import ValidationError

from app.api.schemas.document import DocumentPipelineOptions
from app.api.schemas.governance_profile import GovernanceProfileOut, GovernanceProfilePayload, RegexRuleModel
from app.core.regex_safety import DEFAULT_ALLOWED_FLAG_BITS, validate_regex_rules

PROFILE_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,99}$")
MAX_PROFILE_RULES = 60
MAX_PROFILE_RULE_PATTERN = 600
MAX_PROFILE_RULE_REPL = 2000

DEFAULT_GOVERNANCE_SECRETS_MASK = "[SECRET]"


def validate_profile_key(key: str | None) -> str | None:
    if key is None:
        return None
    val = str(key or "").strip()
    if not val:
        return None
    if val.startswith("builtin:"):
        raise ValueError("profile key must not start with 'builtin:'")
    if not PROFILE_KEY_RE.match(val):
        raise ValueError("invalid profile key format")
    return val


def _normalize_pipeline_patch(raw: object) -> dict:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ValueError("payload.pipeline_patch must be an object")

    allowed = set(DocumentPipelineOptions.model_fields.keys())
    unknown = [k for k in raw.keys() if k not in allowed]
    if unknown:
        unknown_sorted = ", ".join(sorted(map(str, unknown))[:20])
        raise ValueError(f"payload.pipeline_patch contains unknown keys: {unknown_sorted}")

    try:
        validated = DocumentPipelineOptions(**raw)
    except ValidationError as exc:
        # Keep message short for API consumers.
        raise ValueError("invalid payload.pipeline_patch") from exc

    # Store only explicit overrides.
    return validated.model_dump(exclude_none=True)


def _normalize_regex_rules(raw: object) -> list[dict]:
    return validate_regex_rules(
        raw,
        max_rules=MAX_PROFILE_RULES,
        max_pattern_len=MAX_PROFILE_RULE_PATTERN,
        max_repl_len=MAX_PROFILE_RULE_REPL,
        allowed_flag_bits=DEFAULT_ALLOWED_FLAG_BITS,
    )


def validate_and_normalize_payload(payload: GovernanceProfilePayload) -> GovernanceProfilePayload:
    extends = None
    raw_extends = getattr(payload, "extends", None)
    if raw_extends is not None:
        ref = str(raw_extends or "").strip()
        if ref:
            # Keep it safe for logs/storage/JSON; existence is resolved later.
            if "\x7f" in ref or any(ord(ch) < 32 for ch in ref):
                raise ValueError("payload.extends contains control characters")
            extends = ref[:120]

    cleaned_formats: list[str] = []
    for fmt in (payload.input_formats or []):
        v = str(fmt or "").strip().lower()
        if v in {"markdown", "html"} and v not in cleaned_formats:
            cleaned_formats.append(v)
    if not cleaned_formats:
        cleaned_formats = ["markdown"]

    cleaned_patch = _normalize_pipeline_patch(payload.pipeline_patch)
    cleaned_rules = _normalize_regex_rules(payload.regex_rules)
    scripts = list(payload.processing_scripts or [])
    if len(scripts) > 10:
        raise ValueError("payload.processing_scripts contains too many entries (max=10)")

    return GovernanceProfilePayload(
        version="1",
        extends=extends,
        input_formats=cleaned_formats,  # type: ignore[arg-type]
        pipeline_patch=cleaned_patch,
        regex_rules=[RegexRuleModel(**r) for r in cleaned_rules],
        processing_scripts=scripts,
    )


@dataclass(frozen=True)
class BuiltinGovernanceProfile:
    key: str
    name: str
    description: str
    payload: GovernanceProfilePayload


def _p(
    *,
    input_formats: list[str],
    pipeline_patch: dict,
    regex_rules: list[dict] | None = None,
) -> GovernanceProfilePayload:
    return GovernanceProfilePayload(
        version="1",
        input_formats=[f for f in input_formats if f in {"markdown", "html"}] or ["markdown"],  # type: ignore[arg-type]
        pipeline_patch=dict(pipeline_patch or {}),
        regex_rules=[RegexRuleModel(**r) for r in (regex_rules or [])],
    )


def get_builtin_governance_profiles() -> list[BuiltinGovernanceProfile]:
    """
    Built-in profiles cover the most common ingestion sources:
    - Web HTML -> Markdown (boilerplate heavy)
    - PDF -> Markdown (soft line breaks, headers/footers, tables)
    - OCR/scanned documents (fallback + conservative cleanup)

    Keep these profiles conservative and safe-by-default.
    """
    return [
        BuiltinGovernanceProfile(
            key="builtin:kb_default",
            name="知识库默认（保守）",
            description="适用于大多数 Markdown/纯文本：去目录/噪声、合并软换行、去重页眉页脚。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_max_blank_lines": 1,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:html_web",
            name="网页 HTML（去样板/去导航）",
            description="适用于网页抓取/复制：启用样板移除、URL 规范化、去追踪参；可配 XPath 提取正文。",
            payload=_p(
                input_formats=["html", "markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": False,
                    "governance_remove_common_lines": False,
                    "governance_remove_boilerplate": True,
                    "governance_remove_images": "decorative",
                    # Optional rule packs (default off globally; enabled here explicitly).
                    "governance_rule_packs": ["web_navigation", "web_cookie_banners"],
                    "governance_normalize_urls": True,
                    "governance_normalize_urls_strip_tracking": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "governance_drop_duplicate_paragraphs_min_occurrences": 3,
                    "governance_drop_duplicate_paragraphs_min_chars": 40,
                    "governance_drop_duplicate_paragraphs_max_chars": 1200,
                },
                regex_rules=[],
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:pdf_text",
            name="PDF 文本版（修复断行/页眉页脚/表格）",
            description="适用于可复制文本的 PDF：合并软换行、去重页眉页脚、表格规范化。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_normalize_tables": True,
                    "governance_max_blank_lines": 1,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:policy_manual_pdf",
            name="制度/手册 PDF（条款结构友好）",
            description="适用于制度/手册类 PDF：修复断行、去重页眉页脚/重复段落，尽量保留正文结构。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "governance_drop_duplicate_paragraphs_min_occurrences": 3,
                    "governance_drop_duplicate_paragraphs_min_chars": 40,
                    "governance_drop_duplicate_paragraphs_max_chars": 1200,
                    "governance_normalize_tables": True,
                    "governance_max_blank_lines": 1,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:pdf_scanned_ocr",
            name="PDF 扫描/OCR（更强容错）",
            description="适用于扫描件/OCR：开启解析兜底与更保守的噪声过滤（避免把正文删掉）。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_noise_ratio_threshold": 0.12,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "parse_fallback_enabled": True,
                    "parse_fallback_min_content_chars": 160,
                    "parse_fallback_max_retries": 1,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:legal_compliance",
            name="合规脱敏（PII/密钥）",
            description="适用于可能包含邮箱/电话/Token 的文档：启用 PII 匿名化与密钥脱敏。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_pii_anonymize": True,
                    "governance_pii_mode": "mask",
                    "governance_pii_mask": "[REDACTED]",
                    "governance_secrets_redact": True,
                    "governance_secrets_mode": "mask",
                    "governance_secrets_mask": DEFAULT_GOVERNANCE_SECRETS_MASK,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:wiki_longform",
            name="长文/Wiki（去重+参考文献）",
            description="适用于 Wiki/手册：去重重复段落、裁剪末尾 References（保守）。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "governance_drop_duplicate_paragraphs_min_occurrences": 3,
                    "governance_trim_references": True,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:code_repo",
            name="代码仓库（保留格式 + secrets 脱敏）",
            description="适用于代码/配置/README：保留换行与缩进，避免误删；可选去掉代码块行号与 secrets 脱敏。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": False,
                    "governance_remove_noise_lines": False,
                    "governance_unwrap_lines": False,
                    # Only drop truly global boilerplate (license headers) when many docs share it.
                    "governance_remove_common_lines": True,
                    "governance_common_lines_min_docs": 8,
                    "governance_common_lines_min_ratio": 0.75,
                    "governance_strip_code_line_numbers": True,
                    "governance_secrets_redact": True,
                    "governance_secrets_mode": "mask",
                    "governance_secrets_mask": DEFAULT_GOVERNANCE_SECRETS_MASK,
                    "governance_max_blank_lines": 2,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:structured_data",
            name="结构化数据（CSV/JSON/日志型）",
            description="适用于 CSV/JSON/日志等行式数据：保留行边界，轻量去噪；避免过度合并断行。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": False,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": False,
                    "governance_remove_common_lines": False,
                    "governance_max_blank_lines": 1,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:chat_exports",
            name="聊天记录导出（Slack/Teams）",
            description="适用于 Slack/Teams 等聊天导出：去导出头尾/系统提示，保留消息行边界。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": False,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": False,
                    "governance_remove_common_lines": False,
                    "governance_remove_boilerplate": True,
                    "governance_rule_packs": ["chat_export_noise"],
                    "governance_max_blank_lines": 1,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:metadata_enrich",
            name="元数据增强（frontmatter/语言/关键词）",
            description="适用于需要检索增强的文档：提取/剥离 frontmatter、语言检测、关键词抽取（best-effort）。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_extract_frontmatter": True,
                    "governance_strip_frontmatter": True,
                    "governance_detect_language": True,
                    "governance_language_min_chars": 200,
                    "governance_extract_keywords": True,
                    "governance_keywords_provider": "auto",
                    "governance_keywords_top_k": 12,
                    "governance_keywords_max_chars": 60_000,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:quality_gate_quarantine",
            name="质量门禁（低密度/大纲-only → 隔离）",
            description="适用于批量入库：对疑似无正文/低信息密度文档触发过滤，并进入隔离队列以便人工复核。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_drop_outline_only": True,
                    "governance_drop_outline_min_content_chars": 200,
                    "governance_drop_outline_max_heading_ratio": 0.9,
                    "governance_drop_low_density": True,
                    "governance_drop_low_density_threshold": 0.12,
                    "governance_quarantine_on_drop": True,
                    # Parse quality gate (PDF+auto): retry alternative backends; quarantine when still low-signal.
                    "parse_fallback_enabled": True,
                    "parse_fallback_min_content_chars": 120,
                    "parse_fallback_max_retries": 1,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:pii_secrets_quarantine",
            name="PII/Secrets 合规门禁（命中即隔离）",
            description="适用于企业合规场景：启用 PII/Secrets 掩码，并在命中超过阈值时进入隔离队列以便人工复核。",
            payload=_p(
                input_formats=["markdown", "html"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_pii_anonymize": True,
                    "governance_pii_mode": "mask",
                    "governance_pii_mask": "[REDACTED]",
                    # 0 means "any hit triggers quarantine" (best-effort heuristics).
                    "governance_pii_max_hits": 0,
                    "governance_secrets_redact": True,
                    "governance_secrets_mode": "mask",
                    "governance_secrets_mask": DEFAULT_GOVERNANCE_SECRETS_MASK,
                    "governance_secrets_max_hits": 0,
                    "governance_quarantine_on_drop": True,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:html_xpath_main",
            name="网页 XPath 定位正文（默认 //main）",
            description="适用于结构稳定的网站：优先用 XPath 抽正文（默认 //main，未命中则回退到可读性提取）。",
            payload=_p(
                input_formats=["html", "markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": False,
                    "governance_remove_common_lines": False,
                    "governance_remove_boilerplate": True,
                    "governance_remove_images": "decorative",
                    "governance_normalize_urls": True,
                    "governance_normalize_urls_strip_tracking": True,
                    "governance_html_xpath": "//main",
                },
            ),
        ),
    ]


def builtin_profile_to_out(p: BuiltinGovernanceProfile) -> GovernanceProfileOut:
    return GovernanceProfileOut(
        id=None,
        key=p.key,
        name=p.name,
        description=p.description,
        is_system=True,
        payload=p.payload,
        created_at=None,
        updated_at=None,
    )
