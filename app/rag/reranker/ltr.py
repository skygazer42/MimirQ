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


import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from app.rag.core.hashing import stable_hash
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult

_MANIFEST_SCHEMA_V1 = "mimirq.ltr_model_manifest.v1"
_FEATURE_SPEC_FINGERPRINT_SCHEMA_V1 = "mimirq.ltr_feature_spec.v1"
_BINARY_LOGISTIC_OBJECTIVE = "binary:logistic"


@dataclass(frozen=True)
class LTRFeatureSpec:
    schema: str
    feature_names: tuple[str, ...]

    @staticmethod
    def v1() -> "LTRFeatureSpec":
        """Feature spec v1 (stable ordering, used by existing models)."""
        return LTRFeatureSpec(
            schema="mimirq.ltr_features.v1",
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
            ),
        )

    @staticmethod
    def v2() -> "LTRFeatureSpec":
        """
        Feature spec v2: v1 + KG ranking features.

        Notes:
        - v2 is opt-in to avoid breaking existing LTR model artifacts (feature count must match).
        - KG features are low-cardinality and do not include scope identifiers.
        """
        base = list(LTRFeatureSpec.v1().feature_names)
        base.extend(
            [
                "kg_pagerank",
                "kg_shared_events",
                "kg_path_length",
                "kg_edge_conf_low",
                "kg_edge_conf_mid",
                "kg_edge_conf_high",
                "kg_evidence_anchored",
            ]
        )
        return LTRFeatureSpec(schema="mimirq.ltr_features.v2", feature_names=tuple(base))

    @staticmethod
    def v3() -> "LTRFeatureSpec":
        """
        Feature spec v3: v2 + ranking-critical fusion/field-aware signals.

        Added signals:
        - field_aware_boost / field_signal_*: retrieval-time field-aware recall hints.
        - keyword_max_score / vector_keyword_gap: dense-vs-keyword agreement/conflict signal.
        - multi_channel_hits: channel support count (vector/bm25/lexical/sparse).
        """
        base = list(LTRFeatureSpec.v2().feature_names)
        base.extend(
            [
                "field_aware_boost",
                "field_signal_title",
                "field_signal_heading",
                "keyword_max_score",
                "vector_keyword_gap",
                "multi_channel_hits",
            ]
        )
        return LTRFeatureSpec(schema="mimirq.ltr_features.v3", feature_names=tuple(base))

    @staticmethod
    def from_version(version: int | str | None) -> "LTRFeatureSpec":
        try:
            v = int(version) if version is not None else 1
        except Exception:
            v = 1
        if v >= 3:
            return LTRFeatureSpec.v3()
        if v >= 2:
            return LTRFeatureSpec.v2()
        return LTRFeatureSpec.v1()

    @staticmethod
    def default() -> "LTRFeatureSpec":
        # Keep default pinned to v1 to preserve compatibility with existing artifacts.
        return LTRFeatureSpec.v1()


