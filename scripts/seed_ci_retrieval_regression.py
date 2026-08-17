#!/usr/bin/env python3
"""
Seed a tiny deterministic dataset + documents/chunks for the retrieval-only regression gate.

This is intended for CI:
- no background queue required
- no vector DB required (lexical DB retrieval is sufficient)

It also exports a portable regression cases bundle (mimirq.regression_cases.v1).
"""

# The script must make the repository importable before loading app modules.
# ruff: noqa: E402

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import app.models._all  # noqa: F401
from app.core.database import Base, SessionLocal, engine
from app.core.migrations import apply_runtime_migrations
from app.models.dataset import Dataset, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.models.tenant import Tenant, TenantMember

MODEL_REGISTRY = app.models._all.REGISTERED_MODEL_MODULES


def _load_json(path: Path) -> Any:
    # PowerShell commonly writes UTF-8 JSON with BOM; `utf-8-sig` handles both BOM/no-BOM.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json_file(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_cases_bundle(fixture: dict[str, Any]) -> dict[str, Any]:
    ds = str((fixture.get("dataset") or {}).get("id") or "").strip()
    if not ds:
        raise ValueError("fixture.dataset.id is required")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("fixture.cases must be a non-empty list")

    items: list[dict[str, Any]] = []
    for c in cases:
        if not isinstance(c, dict):
            continue
        q = str(c.get("question") or "").strip()
        if not q:
            continue
        ref = c.get("reference_sources") or []
        if not isinstance(ref, list) or not ref:
            raise ValueError("each case must include reference_sources[]")
        items.append(
            {
                "question": q,
                "expected_answer": c.get("expected_answer"),
                "reference_sources": ref,
                "tags": list(c.get("tags") or []),
            }
        )

    if not items:
        raise ValueError("fixture produced zero case items")

    return {"schema": "mimirq.regression_cases.v1", "dataset_id": ds, "items": items}


def ensure_fixture_tenant_owner(db: Any, *, tenant_id: UUID, account_id: str) -> None:
    """Create the explicit CI tenant membership required by authenticated APIs."""
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    if tenant is None:
        tenant = Tenant(
            id=tenant_id,
            name=f"CI Retrieval Regression {str(tenant_id)[:8]}",
            status="active",
            plan="basic",
        )
        db.add(tenant)

    member = (
        db.query(TenantMember).filter(TenantMember.tenant_id == tenant_id, TenantMember.user_id == account_id).first()
    )
    if member is None:
        member = TenantMember(
            tenant_id=tenant_id,
            user_id=account_id,
            role="owner",
            is_active=True,
            is_current=True,
        )
        db.add(member)
    else:
        member.role = "owner"
        member.is_active = True
        member.is_current = True


def _parse_fixture_config(
    fixture: dict[str, Any],
) -> tuple[UUID, str, UUID, str, str | None, list[dict[str, Any]]]:
    tenant_id = UUID(str(fixture.get("tenant_id") or "").strip())
    account_id = str(fixture.get("account_id") or "").strip() or "ci-bot"

    ds_obj = fixture.get("dataset") if isinstance(fixture.get("dataset"), dict) else {}
    dataset_id = UUID(str(ds_obj.get("id") or "").strip())
    dataset_name = str(ds_obj.get("name") or "CI Retrieval Regression Fixture").strip()
    dataset_desc = str(ds_obj.get("description") or "").strip() or None

    documents = fixture.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("fixture.documents must be a non-empty list")

    normalized_documents = [doc for doc in documents if isinstance(doc, dict)]
    return tenant_id, account_id, dataset_id, dataset_name, dataset_desc, normalized_documents


def _upsert_dataset(
    db: Any,
    *,
    dataset_id: UUID,
    tenant_id: UUID,
    dataset_name: str,
    dataset_desc: str | None,
    account_id: str,
) -> None:
    ds = db.query(Dataset).filter(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id).first()
    if ds is None:
        ds = Dataset(
            id=dataset_id,
            tenant_id=tenant_id,
            name=dataset_name,
            description=dataset_desc,
            permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            owner_id=account_id,
            dataset_metadata={},
        )
        db.add(ds)
    else:
        ds.name = dataset_name
        ds.description = dataset_desc
        ds.owner_id = account_id


def _document_total_chars(chunks: list[dict[str, Any]]) -> int:
    return sum(len(str(ch.get("content") or "")) for ch in chunks)


