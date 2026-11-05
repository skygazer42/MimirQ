"""Milvus-native BM25: raw text in, scoped chunk candidates out."""

import json
import threading
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.core.exceptions import MimirQError
from app.rag.core.filters import match_metadata_filter
from app.rag.retrieval.hybrid.result_values import candidate_metadata_from_doc, result_content_from_doc

_SCHEMA_VERSION = "ragvia_native_bm25_v1:chinese"
_IDENTITY_FIELDS = frozenset({"chunk_id", "tenant_id", "dataset_id", "document_id"})
_OUTPUT_FIELDS = ["chunk_id", "tenant_id", "dataset_id", "document_id", "content", "metadata"]
_REQUIRED_FIELDS = {"id", "sparse", *_OUTPUT_FIELDS}


class BM25IndexNotReadyError(MimirQError):
    """Native full-text storage needs an explicit schema migration or backfill."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            error_code="BM25_INDEX_NOT_READY",
            status_code=503,
            detail={"hint": "请管理员预览并执行已有文档的 BM25 回填，并检查 Milvus 全文集合配置。"},
        )


def build_milvus_bm25_schema():  # noqa: ANN201
    from pymilvus import DataType, Function, FunctionType, MilvusClient

    schema = MilvusClient.create_schema(auto_id=False, enable_dynamic_field=False, description=_SCHEMA_VERSION)
    schema.add_field("id", DataType.VARCHAR, is_primary=True, max_length=512)
    schema.add_field("chunk_id", DataType.VARCHAR, max_length=128)
    for name in ("tenant_id", "dataset_id", "document_id"):
        schema.add_field(name, DataType.VARCHAR, max_length=36)
    schema.add_field(
        "content", DataType.VARCHAR, max_length=65535, enable_analyzer=True, analyzer_params={"type": "chinese"}
    )
    schema.add_field("metadata", DataType.JSON)
    schema.add_field("sparse", DataType.SPARSE_FLOAT_VECTOR)
    schema.add_function(
        Function(
            name="content_bm25",
            function_type=FunctionType.BM25,
            input_field_names=["content"],
            output_field_names=["sparse"],
        )
    )
    return schema


def build_milvus_bm25_indexes():  # noqa: ANN201
    from pymilvus import MilvusClient

    indexes = MilvusClient.prepare_index_params()
    indexes.add_index(
        field_name="sparse",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
        params={"inverted_index_algo": "DAAT_MAXSCORE"},
    )
    return indexes


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


class _IdentityPushdown:
    """Push scalar identities down; retain the full matcher for all other metadata."""

    def __init__(self) -> None:
        self.nodes = 0

    def expression(self, specification: dict[str, Any], depth: int = 0) -> tuple[str, bool]:
        self.nodes += len(specification)
        if depth > 8 or self.nodes > 200:
            raise ValueError("BM25 metadata filter exceeds the supported complexity")
        parts, exact = [], True
        for key, value in specification.items():
            if key in {"$and", "$or"}:
                if not isinstance(value, list) or not value or not all(isinstance(item, dict) for item in value):
                    raise ValueError("Invalid BM25 boolean metadata filter")
                children = [self.expression(item, depth + 1) for item in value]
                child_exact = all(item[1] for item in children)
                if key == "$or" and any(not text and item_exact for text, item_exact in children):
                    exact = exact and child_exact
                    continue
                if key == "$or" and not child_exact:
                    exact = False
                    continue
                clauses = [f"({text})" for text, _ in children if text]
                if clauses:
                    parts.append((" and " if key == "$and" else " or ").join(clauses))
                exact = exact and child_exact
            elif key in _IDENTITY_FIELDS:
                condition = value if isinstance(value, dict) else {"$eq": value}
                for operator, expected in condition.items():
                    if operator not in {"$eq", "$ne", "$in", "$nin"} or expected is None:
                        exact = False
                        continue
                    if operator in {"$in", "$nin"} and not isinstance(expected, list):
                        raise ValueError("BM25 identity membership filter requires a list")
                    symbol = {"$eq": "==", "$ne": "!=", "$in": "in", "$nin": "not in"}[operator]
                    parts.append(f"{key} {symbol} {_literal(expected)}")
            else:
                exact = False
        return " and ".join(f"({part})" for part in parts), exact


def _scoped_filter(tenant_id: UUID, metadata_filter: dict[str, Any] | None) -> tuple[str, bool]:
    if tenant_id is None:
        raise ValueError("BM25 requires an explicit tenant")
    expression, exact = _IdentityPushdown().expression(metadata_filter or {})
    tenant = f"tenant_id == {_literal(str(tenant_id))}"
    return (f"({tenant}) and ({expression})" if expression else tenant), exact


def _entity_metadata(entity: dict[str, Any]) -> dict[str, Any]:
    return {**entity["metadata"], **{name: entity[name] for name in _IDENTITY_FIELDS}}


class MilvusBM25Store:
    def __init__(self, *, client: Any = None, collection_name: str | None = None) -> None:
        self.collection_name = collection_name or settings.MILVUS_BM25_COLLECTION_NAME
        self._client = client
        self._schema_checked = False
        self._lock = threading.RLock()

    def _get_client(self):  # noqa: ANN202
        with self._lock:
            if self._client is None:
                from pymilvus import MilvusClient

                self._client = MilvusClient(
                    uri=f"http://{settings.MILVUS_HOST}:{settings.MILVUS_PORT}",
                    user=settings.MILVUS_USER,
                    password=settings.MILVUS_PASSWORD,
                    timeout=settings.MILVUS_BM25_TIMEOUT_SEC,
                )
            return self._client

    def initialize(self) -> None:
        """Explicitly initialize an empty native index for an operator backfill."""
        self._require_collection(create=True)

    def _require_collection(self, *, create: bool = False):  # noqa: ANN202
        client = self._get_client()
        with self._lock:
            if self._schema_checked:
                return client
            if not client.has_collection(
                collection_name=self.collection_name, timeout=settings.MILVUS_BM25_TIMEOUT_SEC
            ):
                if not create:
                    raise BM25IndexNotReadyError(
                        "Milvus BM25 collection is missing; run the explicit BM25 backfill with --apply"
                    )
                client.create_collection(
                    collection_name=self.collection_name,
                    schema=build_milvus_bm25_schema(),
                    index_params=build_milvus_bm25_indexes(),
                    consistency_level="Strong",
                    timeout=settings.MILVUS_BM25_TIMEOUT_SEC,
                )
            schema = client.describe_collection(
                collection_name=self.collection_name, timeout=settings.MILVUS_BM25_TIMEOUT_SEC
            )
            field_definitions = {field["name"]: field for field in schema["fields"]}
            fields = set(field_definitions)
            text_params = field_definitions.get("content", {}).get("params", {})
            analyzer = text_params.get("analyzer_params")
            if isinstance(analyzer, str):
                analyzer = json.loads(analyzer)
            analyzed = text_params.get("enable_analyzer") is True and analyzer == {"type": "chinese"}
            functions = schema.get("functions", [])
            native = any(
                function.get("name") == "content_bm25"
                and function.get("type") == 1  # pymilvus FunctionType.BM25
                and function.get("input_field_names") == ["content"]
                and function.get("output_field_names") == ["sparse"]
                for function in functions
            )
            if (
                schema.get("description") != _SCHEMA_VERSION
                or not _REQUIRED_FIELDS.issubset(fields)
                or not native
                or not analyzed
            ):
                raise BM25IndexNotReadyError(
                    "Milvus BM25 schema is incompatible; select a new full-text collection and backfill it explicitly"
                )
            self._schema_checked = True
        return client

    def upsert(self, documents: list[Document], *, tenant_id: UUID) -> int:
        _scoped_filter(tenant_id, None)
        rows = []
        for document in documents:
            metadata = dict(document.metadata)
            if metadata.get("tenant_id") is not None and str(metadata["tenant_id"]) != str(tenant_id):
                raise ValueError("BM25 document tenant does not match its write scope")
            if document.id is None or not metadata.get("document_id"):
                raise ValueError("BM25 upsert requires chunk and document identities")
            if len(document.page_content.encode("utf-8")) > 65535:
                raise ValueError("BM25 chunk text exceeds the Milvus VARCHAR byte limit")
            identity = {
                "chunk_id": str(document.id),
                "tenant_id": str(tenant_id),
                "dataset_id": str(metadata.get("dataset_id") or ""),
                "document_id": str(metadata["document_id"]),
            }
            metadata.update(identity)
            rows.append(
                {"id": f"{tenant_id}:{document.id}", **identity, "content": document.page_content, "metadata": metadata}
            )
        if not rows:
            return 0
        client = self._require_collection(create=True)
        batch_size = max(1, settings.VECTOR_WRITE_BATCH_SIZE)
        for start in range(0, len(rows), batch_size):
            client.upsert(
                collection_name=self.collection_name,
                data=rows[start : start + batch_size],
                timeout=settings.MILVUS_BM25_TIMEOUT_SEC,
            )
        return len(rows)

    def search(
        self,
        query: str,
        *,
        tenant_id: UUID,
        dataset_ids: tuple[UUID, ...] = (),
        document_ids: tuple[UUID, ...] = (),
        metadata_filter: dict[str, Any] | None = None,
        top_k: int = 10,
    ) -> list[dict[str, Any]]:
        if not query.strip() or top_k <= 0:
            return []
        expression, _ = _scoped_filter(tenant_id, metadata_filter)
        if dataset_ids:
            expression += f" and dataset_id in {_literal([str(value) for value in dataset_ids])}"
        if document_ids:
            expression += f" and document_id in {_literal([str(value) for value in document_ids])}"
        client = self._require_collection()
        maximum = settings.MILVUS_BM25_MAX_CANDIDATES
        limit = min(max(32, top_k * 4), maximum)
        allowed_datasets, allowed_documents = set(map(str, dataset_ids)), set(map(str, document_ids))
        while True:
            hits = client.search(
                collection_name=self.collection_name,
                data=[query],
                anns_field="sparse",
                filter=expression,
                limit=limit,
                output_fields=_OUTPUT_FIELDS,
                search_params={"metric_type": "BM25", "params": {}},
                consistency_level="Strong",
                timeout=settings.MILVUS_BM25_TIMEOUT_SEC,
            )[0]
            results = []
            for hit in hits:
                entity = hit["entity"]
                if (
                    entity["tenant_id"] != str(tenant_id)
                    or (allowed_datasets and entity["dataset_id"] not in allowed_datasets)
                    or (allowed_documents and entity["document_id"] not in allowed_documents)
                ):
                    continue
                metadata = _entity_metadata(entity)
                if metadata_filter and not match_metadata_filter(metadata, metadata_filter):
                    continue
                score = float(hit["distance"])
                doc = Document(id=entity["chunk_id"], page_content=entity["content"], metadata=metadata)
                candidate = candidate_metadata_from_doc(metadata, chunk_id=entity["chunk_id"])
                candidate.update(bm25_score=score, bm25_score_raw=score, question_channel_score=0.0)
                results.append(
                    {
                        "chunk_id": entity["chunk_id"],
                        "content": result_content_from_doc(doc),
                        "metadata": candidate,
                        "score": score,
                    }
                )
            if len(results) >= top_k or len(hits) < limit or limit >= maximum:
                return results[:top_k]
            limit = min(limit * 2, maximum)

    def delete(self, *, tenant_id: UUID, metadata_filter: dict[str, Any]) -> int:
        if not metadata_filter:
            raise ValueError("BM25 deletion requires a nonempty metadata filter")
        expression, exact = _scoped_filter(tenant_id, metadata_filter)
        client = self._get_client()
        if not self._schema_checked and not client.has_collection(
            collection_name=self.collection_name, timeout=settings.MILVUS_BM25_TIMEOUT_SEC
        ):
            return 0
        client = self._require_collection()
        if exact:
            return int(
                client.delete(
                    collection_name=self.collection_name, filter=expression, timeout=settings.MILVUS_BM25_TIMEOUT_SEC
                )["delete_count"]
            )
        iterator = client.query_iterator(
            collection_name=self.collection_name,
            filter=expression,
            batch_size=500,
            output_fields=["id", *_OUTPUT_FIELDS],
            consistency_level="Strong",
            timeout=settings.MILVUS_BM25_TIMEOUT_SEC,
        )
        deleted = 0
        try:
            while rows := iterator.next():
                ids = [
                    row["id"]
                    for row in rows
                    if row["tenant_id"] == str(tenant_id)
                    and row["id"].startswith(f"{tenant_id}:")
                    and match_metadata_filter(_entity_metadata(row), metadata_filter)
                ]
                if ids:
                    deleted += int(
                        client.delete(
                            collection_name=self.collection_name, ids=ids, timeout=settings.MILVUS_BM25_TIMEOUT_SEC
                        )["delete_count"]
                    )
        finally:
            iterator.close()
        return deleted


_shared_bm25_store = MilvusBM25Store()


def get_bm25_store() -> MilvusBM25Store:
    return _shared_bm25_store
