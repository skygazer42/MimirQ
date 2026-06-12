from types import SimpleNamespace

from app.api.v1 import pipeline


def test_dependency_backend_capability_does_not_import_heavy_modules(monkeypatch):
    monkeypatch.setattr(pipeline.settings, "DOCLING_ENABLED", True)

    def fail_import(*_args, **_kwargs):
        raise AssertionError("capability checks must not import heavy parser modules")

    monkeypatch.setattr(pipeline, "check_dependency", fail_import)

    def fake_version(package_name: str) -> str:
        assert package_name == "docling"
        return "1.0.0"

    monkeypatch.setattr(pipeline, "importlib_metadata", SimpleNamespace(version=fake_version), raising=False)

    available, notes = pipeline._dependency_backend_availability(
        enabled_setting="DOCLING_ENABLED",
        enable_note="Set DOCLING_ENABLED=true.",
        module="docling.document_converter",
        attr="DocumentConverter",
        package_name="docling",
    )

    assert available is True
    assert notes is None
