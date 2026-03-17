from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

HIERARCHY_RECALL_KNOBS = {
    "enable_hierarchy_recall": True,
    "hierarchy_family_collapse": True,
    "hierarchy_family_aggregation": "combined",
    "hierarchy_tree_dedup": False,
    "hierarchy_parent_depth": 2,
    "hierarchy_sibling_window": 3,
    "hierarchy_overfetch_factor": 4,
}

HIERARCHY_RECALL_FIELDS = tuple(HIERARCHY_RECALL_KNOBS.keys())


def test_chat_rag_config_accepts_hierarchy_recall_knobs() -> None:
    from app.api.schemas.chat import ChatRAGConfig

    cfg = ChatRAGConfig(**HIERARCHY_RECALL_KNOBS)

    dumped = cfg.model_dump(exclude_none=True)
    assert dumped["enable_hierarchy_recall"] is True
    assert dumped["hierarchy_family_collapse"] is True
    assert dumped["hierarchy_family_aggregation"] == "combined"
    assert dumped["hierarchy_tree_dedup"] is False
    assert dumped["hierarchy_parent_depth"] == 2
    assert dumped["hierarchy_sibling_window"] == 3
    assert dumped["hierarchy_overfetch_factor"] == 4


def test_dataset_rag_defaults_accepts_hierarchy_recall_knobs() -> None:
    from app.api.schemas.dataset import DatasetRAGDefaults

    defaults = DatasetRAGDefaults(**HIERARCHY_RECALL_KNOBS)

    dumped = defaults.model_dump(exclude_none=True)
    assert dumped["enable_hierarchy_recall"] is True
    assert dumped["hierarchy_family_collapse"] is True
    assert dumped["hierarchy_family_aggregation"] == "combined"
    assert dumped["hierarchy_tree_dedup"] is False
    assert dumped["hierarchy_parent_depth"] == 2
    assert dumped["hierarchy_sibling_window"] == 3
    assert dumped["hierarchy_overfetch_factor"] == 4


def test_regression_run_request_accepts_hierarchy_recall_knobs() -> None:
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    req = RagasRegressionRunCreateRequest(dataset_id=uuid4(), **HIERARCHY_RECALL_KNOBS)

    dumped = req.model_dump(exclude_none=True)
    assert dumped["enable_hierarchy_recall"] is True
    assert dumped["hierarchy_family_collapse"] is True
    assert dumped["hierarchy_family_aggregation"] == "combined"
    assert dumped["hierarchy_tree_dedup"] is False
    assert dumped["hierarchy_parent_depth"] == 2
    assert dumped["hierarchy_sibling_window"] == 3
    assert dumped["hierarchy_overfetch_factor"] == 4


def test_hierarchy_recall_knobs_default_to_none_across_runtime_schemas() -> None:
    from app.api.schemas.chat import ChatRAGConfig
    from app.api.schemas.dataset import DatasetRAGDefaults
    from app.api.schemas.regression import RagasRegressionRunCreateRequest

    instances = (
        ChatRAGConfig(),
        DatasetRAGDefaults(),
        RagasRegressionRunCreateRequest(dataset_id=uuid4()),
    )

    for instance in instances:
        for field_name in HIERARCHY_RECALL_FIELDS:
            assert getattr(instance, field_name) is None


@pytest.mark.parametrize(
    ("schema_name", "builder"),
    [
        ("chat", lambda **kwargs: __import__("app.api.schemas.chat", fromlist=["ChatRAGConfig"]).ChatRAGConfig(**kwargs)),
        ("dataset", lambda **kwargs: __import__("app.api.schemas.dataset", fromlist=["DatasetRAGDefaults"]).DatasetRAGDefaults(**kwargs)),
        (
            "regression",
            lambda **kwargs: __import__(
                "app.api.schemas.regression",
                fromlist=["RagasRegressionRunCreateRequest"],
            ).RagasRegressionRunCreateRequest(dataset_id=uuid4(), **kwargs),
        ),
    ],
)
def test_hierarchy_family_aggregation_rejects_invalid_values(schema_name: str, builder) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError) as exc_info:
        builder(hierarchy_family_aggregation="votes")

    message = str(exc_info.value)
    assert "hierarchy_family_aggregation" in message, schema_name
    assert "frequency" in message
    assert "score" in message
    assert "combined" in message


@pytest.mark.parametrize(
    ("schema_name", "builder"),
    [
        ("chat", lambda **kwargs: __import__("app.api.schemas.chat", fromlist=["ChatRAGConfig"]).ChatRAGConfig(**kwargs)),
        ("dataset", lambda **kwargs: __import__("app.api.schemas.dataset", fromlist=["DatasetRAGDefaults"]).DatasetRAGDefaults(**kwargs)),
        (
            "regression",
            lambda **kwargs: __import__(
                "app.api.schemas.regression",
                fromlist=["RagasRegressionRunCreateRequest"],
            ).RagasRegressionRunCreateRequest(dataset_id=uuid4(), **kwargs),
        ),
    ],
)
@pytest.mark.parametrize("value", [0, False])
def test_hierarchy_family_aggregation_rejects_falsey_non_string_values(
    schema_name: str,
    builder,
    value: object,
) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError) as exc_info:
        builder(hierarchy_family_aggregation=value)

    message = str(exc_info.value)
    assert "hierarchy_family_aggregation" in message, schema_name
    assert "frequency" in message
    assert "score" in message
    assert "combined" in message


@pytest.mark.parametrize(
    ("schema_name", "builder"),
    [
        ("chat", lambda **kwargs: __import__("app.api.schemas.chat", fromlist=["ChatRAGConfig"]).ChatRAGConfig(**kwargs)),
        ("dataset", lambda **kwargs: __import__("app.api.schemas.dataset", fromlist=["DatasetRAGDefaults"]).DatasetRAGDefaults(**kwargs)),
        (
            "regression",
            lambda **kwargs: __import__(
                "app.api.schemas.regression",
                fromlist=["RagasRegressionRunCreateRequest"],
            ).RagasRegressionRunCreateRequest(dataset_id=uuid4(), **kwargs),
        ),
    ],
)
@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("hierarchy_parent_depth", -1),
        ("hierarchy_parent_depth", 999),
        ("hierarchy_sibling_window", -1),
        ("hierarchy_sibling_window", 999),
        ("hierarchy_overfetch_factor", 0),
        ("hierarchy_overfetch_factor", 999),
    ],
)
def test_hierarchy_numeric_knobs_reject_out_of_range_values(schema_name: str, builder, field_name: str, value: int) -> None:  # noqa: ANN001
    with pytest.raises(ValidationError) as exc_info:
        builder(**{field_name: value})

    assert field_name in str(exc_info.value), schema_name
