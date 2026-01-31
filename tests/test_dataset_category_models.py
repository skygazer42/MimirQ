def test_dataset_category_models_registered() -> None:
    """
    Contract test: dataset category models are registered for SQLAlchemy metadata creation.

    This prevents runtime surprises where Base.metadata.create_all() misses new tables
    because the modules were never imported.
    """

    import app.models.dataset_category  # noqa: F401
    from app.core.database import Base

    assert "dataset_categories" in Base.metadata.tables
    assert "dataset_category_memberships" in Base.metadata.tables

