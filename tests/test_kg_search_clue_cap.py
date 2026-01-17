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

