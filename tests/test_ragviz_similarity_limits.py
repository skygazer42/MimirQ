import datetime as _datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
import starlette.status as _status
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc  # type: ignore[attr-defined]
if not hasattr(_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _status.HTTP_413_CONTENT_TOO_LARGE = getattr(_status, "HTTP_413_REQUEST_ENTITY_TOO_LARGE", 413)  # type: ignore[attr-defined]
if not hasattr(_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _status.HTTP_422_UNPROCESSABLE_CONTENT = getattr(_status, "HTTP_422_UNPROCESSABLE_ENTITY", 422)  # type: ignore[attr-defined]

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.middleware.request_id import RequestIDMiddleware
from app.core.database import get_db
from app.core.exceptions import register_exception_handlers


def _build_app() -> FastAPI:
    from app.api.v1 import ragviz as ragviz_api

    app = FastAPI()
    app.add_middleware(RequestIDMiddleware)
    register_exception_handlers(app)
    app.include_router(ragviz_api.router, prefix="/api/v1/ragviz")
    app.dependency_overrides[get_current_account_id] = lambda: "acct-1"
    app.dependency_overrides[get_tenant_id] = lambda: uuid4()

    def _override_get_db():
        yield object()

    app.dependency_overrides[get_db] = _override_get_db
    return app


def test_resolve_similarity_request_limits_rejects_axis_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 200_000, raising=False)

    with pytest.raises(ragviz_similarity.SimilarityLimitError) as exc_info:
        ragviz_similarity.resolve_similarity_request_limits(
            x_max_items=501,
            y_max_items=50,
            max_items=100,
        )

    assert "x_max_items exceeds ragviz similarity axis limit" in str(exc_info.value)
    assert exc_info.value.detail == {"field": "x_max_items", "requested": 501, "limit": 500}


def test_resolve_similarity_request_limits_uses_backcompat_max_items(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 200_000, raising=False)

    assert ragviz_similarity.resolve_similarity_request_limits(
        x_max_items=None,
        y_max_items=None,
        max_items=37,
    ) == (37, 37)


def test_resolve_similarity_request_limits_rejects_pair_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 20_000, raising=False)

    with pytest.raises(ragviz_similarity.SimilarityLimitError) as exc_info:
        ragviz_similarity.resolve_similarity_request_limits(
            x_max_items=200,
            y_max_items=101,
            max_items=100,
        )

    assert "requested ragviz similarity matrix exceeds pair limit" in str(exc_info.value)
    assert exc_info.value.detail == {
        "field": "total_pairs",
        "x_max_items": 200,
        "y_max_items": 101,
        "requested": 20_200,
        "limit": 20_000,
    }


def test_calculate_similarity_matrix_rejects_oversize_before_loading_items(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 20_000, raising=False)
    monkeypatch.setattr(
        ragviz_similarity,
        "get_collection_items",
        lambda *_args, **_kwargs: pytest.fail("collection loading should not run for oversize requests"),
        raising=True,
    )

    with pytest.raises(ragviz_similarity.SimilarityLimitError):
        ragviz_similarity.calculate_similarity_matrix(
            SimpleNamespace(),
            uuid4(),
            "acct-1",
            x_collection="dataset_chunks:11111111-1111-1111-1111-111111111111",
            y_collection="dataset_chunks:22222222-2222-2222-2222-222222222222",
            x_max_items=200,
            y_max_items=101,
        )


