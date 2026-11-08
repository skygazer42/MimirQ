import pytest


@pytest.mark.parametrize(
    "field", ["RETRIEVAL_OVERFETCH_MULTIPLIER", "RETRIEVAL_COMPACT_MIN_RECORDS", "HIERARCHY_RECALL_OVERFETCH_FACTOR"]
)
def test_invalid_zero_is_validated_instead_of_substituted(field):
    from app.core.config import settings
    from app.core.config_validation import validate_chunk_llm_and_retrieval

    config = settings.model_copy(update={field: 0})
    with pytest.raises(ValueError, match=field):
        validate_chunk_llm_and_retrieval(config)


def test_empty_bootstrap_fields_still_mean_not_configured():
    from app.core.config import settings
    from app.core.config_validation import validate_initial_admin_bootstrap

    config = settings.model_copy(
        update={
            "INITIAL_ADMIN_EMAIL": "",
            "INITIAL_ADMIN_USERNAME": "",
            "INITIAL_ADMIN_PASSWORD": "",
            "INITIAL_ADMIN_PASSWORD_FILE": "",
        }
    )
    validate_initial_admin_bootstrap(config)


def test_empty_secret_is_still_rejected():
    from app.core.config import settings
    from app.core.config_validation import validate_secret_key_and_jwt_key_source

    with pytest.raises(ValueError):
        validate_secret_key_and_jwt_key_source(settings.model_copy(update={"SECRET_KEY": ""}))


def test_unresolved_password_minimum_keeps_existing_safety_floor():
    from app.core.config import settings
    from app.core.config_validation import _validate_initial_admin_password

    with pytest.raises(ValueError):
        _validate_initial_admin_password(settings.model_copy(update={"PASSWORD_MIN_LENGTH": 0}), "x")
