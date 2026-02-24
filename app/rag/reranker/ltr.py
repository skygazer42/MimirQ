"""
Learning-to-Rank (LTR) reranker (xgboost scaffold).

This module provides:
- a stable feature spec (ordered feature_names)
- an xgboost-based training helper (offline)
- an xgboost-based reranker (online inference)

Design constraints:
- Deterministic and testable without external services.
- Model loading must be explicit (model_path required) so defaults do not change behavior.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult


@dataclass(frozen=True)
class LTRFeatureSpec:
    feature_names: tuple[str, ...]

    @staticmethod
    def default() -> "LTRFeatureSpec":
        # Keep this list stable. Training and inference must use the same ordering.
        return LTRFeatureSpec(
            feature_names=(
                "vector_score",
                "bm25_score",
                "lexical_score",
                "sparse_score",
                "base_score",
                # Retrieval-role one-hot (used when reranking post-fusion in orchestrator).
                "role_main",
                "role_alias",
                "role_dict",
                "role_clause",
                "role_mq",
                "role_subq",
                "role_hyde",
                "role_kgq",
                "role_kg",
                "role_tag",
            )
        )


def _as_float(v: Any) -> float:
    try:
        if v is None:
            return 0.0
        return float(v)
    except Exception:
        return 0.0


def _role_one_hot(role: str | None) -> dict[str, float]:
    r = str(role or "").strip().lower()
    if not r:
        r = "main"
    keys = (
        "main",
        "alias",
        "dict",
        "clause",
        "mq",
        "subq",
        "hyde",
        "kgq",
        "kg",
        "tag",
    )
    out = {f"role_{k}": 0.0 for k in keys}
    if r in keys:
        out[f"role_{r}"] = 1.0
    return out


def extract_ltr_features(*, spec: LTRFeatureSpec, query: str, candidate: RerankCandidate) -> list[float]:
    """
    Extract an ordered feature vector for a candidate.

    Feature sources:
    - candidate.metadata: scalar scores and retrieval_role
    - query: reserved for future query-dependent features (kept for API stability)
    """
    meta = candidate.metadata or {}
    role = meta.get("retrieval_role")
    role_oh = _role_one_hot(str(role) if role is not None else None)

    base_score = _as_float(meta.get("score"))
    f_map: dict[str, float] = {
        "vector_score": _as_float(meta.get("vector_score")),
        "bm25_score": _as_float(meta.get("bm25_score")),
        "lexical_score": _as_float(meta.get("lexical_score")),
        "sparse_score": _as_float(meta.get("sparse_score")),
        "base_score": base_score,
        **role_oh,
    }

    return [_as_float(f_map.get(name)) for name in spec.feature_names]


def train_ltr_xgboost_model(
    *,
    training_rows: list[dict[str, Any]],
    spec: LTRFeatureSpec,
    num_boost_round: int = 50,
    seed: int = 42,
) -> bytes:
    """
    Train a tiny xgboost model and return its serialized bytes.

    Input rows shape:
      {"features": {name: value, ...}, "label": 0|1}
    """
    import xgboost as xgb

    x_rows: list[list[float]] = []
    y: list[float] = []
    for row in training_rows or []:
        if not isinstance(row, dict):
            continue
        feats = row.get("features") if isinstance(row.get("features"), dict) else {}
        label = row.get("label")
        x_rows.append([_as_float(feats.get(name)) for name in spec.feature_names])
        y.append(float(int(label or 0)))

    if not x_rows:
        raise ValueError("training_rows is empty")

    x_arr = np.asarray(x_rows, dtype=np.float32)
    y_arr = np.asarray(y, dtype=np.float32)

    dtrain = xgb.DMatrix(x_arr, label=y_arr, feature_names=list(spec.feature_names))
    params = {
        "objective": "binary:logistic",
        "max_depth": 3,
        "eta": 0.3,
        "subsample": 1.0,
        "colsample_bytree": 1.0,
        # Default min_child_weight=1 can block splits on tiny training sets
        # (sum of Hessians per leaf is often < 1). Keep it low so unit tests can
        # train meaningful models on a handful of examples.
        "min_child_weight": 0.0,
        "gamma": 0.0,
        "seed": int(seed),
        "eval_metric": "logloss",
    }

    booster = xgb.train(params=params, dtrain=dtrain, num_boost_round=max(1, int(num_boost_round or 0)))
    raw = booster.save_raw(raw_format="json")
    return bytes(raw)


class LTRReranker(BaseReranker):
    """
    XGBoost-based LTR reranker (inference).

    Provider id: "ltr" (see app.rag.reranker.factory.get_reranker)
    """

    def __init__(
        self,
        *,
        model_path: str,
        spec: LTRFeatureSpec | None = None,
    ) -> None:
        import xgboost as xgb

        path = str(model_path or "").strip()
        if not path:
            raise ValueError("LTRReranker requires model_path")

        self._model_path = path
        self._spec = spec or LTRFeatureSpec.default()

        booster = xgb.Booster()
        booster.load_model(path)
        self._booster = booster

    def rerank(
        self,
        query: str,
        candidates: Sequence[RerankCandidate],
        **_kwargs: Any,
    ) -> RerankResult:
        if not candidates:
            return RerankResult(ordered_ids=[], score_map={}, provider="ltr", model_used=self._model_path)

        x_rows: list[list[float]] = []
        ids: list[str] = []
        for c in candidates:
            cid = str(c.id or "").strip()
            if not cid:
                continue
            ids.append(cid)
            x_rows.append(extract_ltr_features(spec=self._spec, query=query, candidate=c))

        if not x_rows:
            return RerankResult(ordered_ids=[], score_map={}, provider="ltr", model_used=self._model_path)

        import xgboost as xgb

        dmat = xgb.DMatrix(np.asarray(x_rows, dtype=np.float32), feature_names=list(self._spec.feature_names))
        preds = self._booster.predict(dmat)

        scored = list(zip(ids, [float(p) for p in preds], strict=False))
        scored.sort(key=lambda x: (-x[1], x[0]))
        ordered_ids = [cid for cid, _s in scored]
        score_map = {cid: float(s) for cid, s in scored}
        return RerankResult(
            ordered_ids=ordered_ids,
            score_map=score_map,
            provider="ltr",
            model_used=self._model_path,
        )
