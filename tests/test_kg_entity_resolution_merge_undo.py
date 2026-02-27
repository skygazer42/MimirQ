from __future__ import annotations

from uuid import UUID

import pytest


class _FakeQuery:
    def __init__(self, items: list[object]):
        self._items = list(items)

    def filter_by(self, **kwargs):  # noqa: ANN003, D401
        """Very small subset of SQLAlchemy Query.filter_by for unit tests."""
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

        self.committed = False
        self.rolled_back = False

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
        if name == "KgEntityRedirect":
            self.redirects.append(obj)
        elif name == "KgEntityResolutionAction":
            self.actions.append(obj)
        elif name == "KgEntityAlias":
            self.aliases.append(obj)
        elif name == "KgEventEntity":
            self.assocs.append(obj)
        elif name == "KgRelation":
            self.relations.append(obj)
        else:
            # Keep it extensible for other objects, but don't fail unit tests.
            pass

    def delete(self, obj):  # noqa: ANN001
        for lst in (self.assocs, self.relations, self.redirects, self.aliases):
            try:
                lst.remove(obj)
                return
            except ValueError:
                continue

    def flush(self):  # noqa: D401
        """No-op."""

    def commit(self):  # noqa: D401
        """Mark committed."""
        self.committed = True

    def rollback(self):  # noqa: D401
        """Mark rolled back."""
        self.rolled_back = True


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
def test_kg_entity_merge_creates_redirect_and_dedupes(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    from app.rag.kg.api import routes as routes_mod
    from app.rag.kg.models import KgEntity, KgEntityAlias, KgEventEntity, KgRelation
    from app.rag.kg.schemas import KGEntityMergeRequest

    tenant_id = UUID(int=1)
    source_id = UUID(int=10)
    target_id = UUID(int=11)

    source_ent = KgEntity(
        id=source_id,
        tenant_id=tenant_id,
        name="RAG",
        type="Tech",
        normalized_name="rag",
        description=None,
        vector=None,
        extra_data=None,
    )
    target_ent = KgEntity(
        id=target_id,
        tenant_id=tenant_id,
        name="Retrieval-Augmented Generation",
        type="Tech",
        normalized_name="retrieval augmented generation",
        description=None,
        vector=None,
        extra_data=None,
    )

    ev1 = UUID(int=100)
    ev2 = UUID(int=101)

    assoc_target = KgEventEntity(id=UUID(int=201), event_id=ev1, entity_id=target_id, weight=1.0, role=None, extra_data=None)
    assoc_source_1 = KgEventEntity(id=UUID(int=202), event_id=ev1, entity_id=source_id, weight=0.8, role=None, extra_data=None)
    assoc_source_2 = KgEventEntity(id=UUID(int=203), event_id=ev2, entity_id=source_id, weight=0.5, role=None, extra_data=None)

    rel = KgRelation(
        id=UUID(int=301),
        tenant_id=tenant_id,
        pipeline_hash=None,
        document_id=None,
        chunk_id=None,
        event_id=None,
        subject_entity_id=source_id,
        predicate="alias_of",
        predicate_raw=None,
        object_entity_id=target_id,
        confidence=0.9,
        qualifiers=None,
        references=None,
        extra_data=None,
    )

    alias = KgEntityAlias(
        id=UUID(int=401),
        tenant_id=tenant_id,
        canonical_entity_id=source_id,
        alias="RAG",
        normalized_alias="rag",
        created_by="u",
        extra_data=None,
    )

    db = _FakeSession(
        entities=[source_ent, target_ent],
        assocs=[assoc_target, assoc_source_1, assoc_source_2],
        relations=[rel],
        redirects=[],
        actions=[],
        aliases=[alias],
    )

    out = routes_mod.merge_kg_entities(
        payload=KGEntityMergeRequest(source_entity_id=source_id, target_entity_id=target_id),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    # Redirect created.
    assert len(db.redirects) == 1
    assert db.redirects[0].from_entity_id == source_id
    assert db.redirects[0].to_entity_id == target_id

    # All associations are now on the target.
    assert all(a.entity_id == target_id for a in db.assocs)

    # Deduped event1 so it does not have duplicate entity edges.
    e1_rows = [a for a in db.assocs if a.event_id == ev1 and a.entity_id == target_id]
    assert len(e1_rows) == 1
    assert e1_rows[0].id == assoc_target.id

    # Relation between source<->target becomes self after merge and should be removed.
    assert db.relations == []

    # Action persisted.
    assert len(db.actions) == 1
    assert str(out.action_id) == str(db.actions[0].id)
    assert db.actions[0].action_type == "merge"
    assert db.actions[0].status == "applied"
    assert isinstance(db.actions[0].payload, dict)
    assert str(db.actions[0].payload.get("source_entity_id")) == str(source_id)
    assert str(db.actions[0].payload.get("target_entity_id")) == str(target_id)


def test_kg_entity_merge_undo_restores_source_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    from app.rag.kg.api import routes as routes_mod
    from app.rag.kg.models import KgEntity, KgEventEntity
    from app.rag.kg.schemas import KGEntityMergeRequest

    tenant_id = UUID(int=1)
    source_id = UUID(int=10)
    target_id = UUID(int=11)

    source_ent = KgEntity(id=source_id, tenant_id=tenant_id, name="A", type="Tech", normalized_name="a")
    target_ent = KgEntity(id=target_id, tenant_id=tenant_id, name="B", type="Tech", normalized_name="b")

    ev1 = UUID(int=100)
    assoc_target = KgEventEntity(id=UUID(int=201), event_id=ev1, entity_id=target_id, weight=1.0, role=None, extra_data=None)
    assoc_source = KgEventEntity(id=UUID(int=202), event_id=ev1, entity_id=source_id, weight=0.8, role=None, extra_data=None)

    db = _FakeSession(
        entities=[source_ent, target_ent],
        assocs=[assoc_target, assoc_source],
        relations=[],
        redirects=[],
        actions=[],
        aliases=[],
    )

    merge_out = routes_mod.merge_kg_entities(
        payload=KGEntityMergeRequest(source_entity_id=source_id, target_entity_id=target_id),
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert len(db.redirects) == 1
    assert all(a.entity_id == target_id for a in db.assocs)

    undo_out = routes_mod.undo_kg_entity_resolution_action(
        action_id=merge_out.action_id,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert str(undo_out.action_id) == str(merge_out.action_id)
    assert db.redirects == []
    assert any(a.entity_id == source_id for a in db.assocs)
    assert any(a.entity_id == target_id for a in db.assocs)
    assert db.actions[0].status == "reverted"
