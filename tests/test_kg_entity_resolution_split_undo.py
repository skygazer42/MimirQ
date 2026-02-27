from __future__ import annotations

from uuid import UUID

import pytest


class _FakeQuery:
    def __init__(self, items: list[object]):
        self._items = list(items)

    def filter_by(self, **kwargs):  # noqa: ANN003
        filtered: list[object] = []
        for item in self._items:
            ok = True
            for k, v in kwargs.items():
                if getattr(item, k, None) != v:
                    ok = False
                    break
            if ok:
                filtered.append(item)
        return _FakeQuery(filtered)

    def all(self):  # noqa: ANN201
        return list(self._items)

    def first(self):  # noqa: ANN201
        return self._items[0] if self._items else None


class _FakeSession:
    def __init__(self, *, entities, assocs, relations, redirects, actions, aliases):
        self.entities = list(entities)
        self.assocs = list(assocs)
        self.relations = list(relations)
        self.redirects = list(redirects)
        self.actions = list(actions)
        self.aliases = list(aliases)

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "KgEntity":
            return _FakeQuery(self.entities)
        if name == "KgEventEntity":
            return _FakeQuery(self.assocs)
        if name == "KgRelation":
            return _FakeQuery(self.relations)
        if name == "KgEntityRedirect":
            return _FakeQuery(self.redirects)
        if name == "KgEntityResolutionAction":
            return _FakeQuery(self.actions)
        if name == "KgEntityAlias":
            return _FakeQuery(self.aliases)
        return _FakeQuery([])

    def add(self, obj):  # noqa: ANN001
        name = obj.__class__.__name__
        if name == "KgEntity":
            self.entities.append(obj)
        elif name == "KgEventEntity":
            self.assocs.append(obj)
        elif name == "KgRelation":
            self.relations.append(obj)
        elif name == "KgEntityRedirect":
            self.redirects.append(obj)
        elif name == "KgEntityResolutionAction":
            self.actions.append(obj)
        elif name == "KgEntityAlias":
            self.aliases.append(obj)

    def delete(self, obj):  # noqa: ANN001
        for lst in (self.assocs, self.relations, self.redirects, self.aliases, self.entities):
            try:
                lst.remove(obj)
                return
            except ValueError:
                continue

    def flush(self):  # noqa: D401
        """No-op."""

    def commit(self):  # noqa: D401
        """No-op."""

    def rollback(self):  # noqa: D401
        """No-op."""


def test_kg_entity_split_and_undo(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    from app.rag.kg.api import routes as routes_mod
    from app.rag.kg.models import KgEntity, KgEventEntity
    from app.rag.kg.schemas import KGEntitySplitRequest

    tenant_id = UUID(int=1)
    ent_id = UUID(int=10)

    ent = KgEntity(id=ent_id, tenant_id=tenant_id, name="Python", type="Tech", normalized_name="python")

    ev1 = UUID(int=100)
    ev2 = UUID(int=101)
    assoc1 = KgEventEntity(id=UUID(int=201), event_id=ev1, entity_id=ent_id, weight=1.0, role=None, extra_data=None)
    assoc2 = KgEventEntity(id=UUID(int=202), event_id=ev2, entity_id=ent_id, weight=1.0, role=None, extra_data=None)

    db = _FakeSession(
        entities=[ent],
        assocs=[assoc1, assoc2],
        relations=[],
        redirects=[],
        actions=[],
        aliases=[],
    )

    out = routes_mod.split_kg_entity(
        payload=KGEntitySplitRequest(entity_id=ent_id, new_entity_name="Python (language)", event_ids=[ev2]),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert len(db.entities) == 2
    assert out.original_entity_id == ent_id
    new_id = out.new_entity_id
    assert new_id != ent_id

    # Only ev2 association moved.
    assert assoc1.entity_id == ent_id
    assert assoc2.entity_id == new_id

    undo = routes_mod.undo_kg_entity_resolution_action(
        action_id=out.action_id,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert undo.status == "reverted"
    assert assoc2.entity_id == ent_id
    # Undo should also prune the newly-created entity when it becomes orphaned.
    assert len(db.entities) == 1
