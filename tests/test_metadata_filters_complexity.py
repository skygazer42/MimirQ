from app.rag.core.filters import (
    INDEXED_METADATA_KEY,
    apply_metadata_filter_with_stats,
    match_metadata_filter,
    summarize_metadata_filter,
)


def test_match_metadata_filter_preserves_boolean_and_operator_contracts() -> None:
    metadata = {
        "category": "Contract",
        "page": 12,
        "tags": ["Legal", "Priority"],
        "title": "Quarterly Report.pdf",
        "optional": None,
    }
    filter_spec = {
        "$and": [
            {"category": {"$eq": "Contract", "$ne": "FAQ"}},
            {"page": {"$gt": 10, "$gte": 12, "$lt": 20, "$lte": 12}},
            {"tags": {"$in": ["Priority"], "$nin": ["Blocked"]}},
            {"title": {"$contains": "report", "$startswith": "quarter", "$endswith": ".PDF"}},
            {"optional": {"$exists": False}},
            {"$or": [{"page": 1}, {"page": 12}]},
            {"$not": {"category": "FAQ"}},
        ]
    }

    assert match_metadata_filter(metadata, filter_spec)
    assert not match_metadata_filter(metadata, {"$or": [{"page": 1}, {"page": 2}]})
    assert not match_metadata_filter(metadata, {"$not": {"page": 12}})
    assert not match_metadata_filter(metadata, {"page": {"$unknown": 12}})
    assert not match_metadata_filter(metadata, {"$unknown": []})


def test_match_metadata_filter_preserves_indexed_fallback_and_missing_compatibility() -> None:
    metadata = {
        "topic": "explicit",
        INDEXED_METADATA_KEY: {"topic": "indexed", "nested": {"region": "APAC"}},
    }

    assert match_metadata_filter(metadata, {"topic": "explicit"})
    assert not match_metadata_filter(metadata, {"topic": "indexed"})
    assert match_metadata_filter(metadata, {"nested.region": "APAC"})
    assert match_metadata_filter(metadata, {"missing": {"$in": ["", "legacy"]}})
    assert not match_metadata_filter(metadata, {"missing": {"$in": ["legacy"]}})
    assert not match_metadata_filter(metadata, {"_indexed_metadata.missing": {"$exists": True}})


def test_match_metadata_filter_preserves_empty_invalid_and_bounded_shapes() -> None:
    assert match_metadata_filter({}, None)
    assert match_metadata_filter({}, {})
    assert not match_metadata_filter([], {})
    assert not match_metadata_filter({}, ["invalid"])
    assert not match_metadata_filter({}, {1: "invalid-key"})
    assert not match_metadata_filter({}, {"$and": []})
    assert not match_metadata_filter({}, {"$or": ["invalid"]})
    assert not match_metadata_filter({}, {"$not": {}})

    nested: dict[str, object] = {"value": 1}
    for _ in range(10):
        nested = {"$not": nested}
    assert not match_metadata_filter({"value": 1}, nested)


def test_summarize_and_apply_metadata_filter_preserve_pii_safe_stats() -> None:
    filter_spec = {
        "$and": [
            {"department": {"$in": ["secret-value"]}},
            {"nested.region": {"$eq": "APAC"}},
            {"$not": {"status": {"$eq": "archived"}}},
        ]
    }
    summary = summarize_metadata_filter(filter_spec, max_keys_sample=2)

    assert summary == {
        "keys_count": 3,
        "keys_sample": ["department", "nested.region"],
        "ops": {"$and": 1, "$eq": 2, "$in": 1, "$not": 1},
    }
    assert "secret-value" not in repr(summary)

    items = [
        {"id": "match", "metadata": {"department": "secret-value", "nested": {"region": "APAC"}}},
        {"id": "blocked", "metadata": {"department": "other", "nested": {"region": "APAC"}}},
        {"id": "invalid-meta", "metadata": None},
    ]
    matched, stats = apply_metadata_filter_with_stats(items, filter_spec)
    assert matched == [items[0]]
    assert stats == {
        "enabled": True,
        "matched": 1,
        "blocked": 2,
        "summary": {
            "keys_count": 3,
            "keys_sample": ["department", "nested.region", "status"],
            "ops": summary["ops"],
        },
    }


def test_boolean_depth_budget_counts_each_nested_spec_once() -> None:
    nested: dict[str, object] = {"deep": "value"}
    for _ in range(8):
        nested = {"$and": [nested]}

    assert match_metadata_filter({"deep": "value"}, nested)
    assert summarize_metadata_filter(nested) == {
        "keys_count": 1,
        "keys_sample": ["deep"],
        "ops": {"$and": 8},
    }