def build_ltr_feature_spec_fingerprint(
    *,
    spec: LTRFeatureSpec,
    version: int | str | None,
    schema: str = _FEATURE_SPEC_FINGERPRINT_SCHEMA_V1,
) -> dict[str, Any]:
    """
    Build a stable, versioned fingerprint for an LTR feature spec.

    Why:
    - Offline training/eval runs and model manifests should be comparable across environments.
    - Fingerprints make it easy to detect accidental feature order/count drift.
    """
    try:
        v = int(version) if version is not None else 1
    except Exception:
        v = 1

    payload = {
        "schema": str(schema or _FEATURE_SPEC_FINGERPRINT_SCHEMA_V1),
        "version": int(v),
        "feature_schema": str(getattr(spec, "schema", "") or ""),
        "feature_names": list(getattr(spec, "feature_names", ()) or ()),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    digest = stable_hash(raw, length=32)
    return {**payload, "hash": digest}


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
    _ = query
    meta = candidate.metadata or {}
    role = meta.get("retrieval_role")
    role_oh = _role_one_hot(str(role) if role is not None else None)

    vector_score = _as_float(meta.get("vector_score"))
    bm25_score = _as_float(meta.get("bm25_score"))
    lexical_score = _as_float(meta.get("lexical_score"))
    sparse_score = _as_float(meta.get("sparse_score"))
    base_score = _as_float(meta.get("score"))

    field_aware_boost = _as_float(meta.get("field_aware_boost"))
    field_signal = str(meta.get("field_aware_signal") or "").strip().lower()
    field_signal_title = 1.0 if field_signal == "title" else 0.0
    field_signal_heading = 1.0 if field_signal == "heading" else 0.0

    keyword_max_score = max(float(bm25_score), float(lexical_score), float(sparse_score))
    vector_keyword_gap = float(vector_score) - float(keyword_max_score)
    multi_channel_hits = float(
        sum(
            1
            for s in (vector_score, bm25_score, lexical_score, sparse_score)
            if float(s) > 0.0
        )
    )

    f_map: dict[str, float] = {
        "vector_score": float(vector_score),
        "bm25_score": float(bm25_score),
        "lexical_score": float(lexical_score),
        "sparse_score": float(sparse_score),
        "base_score": base_score,
        "field_aware_boost": float(field_aware_boost),
        "field_signal_title": float(field_signal_title),
        "field_signal_heading": float(field_signal_heading),
        "keyword_max_score": float(keyword_max_score),
        "vector_keyword_gap": float(vector_keyword_gap),
        "multi_channel_hits": float(multi_channel_hits),
        # KG ranking signals (optional; present only for KG-linked candidates).
        "kg_pagerank": _as_float(meta.get("kg_pagerank")),
        "kg_shared_events": _as_float(meta.get("kg_shared_events")),
        "kg_path_length": _as_float(meta.get("kg_path_length")),
        "kg_edge_conf_low": _as_float(meta.get("kg_edge_conf_low")),
        "kg_edge_conf_mid": _as_float(meta.get("kg_edge_conf_mid")),
        "kg_edge_conf_high": _as_float(meta.get("kg_edge_conf_high")),
        "kg_evidence_anchored": _as_float(meta.get("kg_evidence_anchored")),
        **role_oh,
    }

    return [_as_float(f_map.get(name)) for name in spec.feature_names]


def train_ltr_xgboost_model(
    *,
    training_rows: list[dict[str, Any]],
    spec: LTRFeatureSpec,
    num_boost_round: int = 50,
    seed: int = 42,
    objective: str = _BINARY_LOGISTIC_OBJECTIVE,
    group_sizes: Sequence[int] | None = None,
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
    if group_sizes is not None:
        sizes = [int(x) for x in group_sizes if x is not None]
        if not sizes or any(s <= 0 for s in sizes):
            raise ValueError("group_sizes must be a non-empty sequence of positive integers")
        if sum(sizes) != int(x_arr.shape[0]):
            raise ValueError("group_sizes must sum to the number of training rows")
        # Grouped ranking objective support.
        dtrain.set_group(sizes)

    obj = str(objective or _BINARY_LOGISTIC_OBJECTIVE)
    params = {
        "objective": obj,
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
        "eval_metric": ("ndcg@10" if obj.startswith("rank:") else "logloss"),
    }

    # Newer xgboost versions infer base_score from training labels. For tiny
    # datasets it can become exactly 0/1 (e.g., all-positive labels), which is
    # invalid for logistic loss.
    if obj in {_BINARY_LOGISTIC_OBJECTIVE, "reg:logistic"}:
        eps = 1e-6
        mean_label = float(y_arr.mean()) if y_arr.size else 0.5
        params["base_score"] = min(max(mean_label, eps), 1.0 - eps)

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
        manifest_path: str | None = None,
    ) -> None:
        import xgboost as xgb

        path = str(model_path or "").strip()
        if not path:
            raise ValueError("LTRReranker requires model_path")

        model_p = Path(path)
        if not model_p.exists():
            raise ValueError(f"LTR model file not found: {model_p}")

        self._model_path = path
        self._spec = spec or LTRFeatureSpec.default()

        # Human-friendly model id for telemetry (avoid leaking full paths).
        self._model_id = model_p.name

        self._manifest_path: str | None = None
        self._manifest: dict[str, Any] | None = None

        mp = str(manifest_path or "").strip() if manifest_path is not None else ""
        sidecar = model_p.with_suffix(".manifest.json")
        if mp:
            self._manifest_path = mp
        elif sidecar.exists():
            self._manifest_path = str(sidecar)

        if self._manifest_path:
            man_p = Path(self._manifest_path)
            try:
                raw = json.loads(man_p.read_text(encoding="utf-8"))
            except Exception as exc:
                raise ValueError(f"failed to read LTR manifest: {man_p}") from exc
            if not isinstance(raw, dict):
                raise ValueError("LTR manifest must be a JSON object")

            schema = str(raw.get("schema") or "").strip()
            if schema != _MANIFEST_SCHEMA_V1:
                raise ValueError(f"LTR manifest schema mismatch: {schema or '<missing>'} (expected: {_MANIFEST_SCHEMA_V1})")

            feature_schema = str(raw.get("feature_schema") or "").strip()
            if feature_schema != str(self._spec.schema or "").strip():
                raise ValueError(
                    f"LTR manifest feature_schema mismatch: {feature_schema or '<missing>'} (expected: {self._spec.schema})"
                )

            names = raw.get("feature_names")
            if not isinstance(names, list):
                raise ValueError("LTR manifest feature_names must be a list")
            names_norm = [str(x) for x in names if x is not None]
            if names_norm != list(self._spec.feature_names):
                raise ValueError("LTR manifest feature_names mismatch (feature order/count must match spec)")

            # Optional hash pin: if present, ensure the model bytes match.
            sha = str(raw.get("model_sha256") or "").strip()
            if sha:
                try:
                    model_bytes = model_p.read_bytes()
                except Exception as exc:
                    raise ValueError(f"failed to read LTR model for sha256 check: {model_p}") from exc
                digest = hashlib.sha256(model_bytes).hexdigest()
                if digest != sha:
                    raise ValueError("LTR manifest model_sha256 mismatch (model file content changed)")

            # Keep a copy for debugging/telemetry (do not include high-cardinality training data).
            self._manifest = {
                "schema": schema,
                "feature_schema": feature_schema,
                "feature_names": list(names_norm),
                "model_sha256": sha or None,
            }
            if sha:
                # Stable across deployments; safer than full paths in traces/metrics.
                self._model_id = f"sha256:{sha[:12]}"

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
            return RerankResult(ordered_ids=[], score_map={}, provider="ltr", model_used=self._model_id)

        try:
            x_rows: list[list[float]] = []
            ids: list[str] = []
            for c in candidates:
                cid = str(c.id or "").strip()
                if not cid:
                    continue
                ids.append(cid)
                x_rows.append(extract_ltr_features(spec=self._spec, query=query, candidate=c))

            if not x_rows:
                return RerankResult(ordered_ids=[], score_map={}, provider="ltr", model_used=self._model_id)

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
                model_used=self._model_id,
                stats={"ok": True, "manifest": self._manifest},
            )
        except Exception as exc:
            # Online safeguard: rerank failures should be a no-op rather than breaking retrieval.
            return RerankResult(
                ordered_ids=[],
                score_map={},
                provider="ltr",
                model_used=self._model_id,
                stats={"ok": False, "error": str(exc)[:200], "manifest": self._manifest},
            )
