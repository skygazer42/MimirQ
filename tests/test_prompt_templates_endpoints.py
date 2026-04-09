from __future__ import annotations

import operator
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.prompt_template import PromptTemplate


def _condition_value(condition: Any) -> Any:
    right = getattr(condition, "right", None)
    if right is None:
        return None
    if hasattr(right, "value"):
        return right.value
    if hasattr(right, "effective_value"):
        return right.effective_value
    return right


def _matches(template: PromptTemplate, condition: Any) -> bool:
    left = getattr(condition, "left", None)
    key = getattr(left, "key", None) or getattr(left, "name", None)
    op = getattr(condition, "operator", None)
    value = _condition_value(condition)
    current = getattr(template, str(key), None)

    if op is operator.eq:
        return current == value
    if op is operator.ne:
        return current != value
    raise AssertionError(f"Unsupported SQLAlchemy filter operator: {op!r}")


@dataclass
class _Query:
    db: "_FakeDB"
    target: Any
    items: list[PromptTemplate]

    def filter(self, *conditions: Any):
        self.items = [item for item in self.items if all(_matches(item, cond) for cond in conditions)]
        return self

    def count(self) -> int:
        return len(self.items)

    def order_by(self, *_clauses: Any):
        self.items.sort(
            key=lambda item: (
                bool(getattr(item, "is_system", False)),
                int(getattr(item, "usage_count", 0) or 0),
                getattr(item, "updated_at", None) or getattr(item, "created_at", None) or datetime.min.replace(tzinfo=UTC),
            ),
            reverse=True,
        )
        return self

    def offset(self, value: int):
        self.items = self.items[max(0, int(value or 0)) :]
        return self

    def limit(self, value: int):
        self.items = self.items[: max(0, int(value or 0))]
        return self

    def all(self) -> list[PromptTemplate]:
        return list(self.items)

    def first(self) -> PromptTemplate | None:
        return self.items[0] if self.items else None

    def scalar(self) -> int | None:
        clauses_attr = getattr(self.target, "clauses", None)
        clauses = list(clauses_attr) if clauses_attr is not None else []
        clause = clauses[0] if clauses else None
        key = getattr(clause, "key", None) or getattr(clause, "name", None)
        if getattr(self.target, "name", None) == "max" and key == "version":
            versions = [int(getattr(item, "version", 0) or 0) for item in self.items]
            return max(versions) if versions else None
        raise AssertionError(f"Unsupported scalar target: {self.target!r}")

    def update(self, values: dict[str, Any]) -> int:
        now = datetime.now(UTC)
        for item in self.items:
            for key, value in values.items():
                setattr(item, key, value)
            item.updated_at = now
        return len(self.items)


class _FakeDB:
    def __init__(self, items: list[PromptTemplate] | None = None):
        self.items = list(items or [])

    def query(self, target: Any):
        return _Query(db=self, target=target, items=list(self.items))

    def add(self, obj: PromptTemplate) -> None:
        now = datetime.now(UTC)
        if not getattr(obj, "id", None):
            obj.id = uuid.uuid4()
        if not getattr(obj, "tenant_id", None):
            obj.tenant_id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        obj.updated_at = now
        if getattr(obj, "usage_count", None) is None:
            obj.usage_count = 0
        if getattr(obj, "variables", None) is None:
            obj.variables = []
        if getattr(obj, "tags", None) is None:
            obj.tags = []
        if getattr(obj, "version", None) is None:
            obj.version = 1
        if getattr(obj, "ab_weight", None) is None:
            obj.ab_weight = 1.0
        if getattr(obj, "is_active", None) is None:
            obj.is_active = True
        if getattr(obj, "is_system", None) is None:
            obj.is_system = False
        self.items.append(obj)

    def delete(self, obj: PromptTemplate) -> None:
        self.items = [item for item in self.items if item is not obj]

    def commit(self) -> None:
        return None

    def refresh(self, obj: PromptTemplate) -> None:
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(UTC)


def _seed_template(
    *,
    tenant_id: uuid.UUID,
    name: str,
    template_key: str | None = None,
    version: int = 1,
    is_system: bool = False,
    is_active: bool = True,
    category: str | None = "assistant",
) -> PromptTemplate:
    now = datetime.now(UTC)
    template = PromptTemplate(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        template_key=template_key,
        version=version,
        name=name,
        description=f"{name} description",
        content=f"{name} content",
        variables=["context", "question"],
        category=category,
        tags=["team"],
        is_active=is_active,
        is_system=is_system,
        usage_count=version,
        parent_id=None,
        ab_experiment_key=None,
        ab_variant=None,
        ab_weight=1.0,
        created_at=now,
        updated_at=now,
    )
    return template


