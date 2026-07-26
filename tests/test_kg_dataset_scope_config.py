import pytest

from app.core.config import Settings


def test_kg_dataset_scope_doc_enumeration_cap_is_positive_and_bounded() -> None:
    with pytest.raises(ValueError, match="KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS must be between 1 and 10000"):
        Settings(KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS=0)

    with pytest.raises(ValueError, match="KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS must be between 1 and 10000"):
        Settings(KG_SEARCH_DATASET_SCOPE_MAX_ENUM_DOCS=10_001)
