from __future__ import annotations


def test_kg_entity_alias_model_exists() -> None:
    """
    Wave15 foundation: entity resolution requires a first-class alias table.

    This test is intentionally lightweight (no DB) so CI can validate schema wiring
    even when integration tests are disabled.
    """
    from app.rag.kg import models

    assert hasattr(models, "KgEntityAlias")
    kg_entity_alias = models.KgEntityAlias
    assert kg_entity_alias.__tablename__ == "kg_entity_aliases"

    cols = set(kg_entity_alias.__table__.columns.keys())
    for required in ("id", "tenant_id", "canonical_entity_id", "alias", "normalized_alias"):
        assert required in cols


def test_kg_entity_redirect_model_exists() -> None:
    from app.rag.kg import models

    assert hasattr(models, "KgEntityRedirect")
    kg_entity_redirect = models.KgEntityRedirect
    assert kg_entity_redirect.__tablename__ == "kg_entity_redirects"

    cols = set(kg_entity_redirect.__table__.columns.keys())
    for required in ("from_entity_id", "tenant_id", "to_entity_id", "action_id"):
        assert required in cols


def test_kg_entity_resolution_action_model_exists() -> None:
    from app.rag.kg import models

    assert hasattr(models, "KgEntityResolutionAction")
    kg_entity_resolution_action = models.KgEntityResolutionAction
    assert kg_entity_resolution_action.__tablename__ == "kg_entity_resolution_actions"

    cols = set(kg_entity_resolution_action.__table__.columns.keys())
    for required in ("id", "tenant_id", "action_type", "payload", "status", "created_at"):
        assert required in cols


def test_kg_predicate_ontology_model_exists() -> None:
    from app.rag.kg import models

    assert hasattr(models, "KgPredicateOntology")
    kg_predicate_ontology = models.KgPredicateOntology
    assert kg_predicate_ontology.__tablename__ == "kg_predicate_ontology"

    cols = set(kg_predicate_ontology.__table__.columns.keys())
    for required in ("id", "tenant_id", "predicate", "is_enabled", "created_at", "updated_at"):
        assert required in cols
