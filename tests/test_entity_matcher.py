from __future__ import annotations


def test_find_entity_matches_prefers_longest_surface_and_removes_overlap() -> None:
    from app.rag.utils.entity_matcher import extract_partition_keys, find_entity_matches

    text = "Compare ACME Holdings with ACME on the renewal plan."
    matches = find_entity_matches(text, ["ACME", "ACME Holdings"])

    assert [m.entity_key for m in matches] == ["ACME Holdings", "ACME"]
    assert matches[0].matched_text == "ACME Holdings"
    assert matches[1].matched_text == "ACME"
    assert extract_partition_keys(text, ["ACME", "ACME Holdings"]) == ["ACME Holdings", "ACME"]


def test_find_entity_matches_enforces_ascii_token_boundaries() -> None:
    from app.rag.utils.entity_matcher import find_entity_matches

    text = "CRMACME should not match, but ACME should match once."
    matches = find_entity_matches(text, ["ACME"])

    assert len(matches) == 1
    assert matches[0].matched_text == "ACME"


def test_find_entity_matches_handles_cjk_surfaces_and_standalone_tail_match() -> None:
    from app.rag.utils.entity_matcher import extract_partition_keys, find_entity_matches

    text = "请比较招商银行与招商在零售业务上的差异。"
    matches = find_entity_matches(text, ["招商", "招商银行"])

    assert [m.entity_key for m in matches] == ["招商银行", "招商"]
    assert extract_partition_keys(text, ["招商", "招商银行"]) == ["招商银行", "招商"]
