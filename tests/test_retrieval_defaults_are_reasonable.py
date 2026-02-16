from __future__ import annotations


def test_retrieval_defaults_are_reasonable_for_mid_scale() -> None:
    """
    Guardrail: keep default retrieval knobs in a sane range for mid-scale corpora.

    Rationale:
    - Too-low `top_k` hurts recall and makes the system feel "random".
    - Too-high `top_k` / fetch multipliers explode latency and token cost.
    """
    from app.core.config import Settings

    s = Settings()

    assert 8 <= int(s.RETRIEVAL_TOP_K) <= 20
    assert 2 <= int(s.RETRIEVAL_MMR_FETCH_K_MULTIPLIER) <= 8
    assert 10 <= int(s.RETRIEVAL_RRF_K) <= 200

    # Derived guardrail: MMR mode over-fetch must stay bounded.
    assert int(s.RETRIEVAL_TOP_K) * int(s.RETRIEVAL_MMR_FETCH_K_MULTIPLIER) <= 80
