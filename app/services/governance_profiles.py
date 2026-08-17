"""
Governance profile registry (built-in profiles) and helpers.

This module intentionally keeps profiles declarative:
- No executable code, no dynamic imports.
- Profiles are used to patch pipeline options and provide additional regex rules.
"""

import re
from dataclasses import dataclass

from app.api.schemas.governance_profile import GovernanceProfileOut, GovernanceProfilePayload, RegexRuleModel
from app.core.regex_safety import DEFAULT_ALLOWED_FLAG_BITS, validate_regex_rules
from app.services.pipeline_patch_validator import normalize_document_pipeline_patch

PROFILE_KEY_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.:\-]{0,99}$")
MAX_PROFILE_RULES = 60
MAX_PROFILE_RULE_PATTERN = 600
MAX_PROFILE_RULE_REPL = 2000

DEFAULT_GOVERNANCE_SECRETS_MASK = "[SECRET]"
DEFAULT_GOVERNANCE_PII_MASK = "[REDACTED]"
LEGAL_COMPLIANCE_PROFILE_KEY = "builtin:legal_compliance"
WIKI_LONGFORM_PROFILE_KEY = "builtin:wiki_longform"


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
    return normalize_document_pipeline_patch(
        raw,
        field_label="payload.pipeline_patch",
        invalid_message="invalid payload.pipeline_patch",
    )


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
    for fmt in payload.input_formats or []:
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
    extends: str | None = None,
) -> GovernanceProfilePayload:
    return GovernanceProfilePayload(
        version="1",
        extends=extends,
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
            key=LEGAL_COMPLIANCE_PROFILE_KEY,
            name="合规脱敏（PII/密钥）",
            description="适用于可能包含邮箱/电话/Token 的文档：启用 PII 匿名化与密钥脱敏。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_pii_anonymize": True,
                    "governance_pii_mode": "mask",
                    "governance_pii_mask": DEFAULT_GOVERNANCE_PII_MASK,
                    "governance_secrets_redact": True,
                    "governance_secrets_mode": "mask",
                    "governance_secrets_mask": DEFAULT_GOVERNANCE_SECRETS_MASK,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key=WIKI_LONGFORM_PROFILE_KEY,
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
                    "governance_pii_mask": DEFAULT_GOVERNANCE_PII_MASK,
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
        # ============================================================
        # 垂直行业扩展（中文金融 / 医疗政法 / 企业 Wiki 平台）
        # ============================================================
        # ---------- C. 金融报告 ----------
        BuiltinGovernanceProfile(
            key="builtin:cn_a_share_annual_report",
            name="A 股年报 PDF（表格+口径）",
            description=(
                "适用于 A 股上市公司年报/季报 PDF：保留表格结构、去重复页眉页脚、剥离董事会承诺/披露免责声明等噪声。"
            ),
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
                    "governance_drop_duplicate_paragraphs_min_chars": 30,
                    "governance_normalize_tables": True,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "cn_finance_report_artifacts",
                        "pdf_header_footer_cn",
                        "pdf_watermark",
                    ],
                    "parse_fallback_enabled": True,
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:cn_prospectus",
            name="A 股招股书（目录裁剪+风险因素去重）",
            description="适用于招股说明书/募集说明书：去目录、去重复风险因素段、保留法律披露承诺。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "governance_drop_duplicate_paragraphs_min_occurrences": 2,
                    "governance_drop_duplicate_paragraphs_min_chars": 60,
                    "governance_normalize_tables": True,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "cn_finance_report_artifacts",
                        "pdf_header_footer_cn",
                    ],
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:bank_compliance_report",
            name="银行/金融机构合规报告（强 PII）",
            description=(
                "适用于银行/券商/保险合规报告：继承 legal_compliance 做 PII/密钥脱敏，"
                "叠加财报披露噪声移除与表格规范化。"
            ),
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_pii_anonymize": True,
                    "governance_pii_mode": "mask",
                    "governance_pii_mask": DEFAULT_GOVERNANCE_PII_MASK,
                    "governance_secrets_redact": True,
                    "governance_secrets_mode": "mask",
                    "governance_secrets_mask": DEFAULT_GOVERNANCE_SECRETS_MASK,
                    "governance_normalize_tables": True,
                    "governance_remove_common_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_rule_packs": [
                        "cn_finance_report_artifacts",
                        "pdf_watermark",
                    ],
                },
                extends=LEGAL_COMPLIANCE_PROFILE_KEY,
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:insurance_policy_pdf",
            name="保险合同 PDF（条款结构友好）",
            description="适用于保险条款/合同 PDF：修复断行、保留条款序号与附录，规范化表格，避免裁剪正文末尾。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_normalize_tables": True,
                    "governance_trim_references": False,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "pdf_watermark",
                        "pdf_header_footer_cn",
                    ],
                },
            ),
        ),
        # ---------- D. 医疗 / 政务 / 法律 ----------
        BuiltinGovernanceProfile(
            key="builtin:medical_emr",
            name="电子病历（强 PHI 脱敏）",
            description="适用于医院电子病历/检查报告/处方：继承 legal_compliance 做 PII 脱敏，叠加医疗表头噪声移除。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_pii_anonymize": True,
                    "governance_pii_mode": "mask",
                    "governance_pii_mask": DEFAULT_GOVERNANCE_PII_MASK,
                    "governance_secrets_redact": True,
                    "governance_secrets_mode": "mask",
                    "governance_secrets_mask": DEFAULT_GOVERNANCE_SECRETS_MASK,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "cn_medical_record_artifacts",
                        "pdf_header_footer_cn",
                    ],
                },
                extends=LEGAL_COMPLIANCE_PROFILE_KEY,
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:government_redhead",
            name="政府红头公文（保留章节）",
            description="适用于党政机关红头公文/通知/批复：保留章节编号和正文目录，清理抄送/印发/签发块。",
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": False,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "cn_gov_redhead_artifacts",
                        "pdf_header_footer_cn",
                        "pdf_watermark",
                    ],
                },
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:china_law_regulation",
            name="中国法规条例（条/款/项结构）",
            description=(
                "适用于中国法律法规/行政条例/部门规章：继承 policy_manual_pdf，保留附则与条款编号，强化重复段落去除。"
            ),
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
                    "governance_normalize_tables": True,
                    "governance_trim_references": False,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "pdf_header_footer_cn",
                        "pdf_watermark",
                    ],
                },
                extends="builtin:policy_manual_pdf",
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:court_judgment",
            name="法院判决书（裁判文书脱敏）",
            description=(
                "适用于裁判文书网/法院判决书：继承 legal_compliance 做当事人 PII 脱敏，"
                "叠加签发/印发块清理与重复段去除。"
            ),
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_pii_anonymize": True,
                    "governance_pii_mode": "mask",
                    "governance_pii_mask": DEFAULT_GOVERNANCE_PII_MASK,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "governance_drop_duplicate_paragraphs_min_occurrences": 3,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "cn_gov_redhead_artifacts",
                        "pdf_header_footer_cn",
                    ],
                },
                extends=LEGAL_COMPLIANCE_PROFILE_KEY,
            ),
        ),
        # ---------- E. 企业 Wiki / 文档平台 ----------
        BuiltinGovernanceProfile(
            key="builtin:confluence_enterprise",
            name="Confluence 企业导出（强化）",
            description=(
                "适用于企业级 Confluence 导出：继承 wiki_longform，叠加 Confluence/Jira 噪声、导航栏、邮件签名清理。"
            ),
            payload=_p(
                input_formats=["markdown", "html"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_remove_boilerplate": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "governance_drop_duplicate_paragraphs_min_occurrences": 3,
                    "governance_normalize_urls": True,
                    "governance_normalize_urls_strip_tracking": True,
                    "governance_rule_packs": [
                        "confluence_jira_noise",
                        "web_navigation",
                        "email_disclaimer",
                    ],
                },
                extends=WIKI_LONGFORM_PROFILE_KEY,
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:sharepoint_o365",
            name="SharePoint / Office 365 导出",
            description=(
                "适用于 SharePoint/OneDrive/Office 365 导出文档：继承 wiki_longform，"
                "叠加样板移除、装饰图剥离、URL 规范化。"
            ),
            payload=_p(
                input_formats=["markdown", "html"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_remove_boilerplate": True,
                    "governance_remove_images": "decorative",
                    "governance_normalize_urls": True,
                    "governance_normalize_urls_strip_tracking": True,
                    "governance_rule_packs": [
                        "web_navigation",
                        "email_disclaimer",
                        "markdown_export_noise",
                    ],
                },
                extends=WIKI_LONGFORM_PROFILE_KEY,
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:notion_database",
            name="Notion 数据库 + 文档导出",
            description=(
                "适用于 Notion markdown 导出（含 database properties）：继承 wiki_longform，规范化属性表格并合并断行。"
            ),
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
                    "governance_rule_packs": [
                        "notion_export_noise",
                        "markdown_export_noise",
                    ],
                },
                extends=WIKI_LONGFORM_PROFILE_KEY,
            ),
        ),
        BuiltinGovernanceProfile(
            key="builtin:feishu_lark_doc",
            name="飞书 / Lark 知识库",
            description=(
                "适用于飞书/Lark 知识库导出：继承 wiki_longform，叠加飞书特有噪声（导出标识/最后编辑/协作者）清理。"
            ),
            payload=_p(
                input_formats=["markdown"],
                pipeline_patch={
                    "governance_enabled": True,
                    "governance_remove_toc_lines": True,
                    "governance_remove_noise_lines": True,
                    "governance_unwrap_lines": True,
                    "governance_remove_common_lines": True,
                    "governance_drop_duplicate_paragraphs": True,
                    "governance_normalize_urls": True,
                    "governance_max_blank_lines": 1,
                    "governance_rule_packs": [
                        "feishu_lark_noise",
                        "web_navigation",
                    ],
                },
                extends=WIKI_LONGFORM_PROFILE_KEY,
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
