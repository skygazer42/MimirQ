from app.rag.kg.search.config import SearchConfig


def test_kg_search_config_override_defaults() -> None:
    cfg = SearchConfig(query="q")
    assert cfg.relation_expansion_enabled is None
    assert cfg.include_skill_entities is True

