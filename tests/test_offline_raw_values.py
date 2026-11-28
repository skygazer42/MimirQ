from uuid import uuid4

import httpx
import pytest

from scripts import seed_ci_kg_search_regression as seed
from scripts import smoke_test


@pytest.mark.parametrize("operation", ["dataset", "upload"])
def test_smoke_helper_exposes_a_missing_required_response_id(operation: str) -> None:
    transport = httpx.MockTransport(lambda _request: httpx.Response(201, json={"id": None}))
    with httpx.Client(transport=transport) as client:
        with pytest.raises(smoke_test.CallError):
            if operation == "dataset":
                smoke_test._ensure_dataset(
                    client, api_base="https://example.invalid/api/v1", headers={}, dataset_id_arg=None
                )
            else:
                smoke_test._upload_smoke_document(
                    client,
                    api_base="https://example.invalid/api/v1",
                    headers={},
                    dataset_id="dataset-1",
                    parser_backend="basic",
                    core_only=True,
                )


class _Rows:
    def __init__(self) -> None:
        self.added = []

    def add(self, row) -> None:
        self.added.append(row)


def test_kg_fixture_preserves_zero_weight_and_zero_confidence() -> None:
    seed._ensure_app_imports()
    rows = _Rows()
    seed._add_event_links(
        db=rows,
        event_entities=[{"id": str(uuid4()), "event_id": str(uuid4()), "entity_id": str(uuid4()), "weight": 0.0}],
    )
    seed._add_relations(
        db=rows,
        tenant_id=uuid4(),
        relations=[
            {
                "id": str(uuid4()),
                "subject_entity_id": str(uuid4()),
                "object_entity_id": str(uuid4()),
                "predicate": "related_to",
                "confidence": 0.0,
            }
        ],
    )

    assert rows.added[0].weight == 0.0
    assert rows.added[1].confidence == 0.0
