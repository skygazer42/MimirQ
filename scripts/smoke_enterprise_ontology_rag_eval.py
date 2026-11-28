"""Compare ordinary RAG and active ontology chat on the same labeled PDF corpus.

Run with `python -m scripts.smoke_enterprise_ontology_rag_eval` after exporting
the isolated PostgreSQL DATABASE_URL and the usual chat and embedding settings.
"""

import json
import os
import re
from dataclasses import asdict, dataclass
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from fastapi.testclient import TestClient

    from app.api.schemas.conversations import ChatResponse

ONTOLOGIES = "/api/v1/kg/ontologies"
OWNER = "ontology-rag-eval-owner"
READER = "ontology-rag-eval-reader"
ORDER_RELATION = "order_for_equipment"
LINE_RELATION = "equipment_on_line"
TWO_HOPS = (ORDER_RELATION, LINE_RELATION)
BUSINESS_ID = re.compile(r"(?<![A-Z0-9_-])(?:WO-\d+|E-\d+|LINE-[A-Z0-9]+)(?![A-Z0-9_-])", re.IGNORECASE)
UNAVAILABLE = re.compile(
    r"未找到|缺少|未提及|没有(?:足够|提供|明确|可用|相关|依据|记录)|无(?:法|可|据)|不能(?:确认|确定|推断|回答)"
    r"|信息不足|证据不足|不可用|cannot (?:verify|determine|confirm)|insufficient (?:information|evidence)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FixtureDocument:
    filename: str
    text: str
    fact: str


DOCUMENTS = {
    "work_order": FixtureDocument("维修工单.pdf", "维修工单 WO-01 归属于设备 E-102。", "WO-01 归属于设备 E-102"),
    "installation": FixtureDocument("安装台账.pdf", "设备水泵 E-102 安装在产线 LINE-A。", "E-102 安装在产线 LINE-A"),
    "same_name": FixtureDocument("同名设备台账.pdf", "设备水泵 E-103 安装在产线 LINE-B。", "E-103 安装在产线 LINE-B"),
    "expired_installation": FixtureDocument(
        "已失效安装台账.pdf", "设备 E-104 安装在产线 LINE-C。", "E-104 安装在产线 LINE-C"
    ),
}

DEFINITION = {
    "schema_version": 1,
    "ontology": "maintenance",
    "object_types": {
        name: {"label": label, "key": ["id"], "properties": {"id": "string"}}
        for name, label in (("work_order", "维修工单"), ("equipment", "设备"), ("production_line", "产线"))
    },
    "relations": {
        ORDER_RELATION: {
            "label": "工单归属于设备",
            "from": "work_order",
            "to": "equipment",
            "cardinality": "many_to_one",
        },
        LINE_RELATION: {
            "label": "设备安装在产线",
            "from": "equipment",
            "to": "production_line",
            "cardinality": "many_to_one",
        },
    },
}

TWO_HOP_QUESTION = "维修工单 WO-01 归属的设备安装在哪条产线？请沿工单→设备→产线查两跳，引用两段原文。"


@dataclass(frozen=True)
class Case:
    question: str
    object_type: str
    business_key: str
    relations: tuple[str, ...]
    answer: str | None = None
    facts: tuple[str, ...] = ()
    document_scope: tuple[str, ...] = ()
    reader: str = OWNER


CASES = {
    "direct_equipment": Case(
        "维修工单 WO-01 归属于哪台设备（order_for_equipment）？请引用工单原文。",
        "work_order",
        "WO-01",
        (ORDER_RELATION,),
        "E-102",
        ("work_order",),
    ),
    "direct_line": Case(
        "设备 E-102 安装在哪条产线（equipment_on_line）？请引用安装台账原文。",
        "equipment",
        "E-102",
        (LINE_RELATION,),
        "LINE-A",
        ("installation",),
    ),
    "two_hop": Case(TWO_HOP_QUESTION, "work_order", "WO-01", TWO_HOPS, "LINE-A", ("work_order", "installation")),
    "unknown": Case(TWO_HOP_QUESTION.replace("WO-01", "WO-99"), "work_order", "WO-99", TWO_HOPS),
    "constrained": Case(
        TWO_HOP_QUESTION,
        "work_order",
        "WO-01",
        TWO_HOPS,
        document_scope=("work_order", "same_name"),
    ),
    "expired": Case(
        "按现行有效的台账，设备 E-104 安装在哪条产线（equipment_on_line）？请引用有效台账原文。",
        "equipment",
        "E-104",
        (LINE_RELATION,),
    ),
    "restricted": Case(TWO_HOP_QUESTION, "work_order", "WO-01", TWO_HOPS, reader=READER),
}


@dataclass(frozen=True)
class Score:
    route: str
    ontology_used: bool
    ontology_plan_matches: bool
    answer_correct: bool
    answer_ids: tuple[str, ...]
    explicitly_unavailable: bool
    expected_facts: tuple[str, ...]
    matched_facts: tuple[str, ...]
    citation_count: int
    unexpected_citations: tuple[str, ...]
    no_evidence_false_positive: bool

    @property
    def ontology_passed(self) -> bool:
        return (
            self.ontology_plan_matches
            and self.answer_correct
            and len(self.matched_facts) == len(self.expected_facts)
            and not self.unexpected_citations
        )


def score_turn(case: Case, response: "ChatResponse", documents: dict[str, UUID]) -> Score:
    ontology_used = bool(response.metrics.get("ontology_used"))
    plan = response.metrics.get("ontology_fusion", {}).get("plan")
    plan_matches = False
    if ontology_used and plan is not None:
        relations = plan["relation_path"] if len(case.relations) > 1 else [plan["relation_id"]]
        plan_matches = (
            plan["object_type"] == case.object_type
            and plan["business_key"] == case.business_key
            and relations == list(case.relations)
        )

    by_id = {document_id: label for label, document_id in documents.items()}
    matched = set()
    unexpected = []
    for citation in response.citations:
        label = by_id.get(citation.document_id, "unknown_document")
        if (
            label in case.facts
            and label not in matched
            and citation.page_number == 1
            and _contains_fact(citation.chunk_content, DOCUMENTS[label].fact)
        ):
            matched.add(label)
        else:
            unexpected.append(label)

    answer_ids = set(BUSINESS_ID.findall(response.content.upper()))
    allowed_ids = set(BUSINESS_ID.findall(case.question.upper()))
    for label in case.facts:
        allowed_ids.update(BUSINESS_ID.findall(DOCUMENTS[label].fact))
    if case.business_key == "WO-01":
        allowed_ids.add("E-102")
    explicitly_unavailable = bool(UNAVAILABLE.search(response.content))
    unexpected_ids = answer_ids - allowed_ids
    answer_correct = not unexpected_ids and (
        explicitly_unavailable if case.answer is None else case.answer in answer_ids and not explicitly_unavailable
    )
    return Score(
        route=response.metrics.get("route", "ordinary_rag"),
        ontology_used=ontology_used,
        ontology_plan_matches=plan_matches,
        answer_correct=answer_correct,
        answer_ids=tuple(sorted(answer_ids)),
        explicitly_unavailable=explicitly_unavailable,
        expected_facts=case.facts,
        matched_facts=tuple(label for label in case.facts if label in matched),
        citation_count=len(response.citations),
        unexpected_citations=tuple(unexpected),
        no_evidence_false_positive=case.answer is None and (not answer_correct or bool(response.citations)),
    )


def summarize(scores: list[Score]) -> dict[str, dict[str, int]]:
    matched_facts = sum(len(score.matched_facts) for score in scores)
    return {
        "answer_accuracy": {"hits": sum(score.answer_correct for score in scores), "total": len(scores)},
        "citation_precision": {"hits": matched_facts, "total": sum(score.citation_count for score in scores)},
        "citation_recall": {"hits": matched_facts, "total": sum(len(score.expected_facts) for score in scores)},
        "no_evidence_false_positive_rate": {
            "hits": sum(score.no_evidence_false_positive for score in scores),
            "total": sum(not score.expected_facts for score in scores),
        },
    }


def _contains_fact(quote: str, fact: str) -> bool:
    pattern = r"\s*".join(re.escape(part) for part in fact.split())
    return bool(re.search(rf"(?<![A-Za-z0-9_-]){pattern}(?![A-Za-z0-9_-])", quote))


def _pdf(content: str) -> bytes:
    import fitz

    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_font(fontname="fixture", fontbuffer=fitz.Font("cjk").buffer)
        page.insert_text((72, 72), content, fontname="fixture")
        pdf.subset_fonts()
        return pdf.tobytes(garbage=4, deflate=True)


def _request(client: "TestClient", method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    return client.request(method, path, **kwargs).raise_for_status().json()


def _evaluate(client: "TestClient", dataset_id: str, documents: dict[str, UUID]) -> dict[str, Score]:
    from app.api.schemas.conversations import ChatResponse

    scores = {}
    for name, case in CASES.items():
        turn = _request(
            client,
            "POST",
            "/api/v1/chat",
            headers={"X-User-ID": case.reader},
            json={
                "dataset_id": dataset_id,
                "document_ids": [str(documents[label]) for label in case.document_scope],
                "message": case.question,
                "stream": False,
                "structured_output": True,
                "rag_config": {"use_graph": False},
            },
        )
        scores[name] = score_turn(case, ChatResponse.model_validate(turn), documents)
    return scores


def _run() -> bool:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import text

    import app.models.registry  # noqa: F401
    from app.api.middleware.request_context import RequestContextMiddleware
    from app.api.v1 import get_router
    from app.infrastructure.config import settings
    from app.infrastructure.database.connection import SessionLocal
    from app.models.documents.records import Document
    from app.models.identity.workspaces import Tenant, TenantMember

    tenant_id = uuid4()
    with SessionLocal.begin() as db:
        if db.scalar(text("SELECT current_database()")) != "ontology_fixture":
            raise SystemExit("Connected database must be the isolated ontology_fixture database")
        db.add(Tenant(id=tenant_id, name=f"ontology-rag-eval-{tenant_id}"))
        db.add(TenantMember(tenant_id=tenant_id, user_id=OWNER, role="owner"))
        db.add(TenantMember(tenant_id=tenant_id, user_id=READER, role="viewer"))

    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.include_router(get_router(), prefix="/api/v1")
    with TestClient(app, headers={"X-Tenant-ID": str(tenant_id), "X-User-ID": OWNER}) as client:
        dataset = _request(client, "POST", "/api/v1/datasets/", json={"name": "维修问答标注集"})
        dataset_id = dataset["id"]
        documents = {}
        for label, fixture in DOCUMENTS.items():
            uploaded = _request(
                client,
                "POST",
                "/api/v1/documents/upload",
                data={
                    "dataset_id": dataset_id,
                    "parser_backend": "basic",
                },
                files={"file": (fixture.filename, _pdf(fixture.text), "application/pdf")},
            )
            documents[label] = UUID(uploaded["id"])
        with SessionLocal.begin() as db:
            for label, document_id in documents.items():
                document = db.get(Document, document_id)
                if (
                    document is None
                    or document.status != "completed"
                    or not document.doc_metadata["active_pipeline_ready"]
                ):
                    raise RuntimeError(f"Fixture upload was not indexed for {label}")
                document.doc_metadata = {**document.doc_metadata, "effective_at": "2000-01-01"}
                if label == "expired_installation":
                    document.doc_metadata = {**document.doc_metadata, "expires_at": "2001-01-01"}
        _request(client, "PUT", f"/api/v1/documents/{documents['installation']}/access", json={"mode": "only_me"})

        ordinary = _evaluate(client, dataset_id, documents)
        if any(score.ontology_used for score in ordinary.values()):
            raise RuntimeError("Ontology was active during the ordinary RAG baseline")

        workspace = _request(client, "POST", ONTOLOGIES, json=DEFINITION)
        versions = f"{ONTOLOGIES}/{workspace['id']}/versions"
        version = _request(client, "POST", versions, json={"expected_revision": workspace["draft_revision"]})
        for document_id in documents.values():
            _request(client, "POST", f"{versions}/{version['id']}/documents", json={"document_id": str(document_id)})
        for label in ("same_name", "expired_installation"):
            path = f"{versions}/{version['id']}/documents/{documents[label]}/evidence"
            previews = client.get(path).raise_for_status().json()
            if not any(
                relation["predicate"] == LINE_RELATION
                and _contains_fact(relation["evidence"]["quote"], DOCUMENTS[label].fact)
                for preview in previews
                if preview["page"] == 1
                for relation in preview["relations"]
            ):
                raise RuntimeError(f"Ontology extraction missed the control fact for {label}")
        _request(client, "PUT", f"{versions}/{version['id']}/datasets/{dataset_id}")
        ontology = _evaluate(client, dataset_id, documents)

    failures = [name for name, score in ontology.items() if not score.ontology_passed]
    print(
        json.dumps(
            {
                "llm_model": settings.LLM_MODEL,
                "embedding_model": settings.EMBEDDING_MODEL,
                "ordinary_rag": {
                    "summary": summarize(list(ordinary.values())),
                    "cases": {k: asdict(v) for k, v in ordinary.items()},
                },
                "enterprise_ontology": {
                    "summary": summarize(list(ontology.values())),
                    "cases": {k: asdict(v) for k, v in ontology.items()},
                },
                "ontology_failures": failures,
            },
            indent=2,
        )
    )
    return not failures


def main() -> int:
    database = urlsplit(os.environ.get("DATABASE_URL", ""))
    if database.path != "/ontology_fixture" or database.scheme.split("+")[0] not in {"postgres", "postgresql"}:
        raise SystemExit("Set DATABASE_URL to the migrated isolated PostgreSQL database named ontology_fixture")

    with TemporaryDirectory(prefix="mimirq-ontology-rag-eval-") as uploads:
        os.environ.update(
            {
                "AUTH_MODE": "header",
                "TASK_QUEUE_ENABLED": "false",
                "UPLOAD_DIR": uploads,
                "VECTOR_BACKEND": "memory",
                "BM25_INDEX_ENABLED": "false",
                "CHUNK_VECTOR_ENABLED": "true",
                "EMBEDDING_CACHE_ENABLED": "false",
                "OBJECT_STORAGE_ENABLED": "false",
                "OBJECT_STORAGE_DOCUMENTS_ENABLED": "false",
                "MINIO_ENABLED": "false",
                "MINIO_DOCUMENTS_ENABLED": "false",
                "KG_ENABLED": "true",
                "LLAMA_INDEX_ENABLED": "false",
                "LLM_MOCK_ENABLED": "false",
                "CHAT_RESPONSE_CACHE_ENABLED": "false",
                "CHAT_STREAM_PERSIST_IN_BACKGROUND": "false",
            }
        )
        return int(not _run())


if __name__ == "__main__":
    raise SystemExit(main())
