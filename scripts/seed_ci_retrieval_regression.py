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


def seed_fixture(*, fixture: dict[str, Any]) -> None:
    tenant_id = UUID(str(fixture.get("tenant_id") or "").strip())
    account_id = str(fixture.get("account_id") or "").strip() or "ci-bot"

    ds_obj = fixture.get("dataset") if isinstance(fixture.get("dataset"), dict) else {}
    dataset_id = UUID(str(ds_obj.get("id") or "").strip())
    dataset_name = str(ds_obj.get("name") or "CI Retrieval Regression Fixture").strip()
    dataset_desc = str(ds_obj.get("description") or "").strip() or None

    documents = fixture.get("documents")
    if not isinstance(documents, list) or not documents:
        raise ValueError("fixture.documents must be a non-empty list")

    # Ensure schema is up-to-date (best-effort; mirrors app startup).
    apply_runtime_migrations(engine)
    Base.metadata.create_all(bind=engine)
    apply_runtime_migrations(engine)

    db = SessionLocal()
    try:
        # Upsert dataset by id.
        ds = (
            db.query(Dataset)
            .filter(Dataset.id == dataset_id, Dataset.tenant_id == tenant_id)
            .first()
        )
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
        db.commit()

        # Upsert documents + replace chunks for determinism.
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            doc_id = UUID(str(doc.get("id") or "").strip())
            filename = str(doc.get("filename") or "").strip() or f"{doc_id}.txt"
            file_type = str(doc.get("file_type") or "md").strip().lower() or "md"
            doc_meta = doc.get("doc_metadata") if isinstance(doc.get("doc_metadata"), dict) else {}

            chunks = doc.get("chunks")
            if not isinstance(chunks, list) or not chunks:
                raise ValueError("each document must include chunks[]")
            total_chars = 0
            for ch in chunks:
                if isinstance(ch, dict):
                    total_chars += len(str(ch.get("content") or ""))

            row = (
                db.query(DBDocument)
                .filter(DBDocument.id == doc_id, DBDocument.tenant_id == tenant_id)
                .first()
            )
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

            # Replace chunks for this document (idempotent across reruns).
            db.query(DocumentChunk).filter(
                DocumentChunk.tenant_id == tenant_id,
                DocumentChunk.document_id == doc_id,
            ).delete(synchronize_session=False)

            for ch in chunks:
                if not isinstance(ch, dict):
                    continue
                chunk_id = UUID(str(ch.get("id") or "").strip())
                chunk_index = int(ch.get("chunk_index") or 0)
                content = str(ch.get("content") or "")
                page_number = ch.get("page_number")
                try:
                    page_number = int(page_number) if page_number is not None else None
                except Exception:
                    page_number = None

                # Chunk metadata: include dataset_id so BM25 filtering works when dataset-scoped.
                chunk_meta: dict[str, Any] = {
                    "dataset_id": str(dataset_id),
                    "source": filename,
                }
                # Carry selected doc-level audit fields down for convenience (best-effort).
                for k in ("active_pipeline_hash", "pipeline_hash", "doc_pipeline_key"):
                    if k in doc_meta and doc_meta.get(k) is not None:
                        chunk_meta[k] = doc_meta.get(k)
                # Active-pipeline trimming expects chunks to carry either:
                # - doc_pipeline_key = f"{document_id}:{pipeline_hash}", OR
                # - pipeline_hash (so the key can be reconstructed).
                #
                # CI fixtures store the active pipeline under `active_pipeline_hash` at doc-level,
                # so mirror it into the chunk-level fields used by retrieval trimming.
                active_hash = str(doc_meta.get("active_pipeline_hash") or doc_meta.get("pipeline_hash") or "").strip()
                if active_hash:
                    chunk_meta.setdefault("pipeline_hash", active_hash)
                    chunk_meta.setdefault("doc_pipeline_key", f"{doc_id}:{active_hash}")

                db.add(
                    DocumentChunk(
                        id=chunk_id,
                        tenant_id=tenant_id,
                        document_id=doc_id,
                        chunk_index=chunk_index,
                        content=content,
                        page_number=page_number,
                        doc_metadata=chunk_meta,
                    )
                )

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
