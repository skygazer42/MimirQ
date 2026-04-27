from __future__ import annotations

from langchain_core.documents import Document

from app.rag.chunking.strategies.parent_child import ParentChildChunker


def test_parent_child_chunker_parent_ids_are_deterministic() -> None:
    chunker = ParentChildChunker(chunk_size=120, chunk_overlap=20, child_ratio=0.5, min_child_size=60)

    # Ensure we produce multiple parent chunks.
    content = "\n\n".join(
        [
            "Section 1: " + ("A" * 140),
            "Section 2: " + ("B" * 140),
            "Section 3: " + ("C" * 140),
        ]
    )

    out1 = chunker.split_documents([Document(page_content=content, metadata={"source": "t"})])
    out2 = chunker.split_documents([Document(page_content=content, metadata={"source": "t"})])

    parents1 = [d for d in out1 if (d.metadata or {}).get("chunk_role") == "parent"]
    parents2 = [d for d in out2 if (d.metadata or {}).get("chunk_role") == "parent"]
    assert len(parents1) >= 2
    assert len(parents2) == len(parents1)

    parent_ids1 = [str((d.metadata or {}).get("parent_id") or "") for d in parents1]
    parent_ids2 = [str((d.metadata or {}).get("parent_id") or "") for d in parents2]

    assert all(pid for pid in parent_ids1)
    assert parent_ids1 == parent_ids2

    # Family keys are deterministic and shared between a parent and its children.
    family_by_parent: dict[str, str] = {}
    for d in out1:
        meta = d.metadata or {}
        parent_id = str(meta.get("parent_id") or "")
        family_key = str(meta.get("hierarchy_family_key") or "")
        assert family_key
        if str(meta.get("chunk_role") or "") == "parent":
            family_by_parent[parent_id] = family_key
            assert str(meta.get("hierarchy_node_key") or "") == parent_id
            assert meta.get("hierarchy_parent_key") is None

    assert family_by_parent
    for d in out1:
        meta = d.metadata or {}
        if str(meta.get("chunk_role") or "") != "child":
            continue
        parent_id = str(meta.get("parent_id") or "")
        assert str(meta.get("hierarchy_parent_key") or "") == parent_id
        assert str(meta.get("hierarchy_family_key") or "") == family_by_parent[parent_id]


def test_parent_child_chunker_emits_stable_hierarchy_family_keys() -> None:
    chunker = ParentChildChunker(chunk_size=180, chunk_overlap=20, child_ratio=0.4, min_child_size=60)

    content = "\n\n".join(
        [
            "Section 1: " + ("Alpha " * 60),
            "Section 2: " + ("Beta " * 60),
        ]
    )

    out1 = chunker.split_documents([Document(page_content=content, metadata={"source": "t"})])
    out2 = chunker.split_documents([Document(page_content=content, metadata={"source": "t"})])

    parents1 = [d for d in out1 if (d.metadata or {}).get("chunk_role") == "parent"]
    parents2 = [d for d in out2 if (d.metadata or {}).get("chunk_role") == "parent"]
    children1 = [d for d in out1 if (d.metadata or {}).get("chunk_role") == "child"]
    children2 = [d for d in out2 if (d.metadata or {}).get("chunk_role") == "child"]

    assert parents1
    assert children1
    assert len(parents1) == len(parents2)
    assert len(children1) == len(children2)

    parent_keys1 = [str((d.metadata or {}).get("hierarchy_node_key") or "") for d in parents1]
    parent_keys2 = [str((d.metadata or {}).get("hierarchy_node_key") or "") for d in parents2]
    assert parent_keys1 == parent_keys2
    assert parent_keys1 == [str((d.metadata or {}).get("parent_id") or "") for d in parents1]

    for parent in parents1:
        meta = parent.metadata or {}
        assert meta.get("hierarchy_basis") == "parent_child"
        assert meta.get("hierarchy_level") == "parent"
        assert meta.get("hierarchy_family_key") == meta.get("hierarchy_node_key")

    child_keys1 = [str((d.metadata or {}).get("hierarchy_node_key") or "") for d in children1]
    child_keys2 = [str((d.metadata or {}).get("hierarchy_node_key") or "") for d in children2]
    assert child_keys1 == child_keys2
    assert all(key for key in child_keys1)

    for child in children1:
        meta = child.metadata or {}
        parent_id = str(meta.get("parent_id") or "")
        assert meta.get("hierarchy_basis") == "parent_child"
        assert meta.get("hierarchy_level") == "child"
        assert meta.get("hierarchy_parent_key") == parent_id
        assert meta.get("hierarchy_family_key") == parent_id


def test_parent_child_chunker_reuses_cached_hierarchy_for_identical_inputs(monkeypatch) -> None:  # noqa: ANN001
    chunker = ParentChildChunker(chunk_size=120, chunk_overlap=20, child_ratio=0.5, min_child_size=60)

    content = "\n\n".join(
        [
            "Section 1: " + ("A" * 140),
            "Section 2: " + ("B" * 140),
        ]
    )
    docs = [Document(page_content=content, metadata={"source": "t"})]

    parent_calls = {"n": 0}
    child_calls = {"n": 0}
    original_parent = chunker.parent_splitter.split_text
    original_child = chunker.child_splitter.split_text

    def _parent(text):  # noqa: ANN001
        parent_calls["n"] += 1
        return original_parent(text)

    def _child(text):  # noqa: ANN001
        child_calls["n"] += 1
        return original_child(text)

    monkeypatch.setattr(chunker.parent_splitter, "split_text", _parent, raising=True)
    monkeypatch.setattr(chunker.child_splitter, "split_text", _child, raising=True)

    out1 = chunker.split_documents(docs)
    out2 = chunker.split_documents(docs)

    assert out1
    assert out2
    assert parent_calls["n"] == 1
    assert child_calls["n"] >= 1
    assert child_calls["n"] == len([d for d in out1 if (d.metadata or {}).get("chunk_role") == "parent"])
