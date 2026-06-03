from pathlib import Path


def test_document_acl_filters_pass_selects_to_in_clauses() -> None:
    for path in (
        Path("app/api/v1/document_listing.py"),
        Path("app/api/v1/document_stats.py"),
    ):
        source = path.read_text(encoding="utf-8")
        assert "partial_member_subq = select(DatasetPermission.dataset_id).where(" in source
        assert "allowed_dataset_ids_subq = select(Dataset.id).where(" in source
        assert "partial_member_subq = (\n            db.query(DatasetPermission.dataset_id)" not in source
        assert "allowed_dataset_ids_subq = (\n            db.query(Dataset.id)" not in source
