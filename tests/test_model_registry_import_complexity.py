from uuid import UUID

from app.models import _all as model_registry
from scripts import seed_public_bench_cfever_dev as cfever_seed


def test_registered_model_modules_keep_explicit_side_effect_imports() -> None:
    module_names = {module.__name__ for module in model_registry.REGISTERED_MODEL_MODULES}

    assert "app.models.audit_log" in module_names
    assert "app.models.tenant" in module_names
    assert "app.rag.kg.models" in module_names


def test_cfever_seed_wiki_subset_dry_run_trims_required_pages(
    monkeypatch,
) -> None:
    tenant_id = UUID("11111111-1111-1111-1111-111111111111")
    dataset_id = UUID("22222222-2222-2222-2222-222222222222")

    monkeypatch.setattr(cfever_seed, "_list_wiki_files", lambda revision=None: ["wiki-000.jsonl"])

    result = cfever_seed.seed_wiki_subset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        required={
            "title-c": {3},
            "title-a": {1},
            "title-b": {2},
        },
        max_pages=2,
        overwrite=True,
        dry_run=True,
        revision="rev-1",
    )

    assert result == {
        "ok": True,
        "plan": {
            "repo_id": cfever_seed.REPO_ID,
            "repo_type": "dataset",
            "revision": "rev-1",
            "wiki_files": ["wiki-000.jsonl"],
            "required_pages": 2,
            "max_pages": 2,
            "dry_run": True,
            "overwrite": True,
        },
        "seeded": None,
    }
