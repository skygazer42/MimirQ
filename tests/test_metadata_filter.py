from app.rag.core.filters import match_metadata_filter


def test_metadata_filter_basic_ops() -> None:
    meta = {"source": "doc.pdf", "page": 12, "score": 0.81}

    assert match_metadata_filter(meta, {"source": "doc.pdf"})
    assert not match_metadata_filter(meta, {"source": "x.pdf"})
    assert match_metadata_filter(meta, {"page": {"$gte": 10}})
    assert not match_metadata_filter(meta, {"page": {"$lt": 10}})
    assert match_metadata_filter(meta, {"score": {"$gt": 0.8}})
    assert match_metadata_filter(meta, {"missing": {"$exists": False}})
    assert not match_metadata_filter(meta, {"missing": {"$exists": True}})


def test_metadata_filter_dot_paths_and_list_overlap() -> None:
    meta = {
        "document_user": {
            "tags": ["hr", "it"],
            "notes": "hello",
        },
        "document_frontmatter": {
            "author": "Alice",
        },
        "tags": ["a", "b"],
    }

    assert match_metadata_filter(meta, {"document_user": {"$exists": True}})
    assert match_metadata_filter(meta, {"document_user.tags": {"$in": ["it"]}})
    assert not match_metadata_filter(meta, {"document_user.tags": {"$in": ["sales"]}})
    assert match_metadata_filter(meta, {"document_frontmatter.author": {"$contains": "ali"}})

    # List-valued metadata: $in/$nin use overlap/no-overlap semantics.
    assert match_metadata_filter(meta, {"tags": {"$in": ["b"]}})
    assert match_metadata_filter(meta, {"tags": {"$nin": ["c"]}})
    assert not match_metadata_filter(meta, {"tags": {"$nin": ["a"]}})


def test_metadata_filter_falls_back_to_indexed_metadata_view() -> None:
    meta = {
        "_indexed_metadata": {
            "business_type": "demo_service",
            "district": "north-region",
            "aliases": ["就业", "创业"],
        }
    }

    assert match_metadata_filter(meta, {"business_type": "demo_service"})
    assert match_metadata_filter(meta, {"district": {"$contains": "north"}})
    assert match_metadata_filter(meta, {"aliases": {"$in": ["创业"]}})
    assert match_metadata_filter(meta, {"$and": [{"business_type": "demo_service"}, {"district": "north-region"}]})
    assert not match_metadata_filter(meta, {"missing_business_field": {"$exists": True}})
    assert match_metadata_filter(meta, {"missing_business_field": {"$exists": False}})


def test_metadata_filter_keeps_explicit_top_level_metadata_precedence() -> None:
    meta = {
        "district": "south-region",
        "_indexed_metadata": {
            "district": "north-region",
        },
    }

    assert match_metadata_filter(meta, {"district": "south-region"})
    assert not match_metadata_filter(meta, {"district": "north-region"})


def test_metadata_filter_contains_list_values() -> None:
    meta = {"labels": ["Apple", "Banana", "Cherry"]}

    assert match_metadata_filter(meta, {"labels": {"$contains": "ban"}})
    assert not match_metadata_filter(meta, {"labels": {"$contains": "durian"}})


def test_metadata_filter_boolean_composition_and_or_not() -> None:
    meta = {"source": "doc.pdf", "page": 12, "tags": ["a", "b"]}

    # No filter should match everything.
    assert match_metadata_filter(meta, {})

    assert match_metadata_filter(meta, {"$and": [{"source": "doc.pdf"}, {"page": {"$gte": 10}}]})
    assert not match_metadata_filter(meta, {"$and": [{"source": "doc.pdf"}, {"page": {"$lt": 10}}]})

    assert match_metadata_filter(meta, {"$or": [{"source": "x.pdf"}, {"page": {"$gte": 10}}]})
    assert not match_metadata_filter(meta, {"$or": [{"source": "x.pdf"}, {"page": {"$lt": 10}}]})

    assert match_metadata_filter(meta, {"$not": {"source": "x.pdf"}})
    assert not match_metadata_filter(meta, {"$not": {"source": "doc.pdf"}})

    # Composition keys can coexist with normal field predicates (AND semantics).
    assert match_metadata_filter(meta, {"source": "doc.pdf", "$or": [{"page": 1}, {"page": 12}]})
    assert not match_metadata_filter(meta, {"source": "x.pdf", "$or": [{"page": 1}, {"page": 12}]})

    # Fail closed on invalid shapes.
    assert not match_metadata_filter(meta, {"$and": []})
    assert not match_metadata_filter(meta, {"$or": []})
    assert not match_metadata_filter(meta, {"$and": {"source": "doc.pdf"}})  # type: ignore[arg-type]
    assert not match_metadata_filter(meta, {"$or": "x"})  # type: ignore[arg-type]
    assert not match_metadata_filter(meta, {"$not": []})  # type: ignore[arg-type]
    assert not match_metadata_filter(meta, [])  # type: ignore[arg-type]


def test_metadata_filter_startswith_endswith() -> None:
    meta = {"title": "HelloWorld", "labels": ["Apple", "Banana", "Cherry"]}

    assert match_metadata_filter(meta, {"title": {"$startswith": "hello"}})
    assert match_metadata_filter(meta, {"title": {"$endswith": "world"}})
    assert not match_metadata_filter(meta, {"title": {"$startswith": "world"}})

    assert match_metadata_filter(meta, {"labels": {"$startswith": "ban"}})
    assert match_metadata_filter(meta, {"labels": {"$endswith": "ple"}})
    assert not match_metadata_filter(meta, {"labels": {"$endswith": "durian"}})


def test_metadata_filter_guardrails_fail_closed() -> None:
    meta = {"source": "doc.pdf", "x": 1}

    # Depth guard: extremely deep compositions should fail closed.
    spec = {"source": "doc.pdf"}
    for _ in range(32):
        spec = {"$not": spec}
    assert not match_metadata_filter(meta, spec)

    # Size guard: extremely large lists should fail closed (even if each clause matches).
    assert not match_metadata_filter(meta, {"$and": [{"x": 1}] * 256})
