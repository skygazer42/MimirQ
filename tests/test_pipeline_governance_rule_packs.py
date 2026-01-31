from app.services.pipeline_config import build_pipeline_metadata, parse_pipeline_from_metadata, resolve_pipeline_options
from app.types.pipeline import PipelineOptions


def test_pipeline_metadata_roundtrip_governance_rule_packs_sanitizes_and_dedupes():
    opts = PipelineOptions(
        governance_rule_packs=[
            " web_cookie_banners ",
            "",
            None,  # type: ignore[list-item]
            "email_disclaimer",
            "WEB_COOKIE_BANNERS",
        ]
    )

    meta = build_pipeline_metadata(opts)
    parsed = parse_pipeline_from_metadata({"pipeline": meta})

    assert parsed.governance_rule_packs == ["web_cookie_banners", "email_disclaimer"]


def test_resolve_pipeline_options_includes_governance_rule_packs():
    eff = resolve_pipeline_options(PipelineOptions(governance_rule_packs=["email_disclaimer"]))
    assert eff.governance_rule_packs == ["email_disclaimer"]

