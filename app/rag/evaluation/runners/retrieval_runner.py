
from typing import Any


def run_retrieval_route(sample: dict[str, Any]) -> dict[str, Any]:
    del sample
    raise RuntimeError(
        "Stage1 retrieval evaluation requires an actual retrieval runner; "
        "gold labels must never be used as system output"
    )
