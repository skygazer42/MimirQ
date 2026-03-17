def test_datetime_utc_is_available_on_supported_python_versions() -> None:
    import importlib

    import app  # noqa: F401

    datetime_mod = importlib.import_module("datetime")
    assert datetime_mod.UTC is datetime_mod.timezone.utc
