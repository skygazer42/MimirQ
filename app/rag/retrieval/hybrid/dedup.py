"""Result identity, family collapse, dedup and document diversity for the hybrid retriever.

Split out of ``app.rag.retriever`` (see ``app.rag.retrieval.hybrid``). The
methods below run on the ``HybridRetriever`` instance via mixin inheritance.
"""

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import jieba

from app.core.config import settings
from app.rag.core.filters import match_metadata_filter
from app.rag.core.hashing import stable_hash
from app.rag.preprocessing.stopwords import STOPWORDS
from app.rag.retrieval.hybrid.common import (
    _RECORD_IDENTITY_METADATA_KEY,
    NON_CRITICAL_RETRIEVER_FALLBACK_LOG,
    logger,
)


@dataclass
class _DedupRuntime:
    threshold: float
    max_compare: int
    max_chunks_per_record_identity: int
    near_enabled: bool
    near_thr: int
    near_max_compare: int
    distance_func: Any


@dataclass
class _DedupState:
    seen_chunk_ids: set[str]
    seen_content_hashes: set[str]
    seen_fingerprints: set[str]
    record_identity_counts: dict[str, int]
    kept: list[dict[str, Any]]
    kept_tokens_by_doc: dict[str, list[set[str]]]
    kept_simhashes: list[int]
    dropped_record_identity: int = 0
    dropped_near: int = 0
    dropped_content_hash: int = 0


