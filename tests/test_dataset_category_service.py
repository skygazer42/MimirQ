from __future__ import annotations

import uuid


def test_would_create_cycle() -> None:
    from app.services.dataset_category_service import would_create_cycle

    a = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
    b = uuid.UUID("00000000-0000-0000-0000-0000000000b2")
    c = uuid.UUID("00000000-0000-0000-0000-0000000000c3")

    # a <- b <- c
    parent_by_id = {a: None, b: a, c: b}

    assert would_create_cycle(category_id=a, new_parent_id=c, parent_by_id=parent_by_id) is True
    assert would_create_cycle(category_id=b, new_parent_id=c, parent_by_id=parent_by_id) is True
    assert would_create_cycle(category_id=c, new_parent_id=a, parent_by_id=parent_by_id) is False
    assert would_create_cycle(category_id=b, new_parent_id=b, parent_by_id=parent_by_id) is True


def test_build_category_tree_nodes_sorts_siblings() -> None:
    from app.services.dataset_category_service import build_category_tree_nodes

    root1 = uuid.uuid4()
    root2 = uuid.uuid4()
    child_a = uuid.uuid4()
    child_b = uuid.uuid4()

    nodes = build_category_tree_nodes(
        [
            {"id": root1, "name": "B", "parent_id": None, "sort_order": 10},
            {"id": root2, "name": "A", "parent_id": None, "sort_order": 20},
            {"id": child_a, "name": "child-2", "parent_id": root1, "sort_order": 2},
            {"id": child_b, "name": "child-1", "parent_id": root1, "sort_order": 1},
        ]
    )

    assert [n.name for n in nodes] == ["B", "A"]  # top-level sorted by sort_order then name
    assert [c.name for c in nodes[0].children] == ["child-1", "child-2"]
