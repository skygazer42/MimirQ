
from typing import Any


def run_kg_route(sample: dict[str, Any]) -> dict[str, Any]:
    del sample
    raise RuntimeError(
        "Stage1 KG evaluation requires an actual KG runner; "
        "gold labels must never be used as system output"
    )