class DedupDiversityMixin:
    """Result identity keys, hierarchy family collapse, dedup, and doc/page diversity caps."""

    def _result_key(self, result: dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        if doc_id is not None and chunk_index is not None:
            return f"{doc_id}:{chunk_index}"
        cid = result.get("chunk_id") or meta.get("chunk_id")
        if cid:
            return str(cid)
        content = str(result.get("content") or "")
        return f"content:{stable_hash(content)}"

    @staticmethod
    def _first_metadata_value(meta: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = str(meta.get(key) or "").strip()
            if value:
                return value
        return ""

    @staticmethod
    def _document_chunk_family_key(meta: dict[str, Any]) -> str:
        doc_id = meta.get("document_id")
        chunk_index = meta.get("chunk_index")
        return f"{doc_id}:{chunk_index}" if doc_id is not None and chunk_index is not None else ""

    @staticmethod
    def _result_chunk_family_key(meta: dict[str, Any], result: dict[str, Any] | None) -> str:
        if result is None:
            return ""
        chunk_id = result.get("chunk_id") or meta.get("chunk_id")
        return str(chunk_id).strip() if chunk_id else ""

    def _resolve_family_collapse_key(self, meta: dict[str, Any], *, result: dict[str, Any] | None = None) -> str:
        key = self._first_metadata_value(meta, ("hierarchy_family_key", "parent_id", "parent_node_id"))
        if key:
            return key

        role = str(meta.get("chunk_role") or "").strip().lower()
        if role == "parent":
            key = self._first_metadata_value(meta, ("hierarchy_node_key", "chunk_key"))
            if key:
                return key

        key = self._document_chunk_family_key(meta)
        if key:
            return key

        return self._result_chunk_family_key(meta, result)

    def _should_apply_hierarchy_family_collapse(self) -> bool:
        return bool(self.hierarchy_family_collapse)

    def _init_family_collapse_stats(
        self,
        stats: dict[str, Any] | None,
        *,
        enabled: bool,
        input_count: int,
    ) -> None:
        if stats is None:
            return
        stats.clear()
        stats["enabled"] = bool(enabled)
        stats["retrieval_profile"] = str(self.retrieval_profile or "").strip().lower() or None
        stats["input_results"] = int(input_count)

    @staticmethod
    def _set_family_collapse_stats(
        stats: dict[str, Any] | None,
        *,
        output_count: int,
        collapsed: int,
        distinct_families: int | None = None,
    ) -> None:
        if stats is None:
            return
        stats["output_results"] = int(output_count)
        stats["collapsed_results"] = int(collapsed)
        if distinct_families is not None:
            stats["distinct_families"] = int(distinct_families)

    def _collapse_results_by_family(
        self,
        results: list[dict[str, Any]],
        *,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        enabled = self._should_apply_hierarchy_family_collapse()
        self._init_family_collapse_stats(stats, enabled=enabled, input_count=len(results or []))

        if not enabled or not results:
            self._set_family_collapse_stats(stats, output_count=len(results or []), collapsed=0)
            return results

        out: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        collapsed = 0
        for r in results:
            meta = r.get("metadata") or {}
            family_key = self._resolve_family_collapse_key(meta, result=r)
            if family_key and family_key in seen_keys:
                collapsed += 1
                continue
            if family_key:
                seen_keys.add(family_key)
            out.append(r)

        self._set_family_collapse_stats(
            stats,
            output_count=len(out),
            collapsed=collapsed,
            distinct_families=len(seen_keys),
        )
        return out

    def _get_doc_id(self, result: dict[str, Any]) -> str:
        meta = result.get("metadata") or {}
        doc_id = meta.get("document_id")
        return str(doc_id) if doc_id is not None else ""

    def _match_metadata_filter(self, meta: dict[str, Any], filter_spec: dict[str, Any]) -> bool:
        return match_metadata_filter(meta, filter_spec)

    @staticmethod
    def _normalize_similarity_token(token: Any) -> str | None:
        tok = str(token).strip()
        if not tok or len(tok) < 2:
            return None
        if tok.isascii():
            tok = tok.casefold()
            if tok.isdigit():
                return None
        return None if tok in STOPWORDS else tok

    @staticmethod
    def _tokenize_for_similarity(text: str) -> set[str]:
        raw = (text or "").strip()
        if not raw:
            return set()
        tokens: list[str] = []
        for token in jieba.cut_for_search(raw):
            tok = DedupDiversityMixin._normalize_similarity_token(token)
            if tok is not None:
                tokens.append(tok)
        return set(tokens)

    @staticmethod
    def _jaccard(a: set[str], b: set[str]) -> float:
        if not a or not b:
            return 0.0
        inter = a & b
        union = a | b
        return (len(inter) / len(union)) if union else 0.0

    @staticmethod
    def _fingerprint(text: str) -> str:
        norm = re.sub(r"\s+", " ", (text or "").strip())
        return norm.casefold()

    @staticmethod
    def _bounded_similarity_settings(threshold: float, max_compare: int) -> tuple[float, int]:
        return max(0.0, min(float(threshold or 0.0), 1.0)), max(0, int(max_compare or 0))

    @staticmethod
    def _resolve_near_dedup_runtime() -> tuple[bool, int, int, Any | None]:
        near_enabled = bool(getattr(settings, "RETRIEVAL_NEAR_DEDUP_ENABLED", False))
        near_thr = max(0, int(getattr(settings, "RETRIEVAL_NEAR_DEDUP_HAMMING_THRESHOLD", 0) or 0))
        near_max_compare = max(0, int(getattr(settings, "RETRIEVAL_NEAR_DEDUP_MAX_COMPARE", 0) or 0))
        distance_func = None
        if near_enabled:
            try:
                from app.rag.preprocessing.simhash import hamming_distance64  # noqa: WPS433

                distance_func = hamming_distance64
            except (TypeError, ValueError, AttributeError):
                near_enabled = False
        return near_enabled, near_thr, near_max_compare, distance_func

    @staticmethod
    def _simhash64_from_meta(meta: dict[str, Any]) -> int | None:
        sh_hex = str(meta.get("simhash64") or "").strip().lower()
        if not sh_hex:
            return None
        try:
            return int(sh_hex, 16) & ((1 << 64) - 1)
        except (TypeError, ValueError, AttributeError):
            return None

    @staticmethod
    def _is_seen_chunk_id(result: dict[str, Any], meta: dict[str, Any], seen_chunk_ids: set[str]) -> bool:
        cid = result.get("chunk_id") or meta.get("chunk_id")
        if not cid:
            return False
        scid = str(cid)
        if scid in seen_chunk_ids:
            return True
        seen_chunk_ids.add(scid)
        return False

    @staticmethod
    def _is_seen_content_hash(meta: dict[str, Any], seen_content_hashes: set[str]) -> bool:
        content_hash = meta.get("content_hash")
        if content_hash is None:
            return False
        normalized = str(content_hash).strip()
        if not normalized:
            return False
        if normalized in seen_content_hashes:
            return True
        seen_content_hashes.add(normalized)
        return False

    @staticmethod
    def _record_identity_dedup_key(meta: dict[str, Any]) -> str | None:
        record_identity = meta.get(_RECORD_IDENTITY_METADATA_KEY)
        if not isinstance(record_identity, dict):
            return None
        key = str(record_identity.get("key") or "").strip()
        if not key:
            return None
        scope = str(meta.get("dataset_id") or meta.get("document_id") or "").strip()
        return f"{scope}:{key}" if scope else key

    @staticmethod
    def _record_identity_over_cap(
        meta: dict[str, Any],
        *,
        max_chunks_per_record_identity: int,
        record_identity_counts: dict[str, int],
    ) -> bool:
        cap = max(0, int(max_chunks_per_record_identity or 0))
        if cap <= 0:
            return False
        key = DedupDiversityMixin._record_identity_dedup_key(meta)
        if not key:
            return False
        current = int(record_identity_counts.get(key, 0) or 0)
        if current >= cap:
            return True
        record_identity_counts[key] = current + 1
        return False

    @staticmethod
    def _is_near_duplicate_simhash(
        meta: dict[str, Any],
        *,
        near_enabled: bool,
        near_thr: int,
        near_max_compare: int,
        kept_simhashes: list[int],
        distance_func: Any | None,
    ) -> bool:
        if not near_enabled or distance_func is None:
            return False
        simhash = DedupDiversityMixin._simhash64_from_meta(meta)
        if simhash is None:
            return False
        compare_simhashes = kept_simhashes
        if near_max_compare and len(compare_simhashes) > near_max_compare:
            compare_simhashes = compare_simhashes[-near_max_compare:]
        return any(distance_func(simhash, prev) <= near_thr for prev in compare_simhashes)

    @staticmethod
    def _remember_near_simhash(meta: dict[str, Any], *, near_enabled: bool, kept_simhashes: list[int]) -> None:
        if not near_enabled:
            return
        sh_hex = str(meta.get("simhash64") or "").strip().lower()
        if not sh_hex:
            return
        try:
            kept_simhashes.append(int(sh_hex, 16) & ((1 << 64) - 1))
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _is_jaccard_duplicate(
        self,
        *,
        content: str,
        doc_id: str,
        threshold: float,
        max_compare: int,
        kept_tokens_by_doc: dict[str, list[set[str]]],
    ) -> bool:
        if threshold <= 0.0 or not doc_id:
            return False
        tokens = self._tokenize_for_similarity(content)
        if not tokens:
            return False
        compare_sets = kept_tokens_by_doc.get(doc_id) or []
        if max_compare and len(compare_sets) > max_compare:
            compare_sets = compare_sets[-max_compare:]
        if any(self._jaccard(tokens, prev) >= threshold for prev in compare_sets if prev):
            return True
        kept_tokens_by_doc.setdefault(doc_id, []).append(tokens)
        return False

    def _record_dedup_metrics(
        self,
        *,
        near_enabled: bool,
        near_thr: int,
        near_max_compare: int,
        dropped_near: int,
        dropped_content_hash: int,
        dropped_record_identity: int,
        max_chunks_per_record_identity: int,
    ) -> None:
        try:
            if isinstance(self._last_channel_metrics, dict):
                dedup_meta = self._last_channel_metrics.get("dedup")
                if not isinstance(dedup_meta, dict):
                    dedup_meta = {}
                    self._last_channel_metrics["dedup"] = dedup_meta
                dedup_meta["near_dedup_enabled"] = bool(near_enabled)
                dedup_meta["near_dedup_dropped"] = int(dropped_near)
                dedup_meta["near_dedup_hamming_threshold"] = int(near_thr)
                dedup_meta["near_dedup_max_compare"] = int(near_max_compare)
                dedup_meta["content_hash_dropped"] = int(dropped_content_hash)
                dedup_meta["record_identity_dropped"] = int(dropped_record_identity)
                dedup_meta["max_chunks_per_record_identity"] = int(max_chunks_per_record_identity)
        except Exception as exc:
            logger.debug(NON_CRITICAL_RETRIEVER_FALLBACK_LOG, exc)

    def _dedup_runtime(self) -> _DedupRuntime:
        threshold, max_compare = self._bounded_similarity_settings(self.dedup_jaccard_threshold, self.dedup_max_compare)
        near_enabled, near_thr, near_max_compare, distance_func = self._resolve_near_dedup_runtime()
        return _DedupRuntime(
            threshold=threshold,
            max_compare=max_compare,
            max_chunks_per_record_identity=max(0, int(getattr(self, "max_chunks_per_record_identity", 0) or 0)),
            near_enabled=near_enabled,
            near_thr=near_thr,
            near_max_compare=near_max_compare,
            distance_func=distance_func,
        )

    @staticmethod
    def _new_dedup_state() -> _DedupState:
        return _DedupState(
            seen_chunk_ids=set(),
            seen_content_hashes=set(),
            seen_fingerprints=set(),
            record_identity_counts={},
            kept=[],
            kept_tokens_by_doc={},
            kept_simhashes=[],
        )

    def _keep_dedup_result(
        self,
        result: dict[str, Any],
        *,
        runtime: _DedupRuntime,
        state: _DedupState,
    ) -> None:
        meta = result.get("metadata") or {}
        if self._is_seen_chunk_id(result, meta, state.seen_chunk_ids):
            return

        content = (result.get("content") or "").strip()
        if not content:
            return

        if self._is_seen_content_hash(meta, state.seen_content_hashes):
            state.dropped_content_hash += 1
            return

        fingerprint = self._fingerprint(content)
        if fingerprint in state.seen_fingerprints:
            return
        state.seen_fingerprints.add(fingerprint)

        if self._is_near_duplicate_simhash(
            meta,
            near_enabled=runtime.near_enabled,
            near_thr=runtime.near_thr,
            near_max_compare=runtime.near_max_compare,
            kept_simhashes=state.kept_simhashes,
            distance_func=runtime.distance_func,
        ):
            state.dropped_near += 1
            return

        if self._is_jaccard_duplicate(
            content=content,
            doc_id=self._get_doc_id(result),
            threshold=runtime.threshold,
            max_compare=runtime.max_compare,
            kept_tokens_by_doc=state.kept_tokens_by_doc,
        ):
            return

        if self._record_identity_over_cap(
            meta,
            max_chunks_per_record_identity=runtime.max_chunks_per_record_identity,
            record_identity_counts=state.record_identity_counts,
        ):
            state.dropped_record_identity += 1
            return

        state.kept.append(result)
        self._remember_near_simhash(meta, near_enabled=runtime.near_enabled, kept_simhashes=state.kept_simhashes)

    def _deduplicate_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not results or not bool(self.dedup_enabled):
            return results

        runtime = self._dedup_runtime()
        state = self._new_dedup_state()

        for result in results:
            self._keep_dedup_result(result, runtime=runtime, state=state)

        self._record_dedup_metrics(
            near_enabled=runtime.near_enabled,
            near_thr=runtime.near_thr,
            near_max_compare=runtime.near_max_compare,
            dropped_near=state.dropped_near,
            dropped_content_hash=state.dropped_content_hash,
            dropped_record_identity=state.dropped_record_identity,
            max_chunks_per_record_identity=runtime.max_chunks_per_record_identity,
        )
        return state.kept

    def _diversity_page_key(self, result: dict[str, Any]) -> tuple[str, int] | None:
        meta = result.get("metadata") or {}
        doc_id = self._get_doc_id(result)
        if not doc_id:
            return None
        raw = meta.get("page_number")
        if raw is None:
            raw = meta.get("page")
        if raw is None:
            return None
        try:
            return (doc_id, int(raw))
        except (TypeError, ValueError, AttributeError):
            return None

    def _diversity_top_stats(
        self,
        results: list[dict[str, Any]],
        *,
        top_k: int,
    ) -> tuple[set[str], set[str], set[tuple[str, int]]]:
        pre_top = (results or [])[: max(0, int(top_k or 0))]
        pre_keys = {self._result_key(r) for r in pre_top}
        pre_docs = {did for did in (self._get_doc_id(r) for r in pre_top) if did}
        pre_pages = {pk for pk in (self._diversity_page_key(r) for r in pre_top) if pk is not None}
        return pre_keys, pre_docs, pre_pages

    @staticmethod
    def _init_document_diversity_stats(
        stats: dict[str, Any] | None,
        *,
        max_per_doc: int,
        max_per_page: int,
        min_docs: int,
        pre_docs_count: int,
        pre_pages_count: int,
    ) -> None:
        if stats is not None:
            stats.clear()
            stats.update(
                {
                    "max_chunks_per_doc": int(max_per_doc),
                    "max_chunks_per_page": int(max_per_page),
                    "min_distinct_docs": int(min_docs),
                    "pre_unique_docs": int(pre_docs_count),
                    "pre_unique_pages": int(pre_pages_count),
                }
            )

    @staticmethod
    def _set_document_diversity_output_stats(
        stats: dict[str, Any] | None,
        *,
        post_docs_count: int,
        post_pages_count: int,
        moved_out: int,
        moved_in: int,
    ) -> None:
        if stats is None:
            return
        stats.update(
            {
                "post_unique_docs": int(post_docs_count),
                "post_unique_pages": int(post_pages_count),
                "moved_out": int(moved_out),
                "moved_in": int(moved_in),
            }
        )

    def _document_diversity_groups(self, results: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in results:
            groups.setdefault(self._get_doc_id(r), []).append(r)
        return groups

    @staticmethod
    def _document_diversity_must_have(
        groups: dict[str, list[dict[str, Any]]],
        *,
        min_docs: int,
        top_k: int,
    ) -> list[dict[str, Any]]:
        if min_docs <= 0:
            return []
        firsts = [items[0] for items in groups.values() if items]
        firsts.sort(key=lambda x: float(x.get("score", 0.0) or 0.0), reverse=True)
        return firsts[: max(0, min(min_docs, len(firsts), top_k))]

    def _remember_document_diversity_selection(
        self,
        result: dict[str, Any],
        *,
        selected: list[dict[str, Any]],
        used_keys: set[str],
        per_doc: Counter,
        per_page: Counter,
    ) -> None:
        used_keys.add(self._result_key(result))
        selected.append(result)
        per_doc[self._get_doc_id(result)] += 1
        page_key = self._diversity_page_key(result)
        if page_key is not None:
            per_page[page_key] += 1

    def _document_diversity_candidate_allowed(
        self,
        result: dict[str, Any],
        *,
        max_per_doc: int,
        max_per_page: int,
        per_doc: Counter,
        per_page: Counter,
    ) -> bool:
        doc_id = self._get_doc_id(result)
        if max_per_doc > 0 and per_doc[doc_id] >= max_per_doc:
            return False
        page_key = self._diversity_page_key(result)
        return not (max_per_page > 0 and page_key is not None and per_page[page_key] >= max_per_page)

    def _select_document_diversity_must_have(
        self,
        must_have: list[dict[str, Any]],
        *,
        selected: list[dict[str, Any]],
        used_keys: set[str],
        per_doc: Counter,
        per_page: Counter,
    ) -> None:
        for result in must_have:
            key = self._result_key(result)
            if key in used_keys:
                continue
            self._remember_document_diversity_selection(
                result,
                selected=selected,
                used_keys=used_keys,
                per_doc=per_doc,
                per_page=per_page,
            )

    def _select_document_diversity_primary(
        self,
        results: list[dict[str, Any]],
        *,
        selected: list[dict[str, Any]],
        used_keys: set[str],
        per_doc: Counter,
        per_page: Counter,
        top_k: int,
        max_per_doc: int,
        max_per_page: int,
    ) -> list[dict[str, Any]]:
        overflow: list[dict[str, Any]] = []
        for result in results:
            if len(selected) >= top_k:
                break
            key = self._result_key(result)
            if key in used_keys:
                continue
            if not self._document_diversity_candidate_allowed(
                result,
                max_per_doc=max_per_doc,
                max_per_page=max_per_page,
                per_doc=per_doc,
                per_page=per_page,
            ):
                overflow.append(result)
                continue
            self._remember_document_diversity_selection(
                result,
                selected=selected,
                used_keys=used_keys,
                per_doc=per_doc,
                per_page=per_page,
            )
        return overflow

    def _fill_document_diversity_overflow(
        self,
        overflow: list[dict[str, Any]],
        *,
        selected: list[dict[str, Any]],
        used_keys: set[str],
        top_k: int,
    ) -> None:
        for result in overflow:
            if len(selected) >= top_k:
                break
            key = self._result_key(result)
            if key in used_keys:
                continue
            used_keys.add(key)
            selected.append(result)

    def _select_document_diversity_results(
        self,
        results: list[dict[str, Any]],
        *,
        top_k: int,
        max_per_doc: int,
        max_per_page: int,
        min_docs: int,
    ) -> tuple[list[dict[str, Any]], set[str]]:
        groups = self._document_diversity_groups(results)
        must_have = self._document_diversity_must_have(groups, min_docs=min_docs, top_k=top_k)
        selected: list[dict[str, Any]] = []
        used_keys: set[str] = set()
        per_doc: Counter = Counter()
        per_page: Counter = Counter()

        self._select_document_diversity_must_have(
            must_have,
            selected=selected,
            used_keys=used_keys,
            per_doc=per_doc,
            per_page=per_page,
        )
        overflow = self._select_document_diversity_primary(
            results,
            selected=selected,
            used_keys=used_keys,
            per_doc=per_doc,
            per_page=per_page,
            top_k=top_k,
            max_per_doc=max_per_doc,
            max_per_page=max_per_page,
        )
        if len(selected) < top_k and overflow:
            self._fill_document_diversity_overflow(
                overflow,
                selected=selected,
                used_keys=used_keys,
                top_k=top_k,
            )
        return selected, used_keys

    def _record_document_diversity_post_stats(
        self,
        *,
        stats: dict[str, Any] | None,
        out_all: list[dict[str, Any]],
        top_k: int,
        pre_keys: set[str],
    ) -> None:
        if stats is None:
            return
        post_top = out_all[: max(0, int(top_k or 0))]
        post_keys = {self._result_key(r) for r in post_top}
        post_docs = {did for did in (self._get_doc_id(r) for r in post_top) if did}
        post_pages = {pk for pk in (self._diversity_page_key(r) for r in post_top) if pk is not None}
        self._set_document_diversity_output_stats(
            stats,
            post_docs_count=len(post_docs),
            post_pages_count=len(post_pages),
            moved_out=len(pre_keys - post_keys),
            moved_in=len(post_keys - pre_keys),
        )

    def _apply_document_diversity(
        self,
        results: list[dict[str, Any]],
        *,
        top_k: int,
        stats: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        max_per_doc = int(self.max_chunks_per_doc or 0)
        max_per_page = int(getattr(self, "max_chunks_per_page", 0) or 0)
        min_docs = int(self.min_distinct_docs or 0)
        pre_keys, pre_docs, pre_pages = self._diversity_top_stats(results, top_k=top_k)
        self._init_document_diversity_stats(
            stats,
            max_per_doc=max_per_doc,
            max_per_page=max_per_page,
            min_docs=min_docs,
            pre_docs_count=len(pre_docs),
            pre_pages_count=len(pre_pages),
        )

        if not results:
            self._set_document_diversity_output_stats(
                stats,
                post_docs_count=0,
                post_pages_count=0,
                moved_out=0,
                moved_in=0,
            )
            return results

        if max_per_doc <= 0 and max_per_page <= 0 and min_docs <= 0:
            self._set_document_diversity_output_stats(
                stats,
                post_docs_count=len(pre_docs),
                post_pages_count=len(pre_pages),
                moved_out=0,
                moved_in=0,
            )
            return results

        selected, used_keys = self._select_document_diversity_results(
            results,
            top_k=top_k,
            max_per_doc=max_per_doc,
            max_per_page=max_per_page,
            min_docs=min_docs,
        )

        if len(selected) >= len(results):
            out_all = selected
        else:
            rest = [r for r in results if self._result_key(r) not in used_keys]
            out_all = selected + rest
        if any(isinstance(item, dict) and item.get("fusion_budgeted_prefix_rank") is not None for item in out_all):
            def _budgeted_prefix_sort_key(item: dict[str, Any]) -> tuple[int, float, str]:
                return (
                    0 if item.get("fusion_budgeted_prefix_rank") is not None else 1,
                    -float(item.get("score", 0.0) or 0.0),
                    self._result_key(item),
                )

            # Keep the diversity-selected top-k set authoritative. Budgeted fusion
            # may order that set, but candidates in the remainder must not jump
            # back into it after document/page caps have been applied.
            selected_count = len(selected)
            out_all = sorted(out_all[:selected_count], key=_budgeted_prefix_sort_key) + out_all[selected_count:]

        self._record_document_diversity_post_stats(stats=stats, out_all=out_all, top_k=top_k, pre_keys=pre_keys)
        return out_all
