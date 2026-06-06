import pytest


def test_governance_profile_payload_rejects_unknown_pipeline_keys():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        input_formats=["markdown"],
        pipeline_patch={"totally_unknown_key": True},
        regex_rules=[],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_payload(payload)


def test_governance_profile_payload_rejects_suspicious_regex():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        input_formats=["markdown"],
        pipeline_patch={"governance_enabled": True},
        regex_rules=[{"pattern": "(.*)+", "repl": "", "flags": 0}],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_payload(payload)


def test_governance_profile_payload_normalizes_extends_ref():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        extends="  builtin:kb_default  ",
        input_formats=["markdown"],
        pipeline_patch={"governance_enabled": True},
        regex_rules=[],
    )

    out = validate_and_normalize_payload(payload)
    assert out.extends == "builtin:kb_default"


def test_governance_profile_payload_rejects_extends_with_control_chars():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        extends="builtin:kb_default\x00",
        input_formats=["markdown"],
        pipeline_patch={"governance_enabled": True},
        regex_rules=[],
    )

    with pytest.raises(ValueError):
        validate_and_normalize_payload(payload)


def test_governance_profile_payload_preserves_non_executable_processing_scripts():
    from app.api.schemas.governance_profile import GovernanceProfilePayload
    from app.services.governance_profiles import validate_and_normalize_payload

    payload = GovernanceProfilePayload(
        version="1",
        input_formats=["markdown"],
        pipeline_patch={"governance_enabled": True},
        regex_rules=[],
        processing_scripts=[
            {
                "name": "cleanup.py",
                "language": "python",
                "stage": "post_governance",
                "content": "def transform(text):\n    return text\n",
                "enabled": False,
            }
        ],
    )

    out = validate_and_normalize_payload(payload)

    assert len(out.processing_scripts) == 1
    assert out.processing_scripts[0].name == "cleanup.py"
    assert out.processing_scripts[0].enabled is False


def test_builtin_processing_script_templates_keep_generic_legacy_templates_without_task_specific_terms():
    from app.services.governance_processing_scripts import list_builtin_processing_scripts

    scripts = list_builtin_processing_scripts()
    keys = {script.key for script in scripts}
    joined = "\n".join(
        "\n".join(
            [
                script.key,
                script.name,
                script.description,
                script.content,
                " ".join(script.tags),
            ]
        )
        for script in scripts
    )
    user_visible_joined = "\n".join(
        "\n".join(
            [
                script.name,
                script.description,
                script.content,
                " ".join(script.tags),
            ]
        )
        for script in scripts
    )

    expected_legacy_keys = {
        "gov_qa_split_by_separator",
        "gov_qa_field_parse",
        "gov_item_field_parse",
        "gov_phone_normalize",
        "gov_url_unwrap",
        "gov_keyword_extract",
        "gov_qa_xlsx_header_align",
        "gov_term_canonicalize",
    }
    assert expected_legacy_keys.issubset(keys)
    for forbidden in (
        "常州",
        "经开区",
        "天宁区",
        "新北区",
        "公积金",
        "不动产",
        "一件事一次办",
        "12345QA",
        "0519",
        "苏服办",
    ):
        assert forbidden not in joined
    for forbidden in (
        "政务",
        "网上办事大厅",
        "政务网",
        "政务服务中心",
        "办事窗口",
        "行使层级",
        "办件类型",
        "法定办结时限",
        "承诺办结时限",
        "监督投诉方式",
        "办事链接",
    ):
        assert forbidden not in user_visible_joined


def test_builtin_governance_profiles_keep_common_vertical_and_source_presets_without_task_specific_terms():
    from app.services.governance_profiles import get_builtin_governance_profiles

    profiles = get_builtin_governance_profiles()
    keys = {profile.key for profile in profiles}
    joined = "\n".join(
        "\n".join(
            [
                profile.key,
                profile.name,
                profile.description,
                str(profile.payload.pipeline_patch),
            ]
        )
        for profile in profiles
    )

    for expected_key in {
        "builtin:government_redhead",
        "builtin:cn_a_share_annual_report",
        "builtin:cn_prospectus",
        "builtin:bank_compliance_report",
        "builtin:insurance_policy_pdf",
        "builtin:medical_emr",
        "builtin:china_law_regulation",
        "builtin:court_judgment",
        "builtin:confluence_enterprise",
        "builtin:sharepoint_o365",
        "builtin:notion_database",
        "builtin:feishu_lark_doc",
    }:
        assert expected_key in keys
    for forbidden in (
        "常州",
        "经开区",
        "天宁区",
        "新北区",
        "公积金",
        "不动产",
        "一件事一次办",
        "12345QA",
        "苏服办",
    ):
        assert forbidden not in joined


def test_platform_governance_rule_packs_keep_common_vertical_and_source_rules_without_task_specific_terms():
    from app.rag.preprocessing.rule_packs import GOVERNANCE_RULE_PACKS

    joined = "\n".join(
        [
            key
            + "\n"
            + "\n".join(f"{rule.pattern}\n{rule.repl}" for rule in rules)
            for key, rules in GOVERNANCE_RULE_PACKS.items()
        ]
    )

    for expected_key in {
        "cn_gov_redhead_artifacts",
        "cn_finance_report_artifacts",
        "cn_medical_record_artifacts",
        "confluence_jira_noise",
        "notion_export_noise",
        "feishu_lark_noise",
        "wechat_mp_noise",
    }:
        assert expected_key in GOVERNANCE_RULE_PACKS
    for forbidden in ("常州", "经开区", "天宁区", "新北区", "公积金", "不动产", "12345QA", "苏服办"):
        assert forbidden not in joined
