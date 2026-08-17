
import pytest

from scripts.apply_fusion_weights_to_dataset import _extract_weights


def test_extract_weights_prefers_fusion_wrapper_and_normalizes_in_key_order() -> None:
    payload = {
        "weights": {"vector": 1.0},
        "fusion_weights": {"Sparse": 0.25, "BM25": 0.75, "ignored": 1.0},
    }

    assert _extract_weights(payload) == {"bm25": 0.75, "sparse": 0.25}


def test_extract_weights_keeps_last_normalized_key_and_drops_zero_values() -> None:
    payload = {"Vector": 0.2, "vector": 0.8, "lexical": 0, "unused": "bad"}

    assert _extract_weights(payload) == {"vector": 1.0}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ([], "weights JSON must be an object"),
        ({"weights": {"vector": "bad"}}, "weights values must be numbers"),
        ({"weights": {"vector": 1.1}}, "weights values must be in [0,1]"),
        ({"weights": {"vector": 0, "unknown": 1}}, "weights must have at least one positive entry"),
    ],
)
def test_extract_weights_preserves_validation_errors(payload: object, message: str) -> None:
    with pytest.raises(ValueError, match=message.replace("[", r"\[").replace("]", r"\]")):
        _extract_weights(payload)
