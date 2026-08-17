from __future__ import annotations

import hashlib
import json
import sys
import types
import uuid
from types import SimpleNamespace

import pytest

from app.rag.kg.extraction.relation_processor import CandidateEntity, RelationProcessor
from app.rag.kg.extraction.relation_verifier import RelationCandidate, RelationVerifier
from app.rag.preprocessing.frontmatter import extract_markdown_frontmatter
from app.rag.preprocessing.keyword import _normalize_hanlp_tokens
from app.rag.reranker.cross_encoder import CrossEncoderReranker
from app.rag.reranker.ltr import LTRFeatureSpec, LTRReranker
from app.rag.reranker.types import RerankCandidate
from app.rag.retrieval.hybrid.lexical import LexicalDBMixin
from app.services.dify_integration.metadata_condition_helpers import (
    MetadataConditionValidationError,
    metadata_condition_to_filter,
)
from app.services.evidence_drift_audit_service import audit_reference_sources_drift
from app.services.image_embedding_index import index_clip_image_embeddings_for_dataset
from app.services.rag_config_template_resolver import resolve_rag_config_template


class _FakeAsyncLLM:
    def __init__(self, *, result: dict[str, object] | None = None, exc: Exception | None = None) -> None:
        self._result = result or {}
        self._exc = exc
        self.calls: list[dict[str, object]] = []

    async def chat_with_schema(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        if self._exc is not None:
            raise self._exc
        return self._result


class _ListWithToList(list[float]):
    def tolist(self) -> list[float]:
        return list(self)


class _FakeCrossEncoderModel:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.batches: list[list[tuple[str, str]]] = []

    def predict(self, batch: list[tuple[str, str]]) -> object:
        self.batches.append(list(batch))
        return self._responses.pop(0)


class _FakeQuery:
    def __init__(self, rows) -> None:
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSequentialDB:
    def __init__(self, *query_rows) -> None:
        self._query_rows = list(query_rows)

    def query(self, *args, **kwargs):
        return _FakeQuery(self._query_rows.pop(0))


@pytest.mark.asyncio
async def test_relation_processor_extract_relations_preserves_normalization_and_allowlist_contract() -> None:
    llm = _FakeAsyncLLM(
        result={
            "relations": [
                {
                    "subject_id": "E1",
                    "predicate": "works at",
                    "object_id": "E2",
                    "confidence": "0.9",
                    "qualifiers": {"since": "2024"},
                    "evidence_quote": "Alice works at Acme.",
                },
                {
                    "subject_id": "E1",
                    "predicate": "located_in",
                    "object_id": "E2",
                    "confidence": "nan",
                    "qualifiers": ["ignore-me"],
                    "evidence_quote": "",
                },
                {"subject_id": "E1", "predicate": "alias_of", "object_id": "E1"},
                {"subject_id": "E9", "predicate": "works_for", "object_id": "E2"},
            ]
        }
    )
    processor = RelationProcessor(llm, allowed_predicates=["works_for"])

    relations = await processor.extract_relations(
        text="Alice works at Acme.",
        candidates=[
            CandidateEntity(cid="E1", name="Alice", type="person"),
            CandidateEntity(cid="E2", name="Acme", type="org"),
            CandidateEntity(cid="", name="skip"),
        ],
        max_relations=3,
    )

    assert relations == [
        {
            "subject_id": "E1",
            "predicate": "works_for",
            "predicate_raw": "works at",
            "object_id": "E2",
            "confidence": 0.9,
            "qualifiers": {"since": "2024"},
            "evidence_quote": "Alice works at Acme.",
        },
        {
            "subject_id": "E1",
            "predicate": "unknown",
            "predicate_raw": "located_in",
            "object_id": "E2",
            "confidence": 0.5,
            "qualifiers": None,
            "evidence_quote": None,
        },
    ]
    assert "Allowed predicates (if applicable): works_for" in llm.calls[0]["messages"][0].content


@pytest.mark.asyncio
async def test_relation_verifier_verify_preserves_dedup_and_evidence_trimming() -> None:
    llm = _FakeAsyncLLM(
        result={
            "kept": [
                {
                    "rid": "R1",
                    "predicate": "works at",
                    "confidence": "nan",
                    "evidence_quote": "x" * 320,
                },
                {"rid": "R1", "predicate": "works_for", "confidence": 0.1},
                {"rid": "R2", "predicate": "located_in", "confidence": 0.8},
                {"rid": "R9", "predicate": "works_for", "confidence": 0.8},
            ]
        }
    )
    verifier = RelationVerifier(llm, allowed_predicates=["works_for"])

    result = await verifier.verify(
        text="Alice works at Acme.",
        candidates=[
            RelationCandidate(rid="R1", subject_id="E1", predicate="works_for", object_id="E2"),
            RelationCandidate(rid="R2", subject_id="E1", predicate="located_in", object_id="E2"),
        ],
        max_keep=4,
    )

    assert result == {
        "kept": [
            {
                "rid": "R1",
                "predicate": "works_for",
                "confidence": 0.7,
                "evidence_quote": "x" * 300,
            }
        ]
    }


def test_extract_markdown_frontmatter_preserves_list_and_strip_output_contract() -> None:
    text = (
        "---\n"
        "title: Example Doc\n"
        "tags: [alpha, 'beta']\n"
        "authors:\n"
        "  - Alice\n"
        "  - 'Bob'\n"
        "draft: true\n"
        "---\n"
        "\n"
        "# Body\n"
    )

    result = extract_markdown_frontmatter(text, strip=True)

    assert result is not None
    assert result.data == {
        "title": "Example Doc",
        "tags": ["alpha", "beta"],
        "authors": ["Alice", "Bob"],
        "draft": True,
    }
    assert result.stripped_text == "# Body\n"
    assert result.changed is True
    assert result.start_char == 0
    assert result.end_char == len(result.raw)


def test_normalize_hanlp_tokens_prefers_known_keys_and_first_non_empty_fallback() -> None:
    assert _normalize_hanlp_tokens({"tok/coarse": [" Alpha ", None, 3], "ignored": ["beta"]}) == ["Alpha", "3"]
    assert _normalize_hanlp_tokens({"unused": [], "fallback": " Gamma Delta "}) == ["Gamma", "Delta"]


def test_cross_encoder_rerank_preserves_sorting_and_top_n_contracts() -> None:
    model = _FakeCrossEncoderModel(
        responses=[
            _ListWithToList([0.2, 0.9]),
            (0.5,),
        ]
    )
    reranker = CrossEncoderReranker(model_name="fake-model", model=model)

    result = reranker.rerank(
        "query",
        [
            RerankCandidate(id="a", text="A" * 20),
            RerankCandidate(id=" ", text="skip blank id"),
            RerankCandidate(id="b", text="B" * 20),
            RerankCandidate(id="c", text="keep"),
            RerankCandidate(id="d", text=""),
        ],
        batch_size=2,
        max_chars=5,
        top_n=2,
    )

    assert result.ordered_ids == ["b", "c"]
    assert result.score_map == {"b": 0.9, "c": 0.5}
    assert result.stats == {
        "provider": "cross_encoder",
        "model": "fake-model",
        "docs": 3,
        "batch_size": 2,
    }
    assert model.batches == [
        [("query", "AAAAA..."), ("query", "BBBBB...")],
        [("query", "keep")],
    ]


def test_ltr_reranker_init_preserves_manifest_validation_and_sha_model_id(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_path = tmp_path / "model.bin"
    model_path.write_bytes(b"ltr-model")
    sha = hashlib.sha256(b"ltr-model").hexdigest()
    spec = LTRFeatureSpec.default()
    (tmp_path / "model.manifest.json").write_text(
        json.dumps(
            {
                "schema": "mimirq.ltr_model_manifest.v1",
                "feature_schema": spec.schema,
                "feature_names": list(spec.feature_names),
                "model_sha256": sha,
            }
        ),
        encoding="utf-8",
    )

    loaded_paths: list[str] = []

    class _FakeBooster:
        def load_model(self, path: str) -> None:
            loaded_paths.append(path)

    monkeypatch.setitem(sys.modules, "xgboost", types.SimpleNamespace(Booster=_FakeBooster))

    reranker = LTRReranker(model_path=str(model_path))

    assert loaded_paths == [str(model_path)]
    assert vars(reranker)["_manifest"] == {
        "schema": "mimirq.ltr_model_manifest.v1",
        "feature_schema": spec.schema,
        "feature_names": list(spec.feature_names),
        "model_sha256": sha,
    }
    assert vars(reranker)["_model_id"] == f"sha256:{sha[:12]}"


def test_collect_lexical_dataset_scope_preserves_current_and_or_semantics() -> None:
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()

    assert LexicalDBMixin._collect_lexical_dataset_scope({"dataset_id": {"$in": [str(dataset_a), str(dataset_a)]}}) == [
        dataset_a
    ]
    assert LexicalDBMixin._collect_lexical_dataset_scope(
        {
            "$and": [
                {"dataset_id": str(dataset_a)},
                {"$or": [{"dataset_id": str(dataset_b)}, {"dataset_id": str(dataset_a)}]},
            ]
        }
    ) == [dataset_a, dataset_b]
    assert LexicalDBMixin._collect_lexical_dataset_scope(
        {"$or": [{"dataset_id": str(dataset_a)}, {"other": "missing-scope"}]}
    ) == []


def test_metadata_condition_to_filter_preserves_explicit_filters_and_allowed_field_validation() -> None:
    assert metadata_condition_to_filter(
        {"metadata_filter": {"category": {"$eq": "contract"}}},
        allowed_fields={"category"},
    ) == {"category": {"$eq": "contract"}}

    with pytest.raises(MetadataConditionValidationError, match="not allowed"):
        metadata_condition_to_filter(
            {"metadata_filter": {"secret": {"$eq": "x"}}},
            allowed_fields={"category"},
        )


def test_audit_reference_sources_drift_preserves_invalid_ref_accounting_and_slice_payloads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.evidence_drift_audit_service as audit_mod

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    suite_id = uuid.uuid4()
    item_id = uuid.uuid4()
    document_id = uuid.uuid4()
    chunk_id = uuid.uuid4()

    monkeypatch.setattr(
        audit_mod,
        "build_drift_slice_keys",
        lambda **kwargs: SimpleNamespace(
            file_type=str(kwargs["document_file_type"] or "unknown"),
            language="en",
            quality_bucket="high",
            directory="docs",
        ),
        raising=True,
    )
    monkeypatch.setattr(
        audit_mod,
        "classify_reference_source_drift",
        lambda **kwargs: (False, "chunk_missing", {"chunk_id": "expected"}, {"chunk_id": "observed"}),
        raising=True,
    )

    db = _FakeSequentialDB(
        [(document_id, dataset_id, "pdf", {"language": "en"})],
        [(chunk_id, document_id, 4, {"section": "intro"}, None)],
    )
    items = [
        SimpleNamespace(
            id=item_id,
            suite_id=suite_id,
            dataset_id=dataset_id,
            status="approved",
            reference_sources=[
                {"document_id": str(document_id), "chunk_id": str(chunk_id)},
                "invalid-reference",
            ],
        )
    ]

    result = audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=suite_id,
        suite_dataset_id=None,
        items=items,
        include_details=True,
        details_limit=5,
        slice_top_n=3,
    )

    assert result.total_items == 1
    assert result.total_references == 2
    assert result.ok_references == 0
    assert result.drift_references == 2
    assert result.drift_rate == 1.0
    assert result.reasons == {"chunk_missing": 1, "invalid_reference": 1}
    assert result.slices["file_type"]["pdf"].model_dump() == {
        "total": 1,
        "ok": 0,
        "drift": 1,
        "drift_rate": 1.0,
        "reasons": {"chunk_missing": 1},
    }
    assert result.drifted_references[0].model_dump()["slice"] == {
        "file_type": "pdf",
        "language": "en",
        "quality_bucket": "high",
        "directory": "docs",
    }


def test_index_clip_image_embeddings_for_dataset_preserves_skip_fail_and_index_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.image_embedding_index as image_mod

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    kept_chunk_id = uuid.uuid4()

    monkeypatch.setattr(image_mod.settings, "IMAGE_EMBEDDING_ENABLED", True, raising=False)
    monkeypatch.setattr(image_mod.settings, "IMAGE_EMBEDDING_COLLECTION_NAME", "images", raising=False)
    monkeypatch.setattr(image_mod.settings, "MINIO_IMAGE_MAX_BYTES", 0, raising=False)
    monkeypatch.setattr(image_mod, "resolve_collection_name", lambda value: value, raising=True)
    monkeypatch.setattr(image_mod, "normalize_image_metadata", lambda meta: None, raising=True)

    seen_minio_ids: list[str] = []

    def _load_minio(*, img_id: str, max_bytes: int) -> bytes | None:
        seen_minio_ids.append(img_id)
        return None if img_id == "missing" else b"raw-image"

    monkeypatch.setattr(image_mod, "_load_image_bytes_from_minio", _load_minio, raising=True)
    monkeypatch.setattr(image_mod, "_load_image_bytes_from_local", lambda **kwargs: None, raising=True)
    monkeypatch.setattr(image_mod, "_load_pil_image_from_bytes", lambda raw: f"pil:{raw.decode()}", raising=True)
    monkeypatch.setattr(
        image_mod,
        "encode_clip_image",
        lambda pil: [] if pil == "pil:raw-image-fail" else ([0.1, 0.2] if pil == "pil:raw-image" else []),
        raising=True,
    )

    class _FakeAdapter:
        def __init__(self) -> None:
            self.calls: list[tuple[list[dict[str, object]], list[list[float]], bool]] = []

        def add_vectors(self, items, *, embeddings, upsert):
            self.calls.append((list(items), list(embeddings), bool(upsert)))

    adapter = _FakeAdapter()
    monkeypatch.setattr(image_mod, "get_milvus_adapter", lambda **kwargs: adapter, raising=True)

    rows = [
        SimpleNamespace(id=uuid.uuid4(), document_id=uuid.uuid4(), chunk_index=0, page_number=0, doc_metadata={}),
        SimpleNamespace(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=1,
            page_number=0,
            doc_metadata={"doc_type_kwd": "image", "img_id": "missing"},
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            document_id=uuid.uuid4(),
            chunk_index=2,
            page_number=0,
            doc_metadata={"doc_type_kwd": "image", "img_id": "fail"},
        ),
        SimpleNamespace(
            id=kept_chunk_id,
            document_id=uuid.uuid4(),
            chunk_index=3,
            page_number=7,
            doc_metadata={"doc_type_kwd": "image", "img_id": "ok", "image_url": "https://example/image.png"},
        ),
    ]

    def _load_minio_with_fail(*, img_id: str, max_bytes: int) -> bytes | None:
        seen_minio_ids.append(img_id)
        if img_id == "missing":
            return None
        if img_id == "fail":
            return b"raw-image-fail"
        return b"raw-image"

    monkeypatch.setattr(image_mod, "_load_image_bytes_from_minio", _load_minio_with_fail, raising=True)

    stats = index_clip_image_embeddings_for_dataset(
        db=_FakeSequentialDB(rows),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        max_chunks=10,
        upsert=False,
    )

    assert stats == image_mod.ImageIndexStats(indexed=1, skipped=2, failed=1, dim=2, errors=None)
    assert seen_minio_ids == ["missing", "fail", "ok"]
    assert adapter.calls == [
        (
            [
                {
                    "id": str(kept_chunk_id),
                    "content": "image",
                    "metadata": {
                        "tenant_id": str(tenant_id),
                        "dataset_id": str(dataset_id),
                        "document_id": str(rows[3].document_id),
                        "chunk_id": str(kept_chunk_id),
                        "chunk_index": 3,
                        "page_number": 7,
                        "img_id": "ok",
                        "image_id": "",
                        "image_url": "https://example/image.png",
                        "index_kind": "image",
                    },
                }
            ],
            [[0.1, 0.2]],
            False,
        )
    ]


def test_resolve_rag_config_template_adaptive_mode_preserves_exploit_and_debug_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_config_template_resolver as resolver_mod

    tenant_id = uuid.uuid4()
    variant_a = SimpleNamespace(id=uuid.uuid4(), ab_variant="A", ab_weight=1.0)
    variant_b = SimpleNamespace(id=uuid.uuid4(), ab_variant="B", ab_weight=1.0)

    def _stable(seed: str) -> float:
        if seed.endswith(":weighted"):
            return 0.1
        if seed.endswith(":adaptive:explore"):
            return 0.9
        if seed.endswith(":exploit_choice"):
            return 0.0
        raise AssertionError(f"unexpected seed: {seed}")

    monkeypatch.setattr(resolver_mod, "_stable_unit_interval", _stable, raising=True)

    chosen, debug = resolve_rag_config_template(
        db=_FakeSequentialDB([variant_a, variant_b]),
        tenant_id=tenant_id,
        ab_experiment_key="exp-1",
        ab_user_key="user-1",
        routing_mode="adaptive_epsilon_greedy",
        adaptive_epsilon=0.2,
        feedback_reward_hook=lambda _db, _tenant_id, exp, variants: [
            {"ab_variant": "A", "reward": 0.1},
            {"ab_variant": "B", "reward": 0.9},
        ],
        return_debug_metadata=True,
    )

    assert chosen is variant_b
    assert debug == {
        "strategy": "adaptive_epsilon_greedy",
        "epsilon": 0.2,
        "decision": "exploit",
        "chosen_variant": "B",
        "reward_snapshot": {
            "schema": "mimirq.rag_config_reward_snapshot.v1",
            "total_feedback": 2,
            "variants": {
                "A": {"count": 1, "avg_reward": 0.1, "avg_rating": None},
                "B": {"count": 1, "avg_reward": 0.9, "avg_rating": None},
            },
        },
        "weights": {"A": 1.0, "B": 1.0},
    }
