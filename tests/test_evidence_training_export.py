from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4


class _Query:
    def __init__(self, rows):  # noqa: ANN001
        self.rows = rows

    def join(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def outerjoin(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def limit(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def all(self):
        return self.rows


class _DB:
    def __init__(self, rows):  # noqa: ANN001
        self.rows = rows
        self.query_calls = 0

    def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        self.query_calls += 1
        return _Query(self.rows)


def test_feedback_training_export_loads_preceding_users_without_n_plus_one(monkeypatch) -> None:  # noqa: ANN001
    from app.api.v1 import evidence

    now = datetime.now(UTC)
    tenant_id = uuid4()
    dataset_id = uuid4()
    feedback = SimpleNamespace(
        id=uuid4(),
        extra={},
        tags=[],
        expected_answer=None,
        rating=5,
        reason=None,
        created_at=now,
        updated_at=now,
    )
    assistant = SimpleNamespace(id=uuid4(), created_at=now)
    conversation = SimpleNamespace(id=uuid4(), dataset_id=dataset_id)
    user_message = SimpleNamespace(id=uuid4(), content="question")
    db = _DB([(feedback, assistant, conversation, user_message)])
    monkeypatch.setattr(
        evidence,
        "materialize_feedback_case",
        lambda **_kwargs: SimpleNamespace(question="question", reference_sources=[]),
    )

    rows = evidence._collect_feedback_training_export_rows(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        limit=100,
    )

    assert db.query_calls == 1
    assert rows[0]["question"] == "question"
