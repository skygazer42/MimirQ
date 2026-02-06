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


def test_metadata_filter_contains_list_values() -> None:
    meta = {"labels": ["Apple", "Banana", "Cherry"]}

    assert match_metadata_filter(meta, {"labels": {"$contains": "ban"}})
    assert not match_metadata_filter(meta, {"labels": {"$contains": "durian"}})


def test_metadata_filter_boolean_composition_and_or_not() -> None:
    meta = {"source": "doc.pdf", "page": 12, "tags": ["a", "b"]}

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


def test_metadata_filter_startswith_endswith() -> None:
    meta = {"title": "HelloWorld", "labels": ["Apple", "Banana", "Cherry"]}

    assert match_metadata_filter(meta, {"title": {"$startswith": "hello"}})
    assert match_metadata_filter(meta, {"title": {"$endswith": "world"}})
    assert not match_metadata_filter(meta, {"title": {"$startswith": "world"}})

    assert match_metadata_filter(meta, {"labels": {"$startswith": "ban"}})
    assert match_metadata_filter(meta, {"labels": {"$endswith": "ple"}})
    assert not match_metadata_filter(meta, {"labels": {"$endswith": "durian"}})
