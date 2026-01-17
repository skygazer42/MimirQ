from __future__ import annotations

import pytest


def test_tracker_enforces_max_clues(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_MAX_CLUES", 2, raising=False)

    from app.rag.kg.search.tracker import Tracker

    tracker = Tracker()
    for i in range(5):
        tracker.add_clue(
            stage="s",
            from_node={"id": f"f{i}"},
            to_node={"id": f"t{i}"},
            confidence=0.1,
            relation="r",
            metadata={},
        )

    assert len(tracker.get_clues()) == 2
    assert tracker.clues_dropped == 3


def test_tracker_extend_clues_respects_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_MAX_CLUES", 3, raising=False)

    from app.rag.kg.search.tracker import Tracker

    tracker = Tracker()
    tracker.extend_clues(
        [
            {
                "id": "1",
                "stage": "s",
                "from": {"id": "a"},
                "to": {"id": "b"},
                "confidence": 0.0,
                "relation": "",
                "metadata": {},
            }
            for _ in range(5)
        ]
    )

    assert len(tracker.get_clues()) == 3
    assert tracker.clues_dropped == 2


def test_tracker_clues_disabled_does_not_collect(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_CLUES_ENABLED", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_MAX_CLUES", 2, raising=False)

    from app.rag.kg.search.tracker import Tracker

    tracker = Tracker()
    tracker.add_clue(stage="s", from_node={"id": "a"}, to_node={"id": "b"})
    tracker.extend_clues([{"id": "1"}])

    assert tracker.get_clues() == []
    assert tracker.clues_dropped == 0


def test_tracker_truncates_node_text(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_NODE_TEXT_MAX_CHARS", 3, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.tracker import Tracker

    cfg = SearchConfig(query="abcdef")
    qn = Tracker.build_query_node(cfg)
    assert qn["content"] == "abc"

    en = Tracker.build_entity_node({"entity_id": "e", "name": "abcdef", "description": "uvwxyz"})
    assert en["content"] == "abc"
    assert en["description"] == "uvw"
