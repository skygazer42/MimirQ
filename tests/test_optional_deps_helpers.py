import logging

import pytest

from app.core.optional_deps import optional_import, require_dependency


def test_optional_import_logs_warning_and_returns_none(caplog):
    caplog.set_level(logging.WARNING)
    mod = optional_import("definitely_missing_pkg_xyz", feature="unit_test")
    assert mod is None
    assert any("Optional dependency missing" in r.message for r in caplog.records)


def test_require_dependency_raises_runtimeerror():
    with pytest.raises(RuntimeError) as exc:
        require_dependency("definitely_missing_pkg_xyz", feature="unit_test")
    assert "Missing dependency" in str(exc.value)

