import uuid

from app.models.dataset import DatasetPermissionEnum
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.models.document import DocumentParsedContent, DocumentPermission
from app.services.dataset_profile_scan_runner import run_dataset_profile_deep_scan
from app.services.dataset_profile_service import compute_dataset_profile_summary
from app.services.dataset_service import DatasetService


def test_dataset_profile_acl_filtering(pg_session):
    tenant_id = uuid.uuid4()
    owner_id = "owner"
    viewer_id = "viewer"

    ds = DatasetService.create_dataset(
        db=pg_session,
        tenant_id=tenant_id,
        name="ds",
        description=None,
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id=owner_id,
        partial_members=[],
    )

    # Doc A: only owner (uploader) -> viewer cannot see
    doc_a = DBDocument(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="a.txt",
        file_type="txt",
        file_size=10,
        file_path="manual://a",
        owner_id="uploader",
        access_mode="only_me",
        status="completed",
        doc_metadata={},
    )
    # Doc B: partial_members allowlist -> viewer can see
    doc_b = DBDocument(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="b.txt",
        file_type="txt",
        file_size=10,
        file_path="manual://b",
        owner_id="uploader",
        access_mode="partial_members",
        status="completed",
        doc_metadata={},
    )
    # Doc C: partial_members without allowlist -> viewer cannot see
    doc_c = DBDocument(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="c.txt",
        file_type="txt",
        file_size=10,
        file_path="manual://c",
        owner_id="uploader",
        access_mode="partial_members",
        status="completed",
        doc_metadata={},
    )
    # Doc D: inherit/default -> viewer can see
    doc_d = DBDocument(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="d.txt",
        file_type="txt",
        file_size=10,
        file_path="manual://d",
        owner_id="uploader",
        access_mode=None,
        status="completed",
        doc_metadata={},
    )

    pg_session.add_all([doc_a, doc_b, doc_c, doc_d])
    pg_session.commit()

    # Allowlist viewer for doc_b
    pg_session.add(DocumentPermission(tenant_id=tenant_id, document_id=doc_b.id, account_id=viewer_id))
    pg_session.commit()

    summary = compute_dataset_profile_summary(
        pg_session,
        tenant_id=tenant_id,
        account_id=viewer_id,
        dataset_id=ds.id,
    )
    assert summary.total_documents == 2


def test_dataset_profile_deep_scan_backfills_text_quality(pg_session):
    tenant_id = uuid.uuid4()
    owner_id = "owner"

    ds = DatasetService.create_dataset(
        db=pg_session,
        tenant_id=tenant_id,
        name="ds2",
        description=None,
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id=owner_id,
        partial_members=[],
    )

    doc = DBDocument(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        filename="x.md",
        file_type="md",
        file_size=10,
        file_path="manual://x",
        owner_id=owner_id,
        access_mode=None,
        status="completed",
        doc_metadata={},
    )
    pg_session.add(doc)
    pg_session.commit()

    pg_session.add(
        DocumentParsedContent(
            tenant_id=tenant_id,
            document_id=doc.id,
            markdown_content="Hello world\\n\\nThis is a test document.",
            original_markdown_content="Hello world\\n\\nThis is a test document.",
        )
    )
    pg_session.commit()

    run = DBDatasetProfileScanRun(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        requested_by=owner_id,
        kind="deep",
        status="pending",
        progress=0,
        config={"backfill_pdf_quality": False, "backfill_text_quality": True, "compute_file_hash": False},
        summary={},
    )
    pg_session.add(run)
    pg_session.commit()
    pg_session.refresh(run)

    result = run_dataset_profile_deep_scan(
        pg_session,
        tenant_id=tenant_id,
        account_id=owner_id,
        dataset_id=ds.id,
        scan_run_id=run.id,
    )
    assert result.get("ok") is True

    pg_session.refresh(run)
    assert run.status == "completed"
    assert int(run.progress) == 100
    assert isinstance(run.summary, dict) and run.summary

    pg_session.refresh(doc)
    assert isinstance(doc.doc_metadata, dict)
    assert "parsed_text_quality" in doc.doc_metadata
