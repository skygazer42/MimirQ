import builtins
import sys
from types import ModuleType

import pytest


def _hostile_lazy_module(name: str) -> ModuleType:
    module = ModuleType(name)

    def _raise_on_attribute(attribute: str) -> None:
        raise RuntimeError(f"{name}.{attribute} must not be read")

    module.__dict__["__getattr__"] = _raise_on_attribute
    return module


def _install_llama_index_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    package = ModuleType("llama_index")
    package.__dict__["__path__"] = []
    core = ModuleType("llama_index.core")
    package.__dict__["core"] = core
    monkeypatch.setitem(sys.modules, "llama_index", package)
    monkeypatch.setitem(sys.modules, "llama_index.core", core)


def _install_hf_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    monkeypatch.setitem(sys.modules, "transformers", _hostile_lazy_module("transformers"))


def _fail_import(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    error: Exception,
) -> None:
    original_import = builtins.__import__

    def _import(
        name: str,
        globals: dict[str, object] | None = None,
        locals: dict[str, object] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> object:
        if name == module_name:
            raise error
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _import)


def test_chat_bootstrap_uses_the_shared_auto_title_service() -> None:
    from app.services.chat import bootstrap, conversation_titles

    assert bootstrap.apply_auto_conversation_title is conversation_titles.apply_auto_conversation_title


def test_document_storage_uses_enabled_legacy_minio(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.config import settings
    from app.storage.object import minio, runtime

    monkeypatch.setattr(settings, "OBJECT_STORAGE_ENABLED", False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", True)
    monkeypatch.setattr(settings, "MINIO_DOCUMENTS_ENABLED", True)
    assert runtime.get_document_object_store() is minio.minio_service


def test_document_assets_use_the_shared_object_reference_resolver() -> None:
    from app.api.v1.documents import assets
    from app.storage.object import runtime as object_runtime

    assert assets.resolve_document_object_reference is object_runtime.resolve_document_object_reference


def test_http_client_keeps_h2_probe_binding() -> None:
    import h2

    from app.infrastructure.http import client as http_client

    assert http_client.h2 is h2
    assert http_client._HTTP2_AVAILABLE is True


@pytest.mark.parametrize("strategy", ["llama_index", "llama_index_hierarchical"])
def test_llama_strategy_does_not_hide_unrelated_runtime_errors(
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
) -> None:
    from app.rag.ingestion.chunking import strategy_matrix

    _install_llama_index_stub(monkeypatch)

    assert strategy_matrix._is_expected_unavailable(strategy, RuntimeError("boom")) is False


@pytest.mark.parametrize("message", ["feature disabled", "dependency not installed"])
def test_llama_strategy_preserves_expected_unavailable_messages(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    from app.rag.ingestion.chunking import strategy_matrix

    _install_llama_index_stub(monkeypatch)

    assert strategy_matrix._is_expected_unavailable("llama_index", RuntimeError(message)) is True


@pytest.mark.parametrize("module_name", ["llama_index", "llama_index.core"])
def test_llama_strategy_reports_missing_optional_dependency_as_unavailable(module_name: str) -> None:
    from app.rag.ingestion.chunking import strategy_matrix

    missing = ModuleNotFoundError(name=module_name)
    assert strategy_matrix._is_expected_unavailable("llama_index", missing) is True


def test_llama_strategy_keeps_failed_imports_visible_without_reimporting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.ingestion.chunking import strategy_matrix

    _fail_import(
        monkeypatch, "llama_index.core", AssertionError("failure classification must not reimport the dependency")
    )
    assert strategy_matrix._is_expected_unavailable("llama_index", RuntimeError("optional dependency failed")) is False
