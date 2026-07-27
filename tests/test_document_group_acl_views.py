from collections.abc import Iterator
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.api.v1.datasets import get_dataset_ingestion_stats, list_datasets
from app.api.v1.document_duplicates import list_document_duplicates
from app.api.v1.document_folders import list_document_folders
from app.api.v1.document_listing import ListDocumentsQueryFields, list_documents
from app.api.v1.document_stats import get_document_stats
from app.core.database import Base
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document, DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember
from app.services.document_access import get_allowed_document_id_sets, list_accessible_document_ids
from app.services.document_access_service import assert_document_acl_readable


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type, _compiler, **_kwargs) -> str:  # noqa: ANN001
    return "JSON"


@pytest.fixture
def group_acl_db() -> Iterator[tuple[Session, SimpleNamespace]]:
    engine = create_engine("sqlite:///:memory:")
    tables = [
        Tenant.__table__,
        TenantMember.__table__,
        TenantGroup.__table__,
        TenantGroupMember.__table__,
        Dataset.__table__,
        DatasetPermission.__table__,
        DatasetGroupPermission.__table__,
        Document.__table__,
        DocumentPermission.__table__,
        DocumentGroupPermission.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)

    tenant_id = uuid4()
    group_id = uuid4()
    dataset_id = uuid4()
    account_id = "group-reader"
    document_ids = [uuid4(), uuid4(), uuid4()]

    db = Session(engine)
    db.add_all(
        [
            Tenant(id=tenant_id, name="tenant"),
            TenantMember(
                tenant_id=tenant_id,
                user_id=account_id,
                role="viewer",
                is_active=True,
                is_current=True,
            ),
            TenantGroup(id=group_id, tenant_id=tenant_id, name="readers"),
            TenantGroupMember(tenant_id=tenant_id, group_id=group_id, user_id=account_id),
            Dataset(
                id=dataset_id,
                tenant_id=tenant_id,
                name="Shared Base",
                permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
                owner_id="dataset-owner",
            ),
            DatasetGroupPermission(tenant_id=tenant_id, dataset_id=dataset_id, group_id=group_id),
        ]
    )
    for index, document_id in enumerate(document_ids):
        db.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                filename=f"document-{index}.pdf",
                file_type="pdf",
                file_size=100,
                file_path=f"/tmp/document-{index}.pdf",
                owner_id="document-owner",
                access_mode="partial_members",
                status="completed",
                chunk_count=2,
                total_characters=50,
                doc_metadata={
                    "file_sha256": "shared-sha",
                    "source_path": f"visible/document-{index}.pdf" if index < 2 else "hidden/secret.pdf",
                },
            )
        )
    db.add_all(
        [
            DocumentGroupPermission(
                tenant_id=tenant_id,
                document_id=document_ids[0],
                group_id=group_id,
            ),
            DocumentGroupPermission(
                tenant_id=tenant_id,
                document_id=document_ids[1],
                group_id=group_id,
            ),
        ]
    )
    db.commit()

    context = SimpleNamespace(
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        visible_document_ids=set(document_ids[:2]),
    )
    try:
        yield db, context
    finally:
        db.close()
        engine.dispose()