def test_similarity_calculate_rejects_oversize_requests_with_422(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import ragviz as ragviz_api
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 20_000, raising=False)
    monkeypatch.setattr(
        ragviz_api,
        "calculate_similarity_matrix",
        lambda *_args, **_kwargs: pytest.fail("calculation should not run for oversize requests"),
        raising=True,
    )

    client = TestClient(_build_app())
    response = client.post(
        "/api/v1/ragviz/similarity/calculate",
        json={
            "x_collection": "dataset_chunks:11111111-1111-1111-1111-111111111111",
            "y_collection": "dataset_chunks:22222222-2222-2222-2222-222222222222",
            "x_max_items": 200,
            "y_max_items": 101,
        },
    )

    assert response.status_code == 422
    payload = response.json()
    assert payload["error"] == "VALIDATION_ERROR"
    assert "requested ragviz similarity matrix exceeds pair limit" in payload["message"]
    assert payload["detail"] == {
        "field": "total_pairs",
        "x_max_items": 200,
        "y_max_items": 101,
        "requested": 20_200,
        "limit": 20_000,
    }


def test_similarity_calculate_allows_small_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import ragviz as ragviz_api
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 20_000, raising=False)

    def _fake_calculate(*_args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        assert kwargs["x_max_items"] == 2
        assert kwargs["y_max_items"] == 3
        return {
            "matrix": [[0.1, 0.2], [0.3, 0.4], [0.5, 0.6]],
            "x_data": [{"id": "x1"}, {"id": "x2"}],
            "y_data": [{"id": "y1"}, {"id": "y2"}, {"id": "y3"}],
            "stats": {"total_pairs": 6},
        }

    monkeypatch.setattr(ragviz_api, "calculate_similarity_matrix", _fake_calculate, raising=True)

    client = TestClient(_build_app())
    response = client.post(
        "/api/v1/ragviz/similarity/calculate",
        json={
            "x_collection": "dataset_chunks:11111111-1111-1111-1111-111111111111",
            "y_collection": "dataset_chunks:22222222-2222-2222-2222-222222222222",
            "x_max_items": 2,
            "y_max_items": 3,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["result"]["stats"]["total_pairs"] == 6
    assert payload["message"] == "成功计算 3 x 2 相似度矩阵"


def test_similarity_calculate_preserves_dimension_mismatch_response_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import ragviz as ragviz_api
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 20_000, raising=False)

    def _raise_dimension_mismatch(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise ValueError("向量维度不匹配: (2, 10) vs (3, 11)")

    monkeypatch.setattr(ragviz_api, "calculate_similarity_matrix", _raise_dimension_mismatch, raising=True)

    response = ragviz_api.similarity_calculate(
        ragviz_api.SimilarityRequest(
            x_collection="dataset_chunks:11111111-1111-1111-1111-111111111111",
            y_collection="dataset_chunks:22222222-2222-2222-2222-222222222222",
            x_max_items=2,
            y_max_items=3,
        ),
        tenant_id=uuid4(),
        account_id="acct-1",
        db=SimpleNamespace(),
    )

    assert response.success is False
    assert response.error_type == "dimension_mismatch"
    assert "向量维度不匹配" in (response.error or "")


def test_similarity_calculate_raises_http_422_for_limit_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import ragviz as ragviz_api
    from app.services import ragviz_similarity

    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_AXIS_ITEMS", 500, raising=False)
    monkeypatch.setattr(ragviz_similarity.settings, "RAGVIZ_SIMILARITY_MAX_PAIRS", 20_000, raising=False)
    monkeypatch.setattr(
        ragviz_api,
        "calculate_similarity_matrix",
        lambda *_args, **_kwargs: pytest.fail("calculation should not run for rejected requests"),
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        ragviz_api.similarity_calculate(
            ragviz_api.SimilarityRequest(
                x_collection="dataset_chunks:11111111-1111-1111-1111-111111111111",
                y_collection="dataset_chunks:22222222-2222-2222-2222-222222222222",
                x_max_items=200,
                y_max_items=101,
            ),
            tenant_id=uuid4(),
            account_id="acct-1",
            db=SimpleNamespace(),
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == {
        "message": "requested ragviz similarity matrix exceeds pair limit (200 x 101 = 20200 > 20000)",
        "field": "total_pairs",
        "x_max_items": 200,
        "y_max_items": 101,
        "requested": 20_200,
        "limit": 20_000,
    }