def _build_client(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tenant_id: uuid.UUID,
    items: list[PromptTemplate] | None = None,
) -> tuple[TestClient, _FakeDB]:
    import app.api.v1.prompt_templates as prompt_templates_api

    db = _FakeDB(items)

    def _override_get_db():  # noqa: ANN202
        yield db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-user"

    monkeypatch.setattr(
        prompt_templates_api.DatasetService,
        "ensure_member",
        staticmethod(lambda *_args, **_kwargs: None),
        raising=False,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(prompt_templates_api.router, prefix="/api/v1/prompt-templates")
    return TestClient(app), db


def test_prompt_templates_crud_duplicate_and_version_flow(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    client, db = _build_client(monkeypatch=monkeypatch, tenant_id=tenant_id)

    create_res = client.post(
        "/api/v1/prompt-templates",
        json={
            "name": "Answer Coach",
            "description": "Answer quality prompt",
            "content": "Context: {context}\nQuestion: {question}",
            "variables": ["context", "question"],
            "category": "assistant",
            "tags": ["golden"],
            "is_active": True,
        },
    )
    assert create_res.status_code == 201, create_res.text
    created = create_res.json()
    assert created["template_key"] == "answer_coach"
    assert created["version"] == 1
    assert created["is_active"] is True

    create_v2 = client.post(
        "/api/v1/prompt-templates",
        json={
            "template_key": "answer_coach",
            "name": "Answer Coach Warm",
            "description": "Variant",
            "content": "Use warmer tone",
            "variables": ["question"],
            "category": "assistant",
            "tags": ["variant"],
            "is_active": True,
        },
    )
    assert create_v2.status_code == 201, create_v2.text
    created_v2 = create_v2.json()
    assert created_v2["template_key"] == "answer_coach"
    assert created_v2["version"] == 2

    list_res = client.get("/api/v1/prompt-templates?category=assistant&is_active=true&limit=20")
    assert list_res.status_code == 200, list_res.text
    body = list_res.json()
    assert body["total"] == 2
    assert [item["name"] for item in body["items"]] == ["Answer Coach Warm", "Answer Coach"]

    get_res = client.get(f"/api/v1/prompt-templates/{created['id']}")
    assert get_res.status_code == 200, get_res.text
    assert get_res.json()["name"] == "Answer Coach"

    update_res = client.put(
        f"/api/v1/prompt-templates/{created['id']}",
        json={"description": "Updated description", "is_active": False},
    )
    assert update_res.status_code == 200, update_res.text
    assert update_res.json()["description"] == "Updated description"
    assert update_res.json()["is_active"] is False

    duplicate_res = client.post(f"/api/v1/prompt-templates/{created_v2['id']}/duplicate")
    assert duplicate_res.status_code == 201, duplicate_res.text
    duplicate = duplicate_res.json()
    assert duplicate["name"] == "Answer Coach Warm (Copy)"
    assert duplicate["is_system"] is False
    assert duplicate["is_active"] is True

    version_res = client.post(
        f"/api/v1/prompt-templates/{created_v2['id']}/versions",
        json={
            "content": "Version 3 prompt",
            "description": "Versioned rollout",
            "is_active": True,
            "deactivate_previous": True,
            "ab_experiment_key": "exp-q2",
            "ab_variant": "B",
            "ab_weight": 0.4,
        },
    )
    assert version_res.status_code == 201, version_res.text
    versioned = version_res.json()
    assert versioned["version"] == 3
    assert versioned["parent_id"] == created_v2["id"]
    assert versioned["content"] == "Version 3 prompt"
    assert versioned["ab_variant"] == "B"

    original_v2 = next(item for item in db.items if str(item.id) == created_v2["id"])
    assert original_v2.is_active is False

    delete_res = client.delete(f"/api/v1/prompt-templates/{duplicate['id']}")
    assert delete_res.status_code == 204, delete_res.text
    assert all(str(item.id) != duplicate["id"] for item in db.items)


def test_prompt_templates_block_system_mutations_and_missing_scope(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = uuid.uuid4()
    system_template = _seed_template(
        tenant_id=tenant_id,
        name="System Answer",
        template_key="system_answer",
        is_system=True,
        is_active=True,
    )
    other_tenant_template = _seed_template(
        tenant_id=uuid.uuid4(),
        name="Other Tenant",
        template_key="other_tenant",
    )
    client, _db = _build_client(
        monkeypatch=monkeypatch,
        tenant_id=tenant_id,
        items=[system_template, other_tenant_template],
    )

    update_res = client.put(f"/api/v1/prompt-templates/{system_template.id}", json={"name": "blocked"})
    assert update_res.status_code == 403, update_res.text
    assert update_res.json()["detail"] == "Cannot modify system templates"

    delete_res = client.delete(f"/api/v1/prompt-templates/{system_template.id}")
    assert delete_res.status_code == 403, delete_res.text
    assert delete_res.json()["detail"] == "Cannot delete system templates"

    version_res = client.post(
        f"/api/v1/prompt-templates/{system_template.id}/versions",
        json={"content": "new version"},
    )
    assert version_res.status_code == 403, version_res.text
    assert version_res.json()["detail"] == "Cannot version system templates"

    missing_res = client.get(f"/api/v1/prompt-templates/{other_tenant_template.id}")
    assert missing_res.status_code == 404, missing_res.text
    assert missing_res.json()["detail"] == "Prompt template not found"