def test_group_only_reader_sees_same_documents_across_library_views(group_acl_db) -> None:  # noqa: ANN001
    db, ctx = group_acl_db

    listing = list_documents(
        ListDocumentsQueryFields(limit=20, lifecycle="active"),
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    stats = get_document_stats(
        dataset_id=None,
        lifecycle="active",
        file_type=None,
        owner_id=None,
        q=None,
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    folders = list_document_folders(
        dataset_id=ctx.dataset_id,
        lifecycle="active",
        max_depth=20,
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    duplicates = list_document_duplicates(
        dataset_id=ctx.dataset_id,
        min_count=2,
        max_groups=50,
        max_docs_per_group=20,
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    ingestion = get_dataset_ingestion_stats(
        ctx.dataset_id,
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )

    assert listing["total"] == 2
    assert {document.id for document in listing["items"]} == ctx.visible_document_ids
    assert stats["total"] == 2
    assert stats["total_chunks"] == 4
    assert folders.total_documents == 2
    assert folders.total_with_source_path == 2
    assert duplicates["total"] == 1
    assert duplicates["items"][0]["count"] == 2
    assert {item["id"] for item in duplicates["items"][0]["documents"]} == ctx.visible_document_ids
    assert ingestion.total_documents == 2
    assert ingestion.total_chunks == 4


def test_legacy_documents_without_dataset_fail_closed_for_inherited_access(group_acl_db) -> None:  # noqa: ANN001
    db, ctx = group_acl_db
    legacy_ids = {
        "default_other": uuid4(),
        "inherit_other": uuid4(),
        "default_owner": uuid4(),
        "all_team": uuid4(),
        "partial_member": uuid4(),
    }
    for label, document_id in legacy_ids.items():
        access_mode = {
            "inherit_other": "inherit",
            "all_team": "all_team_members",
            "partial_member": "partial_members",
        }.get(label)
        db.add(
            Document(
                id=document_id,
                tenant_id=ctx.tenant_id,
                dataset_id=None,
                filename=f"{label}.txt",
                file_type="txt",
                file_size=10,
                file_path=f"/tmp/{label}.txt",
                owner_id=ctx.account_id if label == "default_owner" else "other-owner",
                access_mode=access_mode,
                status="completed",
                chunk_count=1,
                total_characters=10,
                doc_metadata={},
            )
        )
    db.add(
        DocumentPermission(
            tenant_id=ctx.tenant_id,
            document_id=legacy_ids["partial_member"],
            account_id=ctx.account_id,
        )
    )
    db.commit()

    expected_legacy_ids = {
        legacy_ids["default_owner"],
        legacy_ids["all_team"],
        legacy_ids["partial_member"],
    }
    listing = list_documents(
        ListDocumentsQueryFields(limit=20, lifecycle="active"),
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    stats = get_document_stats(
        dataset_id=None,
        lifecycle="active",
        file_type=None,
        owner_id=None,
        q=None,
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        ctx.tenant_id,
        ctx.account_id,
        list(legacy_ids.values()),
    )
    accessible_ids = set(
        list_accessible_document_ids(
            db,
            ctx.tenant_id,
            ctx.account_id,
            status="completed",
            limit=None,
        )
    )

    assert {document.id for document in listing["items"]} & set(legacy_ids.values()) == expected_legacy_ids
    assert stats["total"] == len(ctx.visible_document_ids) + len(expected_legacy_ids)
    assert allowed_ids == expected_legacy_ids
    assert missing_ids == set()
    assert accessible_ids & set(legacy_ids.values()) == expected_legacy_ids


def test_single_document_acl_fails_closed_without_dataset(group_acl_db) -> None:  # noqa: ANN001
    db, ctx = group_acl_db
    partial_id = uuid4()
    db.add(
        DocumentPermission(
            tenant_id=ctx.tenant_id,
            document_id=partial_id,
            account_id=ctx.account_id,
        )
    )
    db.commit()

    for mode in (None, "inherit"):
        with pytest.raises(HTTPException) as exc_info:
            assert_document_acl_readable(
                db,
                tenant_id=ctx.tenant_id,
                account_id=ctx.account_id,
                document=SimpleNamespace(id=uuid4(), owner_id="other-owner", access_mode=mode),
                dataset=None,
            )
        assert exc_info.value.status_code == 403

    allowed = [
        (SimpleNamespace(id=uuid4(), owner_id=ctx.account_id, access_mode=None), None),
        (SimpleNamespace(id=uuid4(), owner_id="other-owner", access_mode="all_team_members"), None),
        (SimpleNamespace(id=partial_id, owner_id="other-owner", access_mode="partial_members"), None),
        (
            SimpleNamespace(id=uuid4(), owner_id="other-owner", access_mode="inherit"),
            SimpleNamespace(owner_id="dataset-owner"),
        ),
    ]
    for document, dataset in allowed:
        assert_document_acl_readable(
            db,
            tenant_id=ctx.tenant_id,
            account_id=ctx.account_id,
            document=document,
            dataset=dataset,
        )


def test_list_datasets_q_filters_name_and_description(group_acl_db) -> None:  # noqa: ANN001
    db, ctx = group_acl_db
    id_search_dataset_id = UUID("12345678-1234-5678-9abc-def012345678")
    db.add_all(
        [
            Dataset(
                tenant_id=ctx.tenant_id,
                name="Needle Handbook",
                description="ordinary description",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                tenant_id=ctx.tenant_id,
                name="Operations",
                description="contains second-needle marker",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                tenant_id=ctx.tenant_id,
                name="100% Knowledge",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                tenant_id=ctx.tenant_id,
                name="100X Knowledge",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                tenant_id=ctx.tenant_id,
                name="Ops_A",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                tenant_id=ctx.tenant_id,
                name="OpsXA",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                id=id_search_dataset_id,
                tenant_id=ctx.tenant_id,
                name="Identifier Search",
                description="uuid lookup candidate",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
        ]
    )
    db.commit()

    by_name = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q="needle handbook",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    by_description = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q="second-needle",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    literal_percent = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q="100%",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    literal_underscore = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q="Ops_",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    partial_hyphenated_id = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q="1234-5678-9abc",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    partial_compact_id = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q="123456781234",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )

    assert by_name["total"] == 1
    assert [item.name for item in by_name["items"]] == ["Needle Handbook"]
    assert by_description["total"] == 1
    assert [item.name for item in by_description["items"]] == ["Operations"]
    assert literal_percent["total"] == 1
    assert [item.name for item in literal_percent["items"]] == ["100% Knowledge"]
    assert literal_underscore["total"] == 1
    assert [item.name for item in literal_underscore["items"]] == ["Ops_A"]
    assert partial_hyphenated_id["total"] == 1
    assert [item.id for item in partial_hyphenated_id["items"]] == [id_search_dataset_id]
    assert partial_compact_id["total"] == 1
    assert [item.id for item in partial_compact_id["items"]] == [id_search_dataset_id]


def test_list_datasets_operational_status_facets_and_sort(group_acl_db) -> None:  # noqa: ANN001
    db, ctx = group_acl_db

    active_dataset_id = uuid4()
    anomaly_dataset_id = uuid4()
    pending_dataset_id = uuid4()
    testing_dataset_id = uuid4()
    contest_dataset_id = uuid4()

    db.add_all(
        [
            Dataset(
                id=active_dataset_id,
                tenant_id=ctx.tenant_id,
                name="Alpha Active",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                id=anomaly_dataset_id,
                tenant_id=ctx.tenant_id,
                name="Bravo Issue",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                id=pending_dataset_id,
                tenant_id=ctx.tenant_id,
                name="Charlie Pending",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                id=testing_dataset_id,
                tenant_id=ctx.tenant_id,
                name="Demo Broken",
                dataset_metadata={"operational_status": "testing"},
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
            Dataset(
                id=contest_dataset_id,
                tenant_id=ctx.tenant_id,
                name="Contest Knowledge",
                permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                owner_id="other-owner",
            ),
        ]
    )
    db.add_all(
        [
            Document(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                dataset_id=active_dataset_id,
                filename="alpha.pdf",
                file_type="pdf",
                file_size=10,
                file_path="/tmp/alpha.pdf",
                owner_id="other-owner",
                access_mode="inherit",
                status="completed",
                chunk_count=3,
                total_characters=30,
                doc_metadata={},
            ),
            Document(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                dataset_id=anomaly_dataset_id,
                filename="bravo.pdf",
                file_type="pdf",
                file_size=10,
                file_path="/tmp/bravo.pdf",
                owner_id="other-owner",
                access_mode="inherit",
                status="failed",
                chunk_count=1,
                total_characters=10,
                doc_metadata={},
            ),
            Document(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                dataset_id=pending_dataset_id,
                filename="charlie.pdf",
                file_type="pdf",
                file_size=10,
                file_path="/tmp/charlie.pdf",
                owner_id="other-owner",
                access_mode="inherit",
                status="processing",
                chunk_count=2,
                total_characters=20,
                doc_metadata={},
            ),
            Document(
                id=uuid4(),
                tenant_id=ctx.tenant_id,
                dataset_id=testing_dataset_id,
                filename="demo.pdf",
                file_type="pdf",
                file_size=10,
                file_path="/tmp/demo.pdf",
                owner_id="other-owner",
                access_mode="inherit",
                status="failed",
                chunk_count=4,
                total_characters=40,
                doc_metadata={},
            ),
        ]
    )
    db.commit()

    page = list_datasets(
        skip=0,
        limit=2,
        category_id=None,
        include_descendants=True,
        q=None,
        order_by="name",
        order_dir="asc",
        operational_status="all",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    pending_only = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q=None,
        order_by="name",
        order_dir="asc",
        operational_status="pending",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )
    testing_only = list_datasets(
        skip=0,
        limit=20,
        category_id=None,
        include_descendants=True,
        q=None,
        order_by="name",
        order_dir="asc",
        operational_status="testing",
        tenant_id=ctx.tenant_id,
        account_id=ctx.account_id,
        db=db,
    )

    assert page["total"] == 6
    assert [item.name for item in page["items"]] == ["Alpha Active", "Bravo Issue"]
    assert page["facets"].scope_total == 6
    assert page["facets"].filtered_total == 6
    assert page["facets"].status_counts == {
        "active": 3,
        "anomaly": 1,
        "pending": 1,
        "testing": 1,
    }

    alpha = next(item for item in page["items"] if item.name == "Alpha Active")
    bravo = next(item for item in page["items"] if item.name == "Bravo Issue")
    assert alpha.operational_status == "active"
    assert alpha.ingestion_summary.total_documents == 1
    assert alpha.ingestion_summary.total_chunks == 3
    assert bravo.operational_status == "anomaly"
    assert bravo.ingestion_summary.by_status == {"failed": 1}

    assert pending_only["total"] == 1
    assert [item.name for item in pending_only["items"]] == ["Charlie Pending"]
    assert pending_only["items"][0].operational_status == "pending"
    assert pending_only["facets"].status_counts["pending"] == 1

    assert testing_only["total"] == 1
    assert [item.name for item in testing_only["items"]] == ["Demo Broken"]
    assert testing_only["items"][0].operational_status == "testing"


def test_list_datasets_filtered_total_count_avoids_document_stats_join(group_acl_db) -> None:  # noqa: ANN001
    db, ctx = group_acl_db
    dataset_id = uuid4()
    db.add(
        Dataset(
            id=dataset_id,
            tenant_id=ctx.tenant_id,
            name="Contest Knowledge",
            permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
            owner_id="other-owner",
        )
    )
    db.add(
        Document(
            id=uuid4(),
            tenant_id=ctx.tenant_id,
            dataset_id=dataset_id,
            filename="contest.pdf",
            file_type="pdf",
            file_size=10,
            file_path="/tmp/contest.pdf",
            owner_id="other-owner",
            access_mode="inherit",
            status="completed",
            chunk_count=3,
            total_characters=30,
            doc_metadata={},
        )
    )
    db.commit()

    statements: list[str] = []

    def _capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:  # noqa: ANN001
        statements.append(statement)

    event.listen(db.bind, "before_cursor_execute", _capture_sql)
    try:
        result = list_datasets(
            skip=0,
            limit=1,
            category_id=None,
            include_descendants=True,
            q="Contest",
            order_by="name",
            order_dir="asc",
            operational_status="all",
            tenant_id=ctx.tenant_id,
            account_id=ctx.account_id,
            db=db,
        )
    finally:
        event.remove(db.bind, "before_cursor_execute", _capture_sql)

    dataset_count_sql = [
        statement.lower()
        for statement in statements
        if "count(" in statement.lower() and "datasets" in statement.lower() and "group by" not in statement.lower()
    ]

    assert result["total"] == 1
    assert [item.name for item in result["items"]] == ["Contest Knowledge"]
    assert result["facets"].filtered_total == 1
    assert len(dataset_count_sql) == 2
    assert all("documents" not in statement for statement in dataset_count_sql)
    assert all("join" not in statement for statement in dataset_count_sql)
