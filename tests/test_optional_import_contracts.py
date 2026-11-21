import builtins
import sys
from types import ModuleType

import pytest


def _documents_module() -> ModuleType:
    from app.api.v1.documents import routes as documents

    return documents


def _document_upload_module() -> ModuleType:
    _documents_module()
    from app.api.v1.documents import upload as document_upload

    return document_upload


def _chat_module() -> ModuleType:
    _documents_module()
    from app.api.v1.conversations import routes as chat

    return chat


def _api_modules() -> tuple[ModuleType, ModuleType, ModuleType]:
    documents = _documents_module()
    document_upload = _document_upload_module()
    chat = _chat_module()
    return chat, document_upload, documents


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


def test_chat_module_keeps_auto_title_monkeypatch_seam() -> None:
    from app.services.chat import conversation_titles as titles

    chat, _, _ = _api_modules()

    assert chat._apply_auto_conversation_title is titles.apply_auto_conversation_title


def test_document_upload_module_keeps_minio_service_seam() -> None:
    from app.storage.object import minio

    _, document_upload, _ = _api_modules()

    assert document_upload.minio_service is minio.minio_service


def test_documents_module_keeps_object_reference_resolver_seam() -> None:
    from app.storage.object import runtime as object_runtime

    _, _, documents = _api_modules()

    assert documents.resolve_document_object_reference is object_runtime.resolve_document_object_reference


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


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, RuntimeError])
def test_llama_strategy_treats_missing_or_broken_import_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    from app.rag.ingestion.chunking import strategy_matrix

    _fail_import(monkeypatch, "llama_index.core", error_type("optional dependency failed"))

    assert strategy_matrix._is_expected_unavailable("llama_index", RuntimeError("boom")) is True
