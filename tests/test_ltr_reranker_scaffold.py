from __future__ import annotations

from pathlib import Path

from app.rag.reranker.factory import get_reranker
from app.rag.reranker.ltr import LTRFeatureSpec, LTRReranker, train_ltr_xgboost_model
from app.rag.reranker.types import RerankCandidate


def test_ltr_reranker_trains_and_reranks(tmp_path: Path) -> None:
    """
    LTR scaffold:
    - Train a tiny xgboost model from deterministic examples
    - Load it via LTRReranker
    - Ensure it reranks candidates by predicted relevance
    """
    spec = LTRFeatureSpec.default()

    # Training data: prefer higher vector_score.
    rows = []
    for score, label in ((0.9, 1), (0.8, 1), (0.2, 0), (0.1, 0)):
        feats = dict.fromkeys(spec.feature_names, 0.0)
        feats["vector_score"] = float(score)
        feats["role_main"] = 1.0
        rows.append({"features": feats, "label": int(label)})

    model_path = tmp_path / "model.json"
    model_bytes = train_ltr_xgboost_model(
        training_rows=rows,
        spec=spec,
        num_boost_round=10,
        seed=42,
    )
    model_path.write_bytes(model_bytes)

    reranker = LTRReranker(model_path=str(model_path), spec=spec)
    out = reranker.rerank(
        query="q",
        candidates=[
            RerankCandidate(id="a", text="doc a", metadata={"vector_score": 0.9}),
            RerankCandidate(id="b", text="doc b", metadata={"vector_score": 0.1}),
        ],
    )

    assert out.ordered_ids[0] == "a"
    assert out.score_map["a"] > out.score_map["b"]


def test_factory_resolves_ltr_provider(tmp_path: Path) -> None:
    spec = LTRFeatureSpec.default()
    model_path = tmp_path / "model.json"
    model_bytes = train_ltr_xgboost_model(
        training_rows=[
            {
                "features": {k: (1.0 if k in {"vector_score", "role_main"} else 0.0) for k in spec.feature_names},
                "label": 1,
            },
            {"features": {k: (1.0 if k == "role_main" else 0.0) for k in spec.feature_names}, "label": 0},
        ],
        spec=spec,
        num_boost_round=5,
        seed=123,
    )
    model_path.write_bytes(model_bytes)

    inst = get_reranker("ltr", model_path=str(model_path), feature_names=list(spec.feature_names))
    assert inst.__class__.__name__.lower().startswith("ltr")
