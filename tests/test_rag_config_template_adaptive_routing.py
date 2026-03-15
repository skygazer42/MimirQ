from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.services.rag_config_template_resolver import (
    aggregate_feedback_rewards,
    build_adaptive_routing_reward_writeback,
    resolve_rag_config_template,
)


@dataclass
class _Template:
    id: uuid.UUID
    tenant_id: uuid.UUID
    is_active: bool = True
    template_key: str | None = None
    version: int = 1
    ab_experiment_key: str | None = None
    ab_variant: str | None = None
    ab_weight: float = 1.0
    config_patch: dict[str, Any] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class _FakeQuery:
    def __init__(self, rows: list[_Template]) -> None:
        self._rows = rows

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def order_by(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def first(self) -> _Template | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[_Template]:
        return list(self._rows)


class _FakeSession:
    def __init__(self, rows: list[_Template]) -> None:
        self._rows = rows

    def query(self, *_args, **_kwargs) -> _FakeQuery:
        return _FakeQuery(self._rows)


def test_aggregate_feedback_rewards_from_rating_rows() -> None:
    snapshot = aggregate_feedback_rewards(
        [
            {"ab_variant": "A", "rating": 5},
            {"ab_variant": "A", "rating": 3},
            {"ab_variant": "B", "rating": 1},
            {"ab_variant": "B", "rating": 2},
            {"ab_variant": "", "rating": 5},
            {"ab_variant": "A", "rating": "bad"},
        ]
    )

    assert snapshot["schema"] == "mimirq.rag_config_reward_snapshot.v1"
    assert snapshot["total_feedback"] == 4
    assert snapshot["variants"]["A"]["count"] == 2
    assert snapshot["variants"]["B"]["count"] == 2
    assert snapshot["variants"]["A"]["avg_reward"] > snapshot["variants"]["B"]["avg_reward"]


def test_resolver_defaults_to_weighted_strategy_and_returns_debug_metadata() -> None:
    tenant_id = uuid.uuid4()
    variants = [
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-1", ab_variant="A", ab_weight=1.0),
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-1", ab_variant="B", ab_weight=9.0),
    ]
    db = _FakeSession(variants)

    chosen, debug = resolve_rag_config_template(
        db=db,
        tenant_id=tenant_id,
        ab_experiment_key="exp-1",
        ab_user_key="user-42",
        return_debug_metadata=True,
    )

    assert chosen is not None
    assert debug is not None
    assert debug["strategy"] == "weighted"
    assert debug["decision"] == "weighted"
    assert debug["chosen_variant"] == chosen.ab_variant
    assert "weights" in debug


def test_resolver_adaptive_mode_exploit_prefers_best_reward_variant() -> None:
    tenant_id = uuid.uuid4()
    variants = [
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-2", ab_variant="A", ab_weight=1.0),
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-2", ab_variant="B", ab_weight=1.0),
    ]
    db = _FakeSession(variants)
    reward_snapshot = aggregate_feedback_rewards(
        [
            {"ab_variant": "A", "rating": 5},
            {"ab_variant": "A", "rating": 4},
            {"ab_variant": "B", "rating": 1},
        ]
    )

    chosen, debug = resolve_rag_config_template(
        db=db,
        tenant_id=tenant_id,
        ab_experiment_key="exp-2",
        ab_user_key="user-99",
        routing_mode="adaptive",
        adaptive_epsilon=0.0,
        feedback_reward_snapshot=reward_snapshot,
        return_debug_metadata=True,
    )

    assert chosen is not None
    assert debug is not None
    assert chosen.ab_variant == "A"
    assert debug["strategy"] == "adaptive_epsilon_greedy"
    assert debug["decision"] == "exploit"
    assert debug["reward_snapshot"]["variants"]["A"]["avg_reward"] > debug["reward_snapshot"]["variants"]["B"]["avg_reward"]


def test_resolver_adaptive_mode_is_stable_for_same_user_key() -> None:
    tenant_id = uuid.uuid4()
    variants = [
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-3", ab_variant="A", ab_weight=2.0),
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-3", ab_variant="B", ab_weight=1.0),
    ]
    db = _FakeSession(variants)
    reward_snapshot = aggregate_feedback_rewards(
        [
            {"ab_variant": "A", "rating": 3},
            {"ab_variant": "B", "rating": 5},
        ]
    )

    first, first_debug = resolve_rag_config_template(
        db=db,
        tenant_id=tenant_id,
        ab_experiment_key="exp-3",
        ab_user_key="same-user",
        routing_mode="adaptive",
        adaptive_epsilon=0.35,
        feedback_reward_snapshot=reward_snapshot,
        return_debug_metadata=True,
    )
    second, second_debug = resolve_rag_config_template(
        db=db,
        tenant_id=tenant_id,
        ab_experiment_key="exp-3",
        ab_user_key="same-user",
        routing_mode="adaptive",
        adaptive_epsilon=0.35,
        feedback_reward_snapshot=reward_snapshot,
        return_debug_metadata=True,
    )

    assert first is not None and second is not None
    assert first_debug is not None and second_debug is not None
    assert first.id == second.id
    assert first_debug["decision"] == second_debug["decision"]
    assert first_debug["chosen_variant"] == second_debug["chosen_variant"]


def test_resolver_adaptive_mode_accepts_reward_hook() -> None:
    tenant_id = uuid.uuid4()
    variants = [
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-4", ab_variant="A", ab_weight=1.0),
        _Template(id=uuid.uuid4(), tenant_id=tenant_id, ab_experiment_key="exp-4", ab_variant="B", ab_weight=1.0),
    ]
    db = _FakeSession(variants)
    called: dict[str, bool] = {"ok": False}

    def _reward_hook(_db, _tenant_id, _exp, _variants):
        called["ok"] = True
        return [
            {"ab_variant": "B", "rating": 5},
            {"ab_variant": "A", "rating": 1},
        ]

    chosen, debug = resolve_rag_config_template(
        db=db,
        tenant_id=tenant_id,
        ab_experiment_key="exp-4",
        ab_user_key="hook-user",
        routing_mode="adaptive",
        adaptive_epsilon=0.0,
        feedback_reward_hook=_reward_hook,
        return_debug_metadata=True,
    )

    assert called["ok"] is True
    assert chosen is not None
    assert debug is not None
    assert chosen.ab_variant == "B"


def test_build_adaptive_routing_reward_writeback_schema() -> None:
    payload = build_adaptive_routing_reward_writeback(
        experiment_key="exp-42",
        variant="B",
        strategy="adaptive_epsilon_greedy",
        decision="exploit",
        request_id="req-abc",
        template_id="tpl-1",
        template_key="retrieval-fast",
    )

    assert payload["schema"] == "mimirq.rag_config_reward_writeback.v1"
    assert payload["experiment_key"] == "exp-42"
    assert payload["variant"] == "B"
    assert payload["strategy"] == "adaptive_epsilon_greedy"
    assert payload["decision"] == "exploit"
    assert payload["request_id"] == "req-abc"
    assert payload["template_id"] == "tpl-1"
    assert payload["template_key"] == "retrieval-fast"
