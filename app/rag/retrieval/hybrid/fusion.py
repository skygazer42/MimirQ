"""Channel fusion and lightweight reranking for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``). The
methods below run on the ``HybridRetriever`` instance via mixin inheritance.
"""

import math
from collections import Counter
from typing import Any

from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.retrieval.hybrid.common import (
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    _apply_exact_content_bonus_to_result,
    _float_or_default,
    logger,
)
from app.rag.retrieval.query_phrase_match import query_phrase_match


class FusionMixin:
    """Merges per-channel candidate lists and applies weight/MMR reranking."""

    def _merge_results(
        self,
        vector_results: list[dict[str, Any]],
        bm25_results: list[dict[str, Any]],
        lexical_results: list[dict[str, Any]] | None = None,
        sparse_results: list[dict[str, Any]] | None = None,
        query: str | None = None,
        alpha: float = 0.5,
        fusion_strategy: str | None = None,
        rrf_k: int | None = None,
        top_k: int | None = None,
    ) -> list[dict[str, Any]]:
        """Merge retrieval channel results into a single ranked list."""

        lexical_results = list(lexical_results or [])
        sparse_results = list(sparse_results or [])

        field_aware_enabled = bool(getattr(settings, "RETRIEVAL_FIELD_AWARE_RECALL_ENABLED", False))
        field_aware_title_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_TITLE_BOOST", 0.08) or 0.0))
        field_aware_heading_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_HEADING_BOOST", 0.05) or 0.0))
        field_aware_max_boost = max(0.0, float(getattr(settings, "RETRIEVAL_FIELD_AWARE_MAX_BOOST", 0.10) or 0.0))
        field_aware_title_boost = min(field_aware_title_boost, field_aware_max_boost)
        field_aware_heading_boost = min(field_aware_heading_boost, field_aware_max_boost)
        chunk_type_weighting_enabled = bool(getattr(settings, "RETRIEVAL_CHUNK_TYPE_WEIGHTING_ENABLED", False))
        chunk_type_match_boost = max(0.0, float(getattr(settings, "RETRIEVAL_CHUNK_TYPE_MATCH_BOOST", 0.08) or 0.0))

        def _resolve_chunk_type(result: dict[str, Any]) -> str:
            meta = result.get("metadata") or {}
            raw = str(
                meta.get("chunk_type")
                or meta.get("content_type")
                or meta.get("visual_kind")
                or ""
            ).strip().lower()
            if raw in {"text", "formula", "table", "code", "figure", "chart_data", "seal"}:
                return raw
            if raw == "chart":
                return "figure"
            role = str(meta.get("chunk_semantic_role") or "").strip().lower()
            if role == "code":
                return "code"
            if role == "table":
                return "table"
            return "text"

        def _resolve_query_chunk_type_signal(text: str | None) -> str | None:
            raw = str(text or "").strip().lower()
            if not raw:
                return None
            if any(token in raw for token in ("表格", "字段", "列", "schema", "table", "column")):
                return "table"
            if any(token in raw for token in ("公式", "latex", "equation", "math", "公式识别")):
                return "formula"
            if any(token in raw for token in ("代码", "sql", "python", "bash", "json", "yaml", "脚本", "code")):
                return "code"
            if any(token in raw for token in ("图表", "曲线", "趋势图", "chart", "plot", "graph")):
                return "chart_data"
            if any(token in raw for token in ("公章", "印章", "seal", "stamp")):
                return "seal"
            return None

        preferred_chunk_type = _resolve_query_chunk_type_signal(query)

        def _chunk_type_boost(chunk_type: str) -> float:
            if not chunk_type_weighting_enabled or not preferred_chunk_type:
                return 0.0
            if chunk_type == preferred_chunk_type:
                return chunk_type_match_boost
            if preferred_chunk_type == "chart_data" and chunk_type == "figure":
                return max(0.0, chunk_type_match_boost * 0.75)
            return 0.0

        def _resolve_field_signal(result: dict[str, Any]) -> str:
            meta = result.get("metadata") or {}
            hinted = str(
                meta.get("embedding_field_role")
                or meta.get("embedding_field_kind")
                or meta.get("field_channel")
                or ""
            ).strip().lower()
            if hinted in {"title", "heading", "body"}:
                return hinted

            chunk_id = str(result.get("chunk_id") or meta.get("chunk_id") or "").strip().lower()
            if chunk_id.endswith(":title"):
                return "title"
            if chunk_id.endswith(":heading"):
                return "heading"
            return "body"

        def _field_boost(field_signal: str) -> float:
            if not field_aware_enabled:
                return 0.0
            if field_signal == "title":
                return field_aware_title_boost
            if field_signal == "heading":
                return field_aware_heading_boost
            return 0.0

        def normalize(results: list[dict[str, Any]], *, channel: str) -> dict[str, dict[str, Any]]:
            if not results:
                return {}
            scores = [r.get("score", 0.0) for r in results]
            min_score = min(scores)
            max_score = max(scores)
            rng = max_score - min_score if max_score > min_score else 1.0
            out: dict[str, dict[str, Any]] = {}
            for r in results:
                key = self._result_key(r)
                norm_score = (r.get("score", 0.0) - min_score) / rng
                field_signal = "body"
                field_boost = 0.0
                chunk_type = _resolve_chunk_type(r)
                chunk_type_boost = _chunk_type_boost(chunk_type)
                if channel == "vector":
                    field_signal = _resolve_field_signal(r)
                    field_boost = min(_field_boost(field_signal), field_aware_max_boost)
                scored = float(norm_score) + float(field_boost) + float(chunk_type_boost)
                existing = out.get(key)
                if existing is None or float(scored) > float(existing.get("score", 0.0) or 0.0):
                    out[key] = {
                        "score": float(scored),
                        "base_score": float(norm_score),
                        "data": r,
                        "chunk_type": chunk_type,
                        "chunk_type_boost": float(chunk_type_boost),
                        "field_aware_signal": field_signal if channel == "vector" else None,
                        "field_aware_boost": float(field_boost if channel == "vector" else 0.0),
                    }
            return out

        vector_norm = normalize(vector_results, channel="vector")
        bm25_norm = normalize(bm25_results, channel="bm25")
        lexical_norm = normalize(lexical_results, channel="lexical")
        sparse_norm = normalize(sparse_results, channel="sparse")

        def _attach_field_aware_signal(item: dict[str, Any], key: str) -> None:
            field_signal = vector_norm.get(key, {}).get("field_aware_signal")
            field_boost = float(vector_norm.get(key, {}).get("field_aware_boost") or 0.0)
            chunk_type = (
                vector_norm.get(key, {}).get("chunk_type")
                or bm25_norm.get(key, {}).get("chunk_type")
                or lexical_norm.get(key, {}).get("chunk_type")
                or sparse_norm.get(key, {}).get("chunk_type")
            )
            chunk_type_boost = max(
                float(vector_norm.get(key, {}).get("chunk_type_boost") or 0.0),
                float(bm25_norm.get(key, {}).get("chunk_type_boost") or 0.0),
                float(lexical_norm.get(key, {}).get("chunk_type_boost") or 0.0),
                float(sparse_norm.get(key, {}).get("chunk_type_boost") or 0.0),
            )
            if field_signal:
                item["field_aware_signal"] = str(field_signal)
            if field_boost > 0.0:
                item["field_aware_boost"] = float(field_boost)
            if chunk_type:
                item["chunk_type_signal"] = str(chunk_type)
            if chunk_type_boost > 0.0:
                item["chunk_type_boost"] = float(chunk_type_boost)

        try:
            if isinstance(self._last_channel_metrics, dict):
                field_signal_counts: Counter[str] = Counter()
                boosted = 0
                for payload in vector_norm.values():
                    signal = str(payload.get("field_aware_signal") or "body").strip().lower() or "body"
                    field_signal_counts[signal] += 1
                    if float(payload.get("field_aware_boost") or 0.0) > 0.0:
                        boosted += 1

                self._last_channel_metrics["field_aware"] = {
                    "enabled": bool(field_aware_enabled),
                    "title_boost": round(float(field_aware_title_boost), 6),
                    "heading_boost": round(float(field_aware_heading_boost), 6),
                    "max_boost": round(float(field_aware_max_boost), 6),
                    "candidates": int(len(vector_norm)),
                    "boosted_candidates": int(boosted),
                    "signals": dict(sorted((str(k), int(v)) for k, v in field_signal_counts.items())),
                }
                chunk_type_counts: Counter[str] = Counter()
                chunk_boosted = 0
                for payload in vector_norm.values():
                    signal = str(payload.get("chunk_type") or "text").strip().lower() or "text"
                    chunk_type_counts[signal] += 1
                    if float(payload.get("chunk_type_boost") or 0.0) > 0.0:
                        chunk_boosted += 1
                self._last_channel_metrics["chunk_type_weighting"] = {
                    "enabled": bool(chunk_type_weighting_enabled),
                    "preferred_chunk_type": preferred_chunk_type,
                    "match_boost": round(float(chunk_type_match_boost), 6),
                    "candidates": int(len(vector_norm)),
                    "boosted_candidates": int(chunk_boosted),
                    "signals": dict(sorted((str(k), int(v)) for k, v in chunk_type_counts.items())),
                }
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

        fusion = (fusion_strategy or "linear").lower().strip()
        if fusion in ("rrf", "reciprocal_rank_fusion"):
            def _rank_sort_key(r: dict[str, Any]) -> tuple[float, str]:
                # Deterministic ordering is important for regression replay.
                return (-float(r.get("score", 0.0) or 0.0), self._result_key(r))

            v_sorted = sorted(vector_results, key=_rank_sort_key)
            b_sorted = sorted(bm25_results, key=_rank_sort_key)
            l_sorted = sorted(lexical_results, key=_rank_sort_key)
            s_sorted = sorted(sparse_results, key=_rank_sort_key)

            v_rank: dict[str, int] = {}
            b_rank: dict[str, int] = {}
            l_rank: dict[str, int] = {}
            s_rank: dict[str, int] = {}
            for idx, r in enumerate(v_sorted, 1):
                key = self._result_key(r)
                if key not in v_rank:
                    v_rank[key] = idx
            for idx, r in enumerate(b_sorted, 1):
                key = self._result_key(r)
                if key not in b_rank:
                    b_rank[key] = idx
            for idx, r in enumerate(l_sorted, 1):
                key = self._result_key(r)
                if key not in l_rank:
                    l_rank[key] = idx
            for idx, r in enumerate(s_sorted, 1):
                key = self._result_key(r)
                if key not in s_rank:
                    s_rank[key] = idx

            k0 = int(rrf_k or 0) or int(getattr(self, "rrf_k", 60) or 60)
            k0 = max(1, k0)

            merged: dict[str, dict[str, Any]] = {}
            raw_scores: list[float] = []
            keys = sorted(set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys()))
            for key in keys:
                v_data = vector_norm.get(key, {}).get("data")
                b_data = bm25_norm.get(key, {}).get("data")
                l_data = lexical_norm.get(key, {}).get("data")
                s_data = sparse_norm.get(key, {}).get("data")
                data = v_data or b_data or l_data or s_data
                if not data:
                    continue

                # Merge metadata from all channels (prefer existing non-empty values).
                merged_meta = dict(data.get("metadata") or {})
                for src in (v_data, b_data, l_data, s_data):
                    if not src or src is data:
                        continue
                    src_meta = src.get("metadata") or {}
                    for mk, mv in src_meta.items():
                        if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                            merged_meta[mk] = mv
                merged_data = dict(data)
                merged_data["metadata"] = merged_meta
                if not merged_data.get("chunk_id"):
                    for src in (v_data, b_data, l_data, s_data):
                        if src and src.get("chunk_id"):
                            merged_data["chunk_id"] = src.get("chunk_id")
                            break
                data = merged_data

                vr = v_rank.get(key)
                br = b_rank.get(key)
                lr = l_rank.get(key)
                sr = s_rank.get(key)
                rrf_raw = (1.0 / (k0 + vr)) if vr else 0.0
                rrf_raw += (1.0 / (k0 + br)) if br else 0.0
                rrf_raw += (1.0 / (k0 + lr)) if lr else 0.0
                rrf_raw += (1.0 / (k0 + sr)) if sr else 0.0
                raw_scores.append(float(rrf_raw))

                merged[key] = {
                    **data,
                    "vector_score": float(vector_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "bm25_score": float(bm25_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "lexical_score": float(lexical_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "sparse_score": float(sparse_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "rrf_score_raw": float(rrf_raw),
                    "rrf_k": k0,
                    "rrf_rank_vector": vr,
                    "rrf_rank_bm25": br,
                    "rrf_rank_lexical": lr,
                    "rrf_rank_sparse": sr,
                    "fusion_strategy": "rrf",
                    "score": float(rrf_raw),
                }
                _attach_field_aware_signal(merged[key], key)

            if merged:
                min_s = min(raw_scores) if raw_scores else 0.0
                max_s = max(raw_scores) if raw_scores else 0.0
                rng = max_s - min_s if max_s > min_s else 1.0
                for item in merged.values():
                    raw = float(item.get("rrf_score_raw", 0.0) or 0.0)
                    item["score"] = (raw - min_s) / rng

            if query:
                phrase_boost_weight = max(
                    0.0,
                    float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
                )
                for item in merged.values():
                    _apply_exact_content_bonus_to_result(
                        query=query,
                        result=item,
                        phrase_boost_weight=phrase_boost_weight,
                    )

            def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, float, str]:
                return (
                    -float(item.get("score", 0.0) or 0.0),
                    -float(item.get("rrf_score_raw", 0.0) or 0.0),
                    -float(item.get("vector_score", 0.0) or 0.0),
                    -float(item.get("bm25_score", 0.0) or 0.0),
                    -float(item.get("lexical_score", 0.0) or 0.0),
                    -float(item.get("sparse_score", 0.0) or 0.0),
                    self._result_key(item),
                )

            return self._apply_plugin_retrieval_policy(sorted(merged.values(), key=_sort_key), query=query)

        if fusion in ("budgeted_rrf", "budget_rrf"):
            def _rank_sort_key(r: dict[str, Any]) -> tuple[float, str]:
                # Deterministic ordering is important for regression replay.
                return (-float(r.get("score", 0.0) or 0.0), self._result_key(r))

            v_sorted = sorted(vector_results, key=_rank_sort_key)
            b_sorted = sorted(bm25_results, key=_rank_sort_key)
            l_sorted = sorted(lexical_results, key=_rank_sort_key)
            s_sorted = sorted(sparse_results, key=_rank_sort_key)

            v_rank: dict[str, int] = {}
            b_rank: dict[str, int] = {}
            l_rank: dict[str, int] = {}
            s_rank: dict[str, int] = {}
            for idx, r in enumerate(v_sorted, 1):
                key = self._result_key(r)
                if key not in v_rank:
                    v_rank[key] = idx
            for idx, r in enumerate(b_sorted, 1):
                key = self._result_key(r)
                if key not in b_rank:
                    b_rank[key] = idx
            for idx, r in enumerate(l_sorted, 1):
                key = self._result_key(r)
                if key not in l_rank:
                    l_rank[key] = idx
            for idx, r in enumerate(s_sorted, 1):
                key = self._result_key(r)
                if key not in s_rank:
                    s_rank[key] = idx

            def _rank_score(rank_map: dict[str, int], key: str) -> float:
                rnk = rank_map.get(key)
                if not rnk:
                    return 0.0
                rnk = int(rnk)
                if rnk <= 0:
                    return 0.0
                return 1.0 / float(rnk)

            def _coerce_budgets(raw: Any) -> dict[str, int]:
                if not isinstance(raw, dict):
                    return {}
                out0: dict[str, int] = {}
                for k, v in raw.items():
                    key = str(k or "").strip().lower()
                    if not key:
                        continue
                    try:
                        iv = int(v) if v is not None else 0
                    except (TypeError, ValueError, AttributeError):
                        continue
                    out0[key] = max(0, iv)
                return out0

            def _coerce_min_scores(raw: Any) -> dict[str, float]:
                if not isinstance(raw, dict):
                    return {}
                out0: dict[str, float] = {}
                for k, v in raw.items():
                    key = str(k or "").strip().lower()
                    if not key:
                        continue
                    try:
                        fv = float(v) if v is not None else 0.0
                    except (TypeError, ValueError, AttributeError):
                        continue
                    out0[key] = max(0.0, min(1.0, fv))
                return out0

            # Determine budgets (quotas) for the top_k prefix.
            k_prefix = int(top_k or 0) or int(getattr(self, "k", 0) or 0) or 10
            k_prefix = max(1, k_prefix)

            budgets = _coerce_budgets(getattr(self, "fusion_budgets", None))
            if not budgets:
                channel_results = {
                    "vector": v_sorted,
                    "bm25": b_sorted,
                    "lexical": l_sorted,
                    "sparse": s_sorted,
                }
                active_channels = [channel for channel, rows in channel_results.items() if rows]
                budgets = {channel: 0 for channel in channel_results}
                if active_channels:
                    # Default: allocate the visible prefix across channels that are
                    # actually healthy enough to produce candidates. Give every active
                    # channel one slot first, then distribute the remainder with a
                    # stable priority that still favors dense recall slightly.
                    remaining = int(k_prefix)
                    for channel in active_channels:
                        if remaining <= 0:
                            break
                        budgets[channel] = 1
                        remaining -= 1

                    priority = [channel for channel in ("vector", "bm25", "lexical", "sparse") if channel in active_channels]
                    idx = 0
                    while remaining > 0 and priority:
                        channel = priority[idx % len(priority)]
                        budgets[channel] = int(budgets.get(channel, 0) or 0) + 1
                        remaining -= 1
                        idx += 1

            min_scores = _coerce_min_scores(getattr(self, "fusion_min_scores", None))

            k0 = int(rrf_k or 0) or int(getattr(self, "rrf_k", 60) or 60)
            k0 = max(1, k0)

            merged: dict[str, dict[str, Any]] = {}
            raw_scores: list[float] = []
            keys = sorted(set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys()))

            def _candidate_eligible(key: str) -> bool:
                # Candidate must have at least one channel where it meets that channel's min score (if configured).
                for ch, rmap in (("vector", v_rank), ("bm25", b_rank), ("lexical", l_rank), ("sparse", s_rank)):
                    rs = _rank_score(rmap, key)
                    if rs <= 0.0:
                        continue
                    th = min_scores.get(ch)
                    if th is None or rs >= float(th):
                        return True
                return False

            for key in keys:
                v_data = vector_norm.get(key, {}).get("data")
                b_data = bm25_norm.get(key, {}).get("data")
                l_data = lexical_norm.get(key, {}).get("data")
                s_data = sparse_norm.get(key, {}).get("data")
                data = v_data or b_data or l_data or s_data
                if not data:
                    continue

                # Merge metadata from all channels (prefer existing non-empty values).
                merged_meta = dict(data.get("metadata") or {})
                for src in (v_data, b_data, l_data, s_data):
                    if not src or src is data:
                        continue
                    src_meta = src.get("metadata") or {}
                    for mk, mv in src_meta.items():
                        if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                            merged_meta[mk] = mv
                merged_data = dict(data)
                merged_data["metadata"] = merged_meta
                if not merged_data.get("chunk_id"):
                    for src in (v_data, b_data, l_data, s_data):
                        if src and src.get("chunk_id"):
                            merged_data["chunk_id"] = src.get("chunk_id")
                            break
                data = merged_data

                vr = v_rank.get(key)
                br = b_rank.get(key)
                lr = l_rank.get(key)
                sr = s_rank.get(key)
                rrf_raw = (1.0 / (k0 + vr)) if vr else 0.0
                rrf_raw += (1.0 / (k0 + br)) if br else 0.0
                rrf_raw += (1.0 / (k0 + lr)) if lr else 0.0
                rrf_raw += (1.0 / (k0 + sr)) if sr else 0.0
                raw_scores.append(float(rrf_raw))

                merged[key] = {
                    **data,
                    "vector_score": float(vector_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "bm25_score": float(bm25_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "lexical_score": float(lexical_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "sparse_score": float(sparse_norm.get(key, {}).get("score", 0.0) or 0.0),
                    "vector_rank_score": float(_rank_score(v_rank, key)),
                    "bm25_rank_score": float(_rank_score(b_rank, key)),
                    "lexical_rank_score": float(_rank_score(l_rank, key)),
                    "sparse_rank_score": float(_rank_score(s_rank, key)),
                    "rrf_score_raw": float(rrf_raw),
                    "rrf_k": k0,
                    "rrf_rank_vector": vr,
                    "rrf_rank_bm25": br,
                    "rrf_rank_lexical": lr,
                    "rrf_rank_sparse": sr,
                    "fusion_strategy": "budgeted_rrf",
                    "score": float(rrf_raw),
                }
                _attach_field_aware_signal(merged[key], key)

            if merged:
                min_s = min(raw_scores) if raw_scores else 0.0
                max_s = max(raw_scores) if raw_scores else 0.0
                rng = max_s - min_s if max_s > min_s else 1.0
                for item in merged.values():
                    raw = float(item.get("rrf_score_raw", 0.0) or 0.0)
                    item["score"] = (raw - min_s) / rng

            if query:
                phrase_boost_weight = max(
                    0.0,
                    float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0),
                )
                for item in merged.values():
                    _apply_exact_content_bonus_to_result(
                        query=query,
                        result=item,
                        phrase_boost_weight=phrase_boost_weight,
                    )

            def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, float, str]:
                return (
                    -float(item.get("score", 0.0) or 0.0),
                    -float(item.get("rrf_score_raw", 0.0) or 0.0),
                    -float(item.get("vector_rank_score", 0.0) or 0.0),
                    -float(item.get("bm25_rank_score", 0.0) or 0.0),
                    -float(item.get("lexical_rank_score", 0.0) or 0.0),
                    -float(item.get("sparse_rank_score", 0.0) or 0.0),
                    self._result_key(item),
                )

            all_sorted = sorted(merged.values(), key=_sort_key)

            def _budget_channel_order(
                channel_results: list[dict[str, Any]],
                rank_map: dict[str, int],
            ) -> list[dict[str, Any]]:
                return sorted(
                    channel_results,
                    key=lambda item: (
                        -_float_or_default(
                            merged.get(self._result_key(item), {}).get("exact_phrase_score"),
                            0.0,
                        ),
                        int(rank_map.get(self._result_key(item), len(channel_results) + 1)),
                        self._result_key(item),
                    ),
                )

            v_budget_sorted = _budget_channel_order(v_sorted, v_rank)
            b_budget_sorted = _budget_channel_order(b_sorted, b_rank)
            l_budget_sorted = _budget_channel_order(l_sorted, l_rank)
            s_budget_sorted = _budget_channel_order(s_sorted, s_rank)

            # Build a top_k prefix that enforces budgets/quotas but still orders by fused score.
            selected_keys: list[str] = []
            used: set[str] = set()
            picked_by_channel: dict[str, int] = {"vector": 0, "bm25": 0, "lexical": 0, "sparse": 0, "fill": 0}

            def _select_from_channel(channel: str, sorted_results: list[dict[str, Any]], rank_map: dict[str, int]) -> None:
                quota = int(budgets.get(channel, 0) or 0)
                if quota <= 0:
                    return
                picked = 0
                th = min_scores.get(channel)
                for rr in sorted_results:
                    if picked >= quota:
                        break
                    key = self._result_key(rr)
                    if key in used:
                        continue
                    rs = _rank_score(rank_map, key)
                    if rs <= 0.0:
                        continue
                    if th is not None and rs < float(th):
                        # Exact-hit weighting may reorder a channel, so lower-ranked misses
                        # cannot terminate the scan for later eligible candidates.
                        continue
                    if not _candidate_eligible(key):
                        continue
                    used.add(key)
                    selected_keys.append(key)
                    picked += 1
                    try:
                        picked_by_channel[channel] = int(picked_by_channel.get(channel, 0) or 0) + 1
                    except Exception as exc:
                        logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

            _select_from_channel("vector", v_budget_sorted, v_rank)
            _select_from_channel("bm25", b_budget_sorted, b_rank)
            _select_from_channel("lexical", l_budget_sorted, l_rank)
            _select_from_channel("sparse", s_budget_sorted, s_rank)

            if len(selected_keys) < k_prefix:
                for item in all_sorted:
                    if len(selected_keys) >= k_prefix:
                        break
                    key = self._result_key(item)
                    if key in used:
                        continue
                    if not _candidate_eligible(key):
                        continue
                    used.add(key)
                    selected_keys.append(key)
                    try:
                        picked_by_channel["fill"] = int(picked_by_channel.get("fill", 0) or 0) + 1
                    except Exception as exc:
                        logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

            selected_set = set(selected_keys)
            prefix = [item for item in all_sorted if self._result_key(item) in selected_set]
            rest = [item for item in all_sorted if self._result_key(item) not in selected_set]
            for idx, item in enumerate(prefix, 1):
                item["fusion_budgeted_prefix_rank"] = int(idx)

            # Best-effort: surface fusion budget behavior into retriever_debug.channels for diagnostics.
            # PII-safe: only small numeric counters and low-cardinality settings.
            try:
                eligible_total = 0
                for key in keys:
                    if _candidate_eligible(key):
                        eligible_total += 1

                budgets_out = dict(sorted((str(k), int(v or 0)) for k, v in (budgets or {}).items()))
                min_scores_out = dict(sorted((str(k), float(v or 0.0)) for k, v in (min_scores or {}).items()))
                picked_out = {k: int(picked_by_channel.get(k, 0) or 0) for k in ("vector", "bm25", "lexical", "sparse", "fill")}

                if isinstance(self._last_channel_metrics, dict):
                    self._last_channel_metrics["fusion_budgeted_rrf"] = {
                        "k_prefix": int(k_prefix),
                        "rrf_k": int(k0),
                        "budgets": budgets_out,
                        "min_scores": min_scores_out or None,
                        "eligible_total": int(eligible_total),
                        "selected_prefix": int(len(selected_keys)),
                        "picked_by_channel": picked_out,
                    }
            except Exception as exc:
                logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)
            return self._apply_plugin_retrieval_policy(prefix + rest, query=query)

        if fusion in ("weighted", "weighted_linear", "weighted_sum"):
            def _coerce_weights(raw: Any) -> dict[str, float]:
                if not isinstance(raw, dict):
                    return {}
                allowed = {"vector", "bm25", "lexical", "sparse"}
                out0: dict[str, float] = {}
                for k, v in raw.items():
                    key = str(k or "").strip().lower()
                    if not key or key not in allowed:
                        continue
                    try:
                        w = float(v)
                    except (TypeError, ValueError, AttributeError):
                        continue
                    if w <= 0.0:
                        continue
                    out0[key] = float(w)
                return out0

            weights_raw = _coerce_weights(getattr(self, "fusion_weights", None))
            w_sum = sum(float(x) for x in weights_raw.values())
            if w_sum <= 0.0:
                # Safe fallback: behave like linear fusion when weights are not configured.
                fusion = "linear"
            else:
                weights = {k: (float(v) / w_sum) for k, v in weights_raw.items()}

                merged: dict[str, dict[str, Any]] = {}
                keys = sorted(
                    set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys())
                )
                for key in keys:
                    v_score = float(vector_norm.get(key, {}).get("score", 0.0) or 0.0)
                    b_score = float(bm25_norm.get(key, {}).get("score", 0.0) or 0.0)
                    l_score = float(lexical_norm.get(key, {}).get("score", 0.0) or 0.0)
                    s_score = float(sparse_norm.get(key, {}).get("score", 0.0) or 0.0)
                    v_data = vector_norm.get(key, {}).get("data")
                    b_data = bm25_norm.get(key, {}).get("data")
                    l_data = lexical_norm.get(key, {}).get("data")
                    s_data = sparse_norm.get(key, {}).get("data")
                    data = v_data or b_data or l_data or s_data
                    if not data:
                        continue

                    # Merge metadata from all channels (e.g., img_id may only exist in BM25/DB metadata).
                    merged_meta = dict(data.get("metadata") or {})
                    for src in (v_data, b_data, l_data, s_data):
                        if not src or src is data:
                            continue
                        src_meta = src.get("metadata") or {}
                        for mk, mv in src_meta.items():
                            if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                                merged_meta[mk] = mv
                    merged_data = dict(data)
                    merged_data["metadata"] = merged_meta
                    if not merged_data.get("chunk_id"):
                        for src in (v_data, b_data, l_data, s_data):
                            if src and src.get("chunk_id"):
                                merged_data["chunk_id"] = src.get("chunk_id")
                                break
                    data = merged_data

                    fused_score = (
                        float(weights.get("vector", 0.0) or 0.0) * float(v_score)
                        + float(weights.get("bm25", 0.0) or 0.0) * float(b_score)
                        + float(weights.get("lexical", 0.0) or 0.0) * float(l_score)
                        + float(weights.get("sparse", 0.0) or 0.0) * float(s_score)
                    )

                    merged[key] = {
                        **data,
                        "vector_score": float(v_score),
                        "bm25_score": float(b_score),
                        "lexical_score": float(l_score),
                        "sparse_score": float(s_score),
                        "fusion_strategy": "weighted",
                        "score": float(fused_score),
                    }
                    _attach_field_aware_signal(merged[key], key)

                # Best-effort: surface weights used into retriever_debug.channels for diagnostics.
                try:
                    if isinstance(self._last_channel_metrics, dict):
                        weights_out = dict(sorted((k, round(float(v), 6)) for k, v in (weights or {}).items()))
                        sig = ",".join([f"{k}:{weights_out.get(k, 0.0):.6f}" for k in sorted(weights_out.keys())])
                        self._last_channel_metrics["fusion_weighted"] = {
                            "weights": weights_out,
                            "weights_hash": stable_hash(sig, length=16) if sig else None,
                        }
                except Exception as exc:
                    logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

                def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
                    return (
                        -float(item.get("score", 0.0) or 0.0),
                        -float(item.get("vector_score", 0.0) or 0.0),
                        -float(item.get("bm25_score", 0.0) or 0.0),
                        -float(item.get("lexical_score", 0.0) or 0.0),
                        -float(item.get("sparse_score", 0.0) or 0.0),
                        self._result_key(item),
                    )

                return self._apply_plugin_retrieval_policy(sorted(merged.values(), key=_sort_key), query=query)

        merged: dict[str, dict[str, Any]] = {}
        keys = sorted(set(vector_norm.keys()) | set(bm25_norm.keys()) | set(lexical_norm.keys()) | set(sparse_norm.keys()))
        for key in keys:
            v_score = vector_norm.get(key, {}).get("score", 0.0)
            b_score = bm25_norm.get(key, {}).get("score", 0.0)
            l_score = lexical_norm.get(key, {}).get("score", 0.0)
            s_score = sparse_norm.get(key, {}).get("score", 0.0)
            v_data = vector_norm.get(key, {}).get("data")
            b_data = bm25_norm.get(key, {}).get("data")
            l_data = lexical_norm.get(key, {}).get("data")
            s_data = sparse_norm.get(key, {}).get("data")
            data = v_data or b_data or l_data or s_data
            if not data:
                continue

            # Merge metadata from all channels (e.g., img_id may only exist in BM25/DB metadata).
            merged_meta = dict(data.get("metadata") or {})
            for src in (v_data, b_data, l_data, s_data):
                if not src or src is data:
                    continue
                src_meta = src.get("metadata") or {}
                for mk, mv in src_meta.items():
                    if mk not in merged_meta or merged_meta.get(mk) in (None, "", [], {}):
                        merged_meta[mk] = mv
            merged_data = dict(data)
            merged_data["metadata"] = merged_meta
            if not merged_data.get("chunk_id"):
                for src in (v_data, b_data, l_data, s_data):
                    if src and src.get("chunk_id"):
                        merged_data["chunk_id"] = src.get("chunk_id")
                        break
            data = merged_data

            has_v = key in vector_norm
            has_b = key in bm25_norm
            has_l = key in lexical_norm
            has_s = key in sparse_norm
            keyword_score = max(float(b_score), float(l_score), float(s_score))
            if has_v and (has_b or has_l or has_s):
                fused_score = alpha * float(v_score) + (1 - alpha) * float(keyword_score)
            elif has_v:
                fused_score = float(v_score)
            else:
                fused_score = float(keyword_score)

            merged[key] = {
                **data,
                "vector_score": float(v_score),
                "bm25_score": float(b_score),
                "lexical_score": float(l_score),
                "sparse_score": float(s_score),
                "fusion_strategy": "linear",
                "score": fused_score,
            }
            _attach_field_aware_signal(merged[key], key)

        def _sort_key(item: dict[str, Any]) -> tuple[float, float, float, float, float, str]:
            return (
                -float(item.get("score", 0.0) or 0.0),
                -float(item.get("vector_score", 0.0) or 0.0),
                -float(item.get("bm25_score", 0.0) or 0.0),
                -float(item.get("lexical_score", 0.0) or 0.0),
                -float(item.get("sparse_score", 0.0) or 0.0),
                self._result_key(item),
            )

        return self._apply_plugin_retrieval_policy(sorted(merged.values(), key=_sort_key), query=query)

    def _weight_rerank(
        self,
        query: str,
        documents: list[dict[str, Any]],
        vector_weight: float = 0.6,
        keyword_weight: float = 0.4,
    ) -> list[dict[str, Any]]:
        """Vector score + keyword TF-IDF cosine linear weighting."""
        if not documents:
            return documents

        query_tokens = self._bm25_tokenize(query)
        doc_tokens_list = [self._bm25_tokenize(doc.get("content", "")) for doc in documents]

        doc_term_frequencies = [Counter(tokens) for tokens in doc_tokens_list]
        document_frequencies: Counter[str] = Counter()
        for term_frequencies in doc_term_frequencies:
            document_frequencies.update(term_frequencies.keys())
        if not document_frequencies:
            return documents

        doc_count = len(documents)
        token_idf = {
            token: math.log((1 + doc_count) / (1 + document_count)) + 1
            for token, document_count in document_frequencies.items()
        }

        def tfidf_vec(term_frequencies: Counter[str]) -> dict[str, float]:
            return {
                token: count * token_idf.get(token, 0.0)
                for token, count in term_frequencies.items()
            }

        query_vec = tfidf_vec(Counter(query_tokens))
        doc_vecs = [tfidf_vec(term_frequencies) for term_frequencies in doc_term_frequencies]

        def cosine(a: dict[str, float], b: dict[str, float]) -> float:
            if not a or not b:
                return 0.0
            common = set(a.keys()) & set(b.keys())
            num = sum(a[t] * b[t] for t in common)
            denom = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
            return num / denom if denom else 0.0

        keyword_scores = [cosine(query_vec, v) for v in doc_vecs]

        reranked: list[dict[str, Any]] = []
        phrase_boost_weight = max(0.0, float(getattr(settings, "RETRIEVAL_EXACT_PHRASE_RERANK_BOOST", 0.35) or 0.0))
        for doc, kw_score in zip(documents, keyword_scores, strict=False):
            vec_score = doc.get("vector_score", doc.get("score", 0.0))
            phrase = query_phrase_match(query, str(doc.get("content", "") or ""))
            phrase_score = float(phrase.get("score", 0.0) or 0.0)
            phrase_boost = phrase_score * phrase_boost_weight
            final_score = vector_weight * float(vec_score) + keyword_weight * float(kw_score) + phrase_boost
            new_doc = dict(doc)
            new_doc["keyword_score"] = float(kw_score)
            new_doc["exact_phrase_score"] = float(phrase_score)
            new_doc["exact_phrase_boost"] = float(phrase_boost)
            if phrase.get("matched_phrases"):
                new_doc["exact_phrase_matches"] = list(phrase.get("matched_phrases") or [])[:4]
            new_doc["score"] = float(final_score)
            reranked.append(new_doc)

        reranked.sort(key=lambda x: x["score"], reverse=True)
        return reranked

    def _mmr_doc_similarity(
        self,
        tokens_map: dict[int, set[str]],
        doc_a: dict[str, Any],
        doc_b: dict[str, Any],
    ) -> float:
        return self._jaccard(tokens_map.get(id(doc_a), set()), tokens_map.get(id(doc_b), set()))

    def _mmr_diversity_penalty(
        self,
        doc: dict[str, Any],
        selected: list[dict[str, Any]],
        tokens_map: dict[int, set[str]],
    ) -> float:
        if not selected:
            return 0.0
        similarities = [self._mmr_doc_similarity(tokens_map, doc, selected_doc) for selected_doc in selected]
        return max(similarities) if similarities else 0.0

    def _best_mmr_candidate(
        self,
        candidates: list[dict[str, Any]],
        selected: list[dict[str, Any]],
        *,
        tokens_map: dict[int, set[str]],
        lambda_mult: float,
    ) -> tuple[int, dict[str, Any]] | None:
        best: tuple[int, dict[str, Any]] | None = None
        best_score = -1e9
        for index, doc in enumerate(candidates):
            relevance = float(doc.get("score", 0.0))
            diversity_penalty = self._mmr_diversity_penalty(doc, selected, tokens_map)
            mmr_score = lambda_mult * relevance - (1 - lambda_mult) * diversity_penalty
            if mmr_score > best_score:
                best_score = mmr_score
                best = (index, doc)
        return best

    def _mmr_rerank(
        self,
        documents: list[dict[str, Any]],
        query: str,
        top_k: int,
        lambda_mult: float = 0.7,
    ) -> list[dict[str, Any]]:
        """
        Simple MMR (Maximal Marginal Relevance) reranking:
        max lambda*sim(query, doc) - (1-lambda)*max sim(doc, selected)
        Uses bag-of-words Jaccard approximation, lightweight with no extra dependencies.
        """
        if not documents:
            return documents

        lambda_mult = max(min(lambda_mult, 1.0), 0.0)
        selected: list[dict[str, Any]] = []
        candidates = list(documents)
        # Pre-cache tokens to avoid multiple tokenizations
        tokens_map = {id(doc): self._tokenize_for_similarity(doc.get("content", "")) for doc in candidates}

        while candidates and len(selected) < top_k:
            best = self._best_mmr_candidate(
                candidates,
                selected,
                tokens_map=tokens_map,
                lambda_mult=lambda_mult,
            )
            if best is None:
                break
            idx, doc = best
            selected.append(doc)
            candidates.pop(idx)

        return selected
