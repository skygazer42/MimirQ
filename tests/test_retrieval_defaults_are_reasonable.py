from __future__ import annotations


def test_retrieval_defaults_are_reasonable_for_mid_scale() -> None:
    """
    Guardrail: keep default retrieval knobs in a sane range for mid-scale corpora.

    Rationale:
    - Too-low `top_k` hurts recall and makes the system feel "random".
    - Too-high `top_k` / fetch multipliers explode latency and token cost.
    """
    from app.core.config import Settings

    defaults = Settings.model_fields

    top_k = int(defaults["RETRIEVAL_TOP_K"].default)
    mmr_fetch_multiplier = int(defaults["RETRIEVAL_MMR_FETCH_K_MULTIPLIER"].default)
    rrf_k = int(defaults["RETRIEVAL_RRF_K"].default)

    assert 8 <= top_k <= 20
    assert 2 <= mmr_fetch_multiplier <= 8
    assert 10 <= rrf_k <= 200

    # Derived guardrail: MMR mode over-fetch must stay bounded.
    assert top_k * mmr_fetch_multiplier <= 80
