import random

import pytest


def _dynamic_programming_overlap(query_text: str, value_text: str) -> bool:
    if not query_text or not value_text:
        return False
    if value_text in query_text or query_text in value_text:
        return True
    shortest = min(len(query_text), len(value_text))
    if shortest < 4:
        return False
    previous = [0] * (len(value_text) + 1)
    best = 0
    for query_char in query_text:
        current = [0] * (len(value_text) + 1)
        for index, value_char in enumerate(value_text, start=1):
            if query_char == value_char:
                current[index] = previous[index - 1] + 1
                best = max(best, current[index])
        previous = current
    return best >= 4 and (best / shortest) >= 0.72


@pytest.mark.parametrize(
    ("query_text", "value_text", "expected"),
    [
        ("abcdefghij", "zzabcdefghxx", True),
        ("abcdefghij", "zzabcdefgxxx", False),
        ("servicepermit", "permit", True),
        ("abc", "zabc", True),
        ("abc", "zabx", False),
        ("", "anything", False),
    ],
)
def test_policy_fuzzy_overlap_semantics(
    query_text: str,
    value_text: str,
    expected: bool,
) -> None:
    from app.rag.retrieval import planner, plugin_policy

    assert planner._policy_value_fuzzy_overlaps_query(query_text, value_text) is expected
    assert plugin_policy._policy_value_fuzzy_overlaps_query(query_text, value_text) is expected


def test_policy_fuzzy_overlap_does_not_scan_both_strings_in_python() -> None:
    from app.rag.retrieval import planner, plugin_policy

    class IterationCountingText(str):
        iteration_count = 0

        def __iter__(self):  # noqa: ANN204
            type(self).iteration_count += 1
            return super().__iter__()

    query_text = IterationCountingText("abcdefghij")
    value_text = IterationCountingText("zzabcdefghxx")

    assert planner._policy_value_fuzzy_overlaps_query(query_text, value_text) is True
    assert plugin_policy._policy_value_fuzzy_overlaps_query(query_text, value_text) is True
    assert IterationCountingText.iteration_count == 0


def test_policy_fuzzy_overlap_matches_previous_algorithm() -> None:
    from app.rag.retrieval import planner

    rng = random.Random(20260723)
    alphabet = "abcdef常州市人才政策办理材料"
    for _ in range(200):
        query_text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 32)))
        value_text = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 48)))
        assert planner._policy_value_fuzzy_overlaps_query(
            query_text,
            value_text,
        ) is _dynamic_programming_overlap(query_text, value_text)
