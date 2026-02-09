from __future__ import annotations


def test_generate_dictionary_expansions_is_bounded_and_auditable() -> None:
    from app.query.expand import generate_dictionary_expansions

    expansions, meta = generate_dictionary_expansions(
        query="SLO SSO",
        rules={
            "SLO": [
                "service level objective",
                "service-level objective",
                "service level objectives",
            ],
            "SSO": [
                "single sign-on",
                "single sign on",
                "single sign-on",  # duplicate
            ],
        },
        max_expansions_total=5,
        max_expansions_per_rule=1,
    )

    assert [e.get("expanded_text") for e in expansions] == [
        "service level objective SSO",
        "SLO single sign-on",
    ]
    assert all("source_rule_id" in e for e in expansions)
    assert all("weight" in e for e in expansions)
    assert all("expanded_text" in e for e in expansions)

    assert meta.get("enabled") is True
    assert meta.get("used") is True
    assert int(meta.get("generated") or 0) == 2


def test_generate_dictionary_expansions_dedups_ascii_case_insensitive() -> None:
    from app.query.expand import generate_dictionary_expansions

    expansions, meta = generate_dictionary_expansions(
        query="SLO",
        rules={"SLO": ["service level objective", "Service Level Objective", "service level objective"]},
        max_expansions_total=10,
        max_expansions_per_rule=10,
    )

    assert [e.get("expanded_text") for e in expansions] == ["service level objective"]
    assert meta.get("used") is True