def _normalize_page_number(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except Exception:
        return None


def _chunk_metadata(
    *,
    dataset_id: UUID,
    filename: str,
    doc_id: UUID,
    doc_meta: dict[str, Any],
) -> dict[str, Any]:
    chunk_meta: dict[str, Any] = {
        "dataset_id": str(dataset_id),
        "source": filename,
    }
    for key in ("active_pipeline_hash", "pipeline_hash", "doc_pipeline_key"):
        if key in doc_meta and doc_meta.get(key) is not None:
            chunk_meta[key] = doc_meta.get(key)

    active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
    if active_hash:
        chunk_meta.setdefault("pipeline_hash", active_hash)
        chunk_meta.setdefault("doc_pipeline_key", f"{doc_id}:{active_hash}")
    return chunk_meta


def _replace_document_chunks(
    db: Any,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    doc_id: UUID,
    filename: str,
    doc_meta: dict[str, Any],
    chunks: list[dict[str, Any]],
) -> None:
    db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == doc_id,
    ).delete(synchronize_session=False)

    for ch in chunks:
        chunk_id = UUID(str(ch.get("id") or "").strip())
        db.add(
            DocumentChunk(
                id=chunk_id,
                tenant_id=tenant_id,
                document_id=doc_id,
                chunk_index=int(ch.get("chunk_index") or 0),
                content=str(ch.get("content") or ""),
                page_number=_normalize_page_number(ch.get("page_number")),
                doc_metadata=_chunk_metadata(
                    dataset_id=dataset_id,
                    filename=filename,
                    doc_id=doc_id,
                    doc_meta=doc_meta,
                ),
            )
        )


def _upsert_document(
    db: Any,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    doc: dict[str, Any],
) -> None:
    doc_id = UUID(str(doc.get("id") or "").strip())
    filename = str(doc.get("filename") or "").strip() or f"{doc_id}.txt"
    file_type = str(doc.get("file_type") or "md").strip().lower() or "md"
    doc_meta = doc.get("doc_metadata") if isinstance(doc.get("doc_metadata"), dict) else {}

    raw_chunks = doc.get("chunks")
    if not isinstance(raw_chunks, list) or not raw_chunks:
        raise ValueError("each document must include chunks[]")
    chunks = [chunk for chunk in raw_chunks if isinstance(chunk, dict)]

    total_chars = _document_total_chars(chunks)
    row = db.query(DBDocument).filter(DBDocument.id == doc_id, DBDocument.tenant_id == tenant_id).first()
    if row is None:
        row = DBDocument(
            id=doc_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            filename=filename,
            file_type=file_type,
            file_size=int(total_chars),
            file_path=f"ci://{filename}",
            status="completed",
            chunk_count=len(chunks),
            total_characters=int(total_chars),
            doc_metadata=dict(doc_meta),
        )
        db.add(row)
    else:
        row.dataset_id = dataset_id
        row.filename = filename
        row.file_type = file_type
        row.file_size = int(total_chars)
        row.file_path = f"ci://{filename}"
        row.status = "completed"
        row.error_message = None
        row.chunk_count = len(chunks)
        row.total_characters = int(total_chars)
        row.doc_metadata = dict(doc_meta)

    _replace_document_chunks(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        doc_id=doc_id,
        filename=filename,
        doc_meta=doc_meta,
        chunks=chunks,
    )


def seed_fixture(*, fixture: dict[str, Any]) -> None:
    tenant_id, account_id, dataset_id, dataset_name, dataset_desc, documents = _parse_fixture_config(fixture)

    # Ensure schema is up-to-date (best-effort; mirrors app startup).
    apply_runtime_migrations(engine)
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations(engine)

    db = SessionLocal()
    try:
        # Security contract: CI creates an explicit membership instead of relying
        # on the local-development owner bootstrap escape hatch.
        ensure_fixture_tenant_owner(db, tenant_id=tenant_id, account_id=account_id)
        _upsert_dataset(
            db,
            dataset_id=dataset_id,
            tenant_id=tenant_id,
            dataset_name=dataset_name,
            dataset_desc=dataset_desc,
            account_id=account_id,
        )
        for doc in documents:
            _upsert_document(db, tenant_id=tenant_id, dataset_id=dataset_id, doc=doc)

        db.commit()
    finally:
        db.close()


def main() -> int:
    p = argparse.ArgumentParser(description="Seed CI retrieval regression fixture dataset/documents/chunks.")
    p.add_argument(
        "--fixture",
        default=str(Path("ci") / "retrieval_regression_fixture.v1.json"),
        help="Fixture JSON path (default: %(default)s)",
    )
    p.add_argument(
        "--out-cases",
        default="",
        help="Write regression cases bundle (mimirq.regression_cases.v1) to this path (optional)",
    )
    args = p.parse_args()

    fixture_path = Path(args.fixture)
    fixture = _load_json(fixture_path)
    if not isinstance(fixture, dict):
        raise SystemExit(2)

    seed_fixture(fixture=fixture)

    if args.out_cases:
        bundle = build_cases_bundle(fixture)
        write_json_file(Path(args.out_cases), bundle)

    print("[seed_ci_retrieval_regression] OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
