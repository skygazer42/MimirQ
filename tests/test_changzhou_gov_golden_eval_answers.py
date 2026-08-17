
import json

import pytest

from scripts.changzhou_gov_golden_eval import load_answer_map


def _write_json(tmp_path, name: str, payload) -> str:
    path = tmp_path / name
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_load_answer_map_accepts_wrapped_and_plain_lists_with_last_duplicate_wins(
    tmp_path,
) -> None:
    answers = [
        {"id": " case-1 ", "answer": "first"},
        "invalid",
        {"case_id": "case-1", "answer": "last"},
        {"id": "", "answer": "ignored"},
    ]

    wrapped = load_answer_map(_write_json(tmp_path, "wrapped.json", {"answers": answers}))
    plain = load_answer_map(_write_json(tmp_path, "plain.json", answers))

    assert wrapped == plain == {"case-1": {"case_id": "case-1", "answer": "last"}}


def test_load_answer_map_accepts_mapping_values_and_normalizes_scalars(tmp_path) -> None:
    result = load_answer_map(
        _write_json(
            tmp_path,
            "mapping.json",
            {" case-1 ": " answer ", "case-2": {"answer": "two"}, "": "ignored"},
        )
    )

    assert result == {
        "case-1": {"answer": "answer"},
        "case-2": {"answer": "two"},
    }


def test_load_answer_map_empty_path_returns_empty_without_file_access() -> None:
    assert load_answer_map("  ") == {}


def test_load_answer_map_rejects_non_collection_payload(tmp_path) -> None:
    with pytest.raises(
        ValueError,
        match=r"answers file must be an object, an object with answers\[\], or an answers\[\] list",
    ):
        load_answer_map(_write_json(tmp_path, "scalar.json", "answer"))
