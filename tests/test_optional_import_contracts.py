import builtins
import sys
from types import ModuleType

import pytest


def _documents_module() -> ModuleType:
    from app.api.v1 import documents

    return documents


def _document_upload_module() -> ModuleType:
    _documents_module()
    from app.api.v1 import document_upload

    return document_upload


def _chat_module() -> ModuleType:
    _documents_module()
    from app.api.v1 import chat

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


def _install_faiss_wrapper(monkeypatch: pytest.MonkeyPatch, faiss_cls: type) -> None:
    package = ModuleType("langchain_community")
    package.__dict__["__path__"] = []
    vectorstores = ModuleType("langchain_community.vectorstores")
    vectorstores.__dict__["FAISS"] = faiss_cls
    package.__dict__["vectorstores"] = vectorstores
    monkeypatch.setitem(sys.modules, "langchain_community", package)
    monkeypatch.setitem(sys.modules, "langchain_community.vectorstores", vectorstores)


def _install_chroma_wrapper(monkeypatch: pytest.MonkeyPatch, chroma_cls: type) -> None:
    module = ModuleType("langchain_chroma")
    module.__dict__["Chroma"] = chroma_cls
    monkeypatch.setitem(sys.modules, "langchain_chroma", module)


def test_chat_module_keeps_auto_title_monkeypatch_seam() -> None:
    from app.services import chat_conversation_titles as titles

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

    from app.core import http_client

    assert http_client.h2 is h2
    assert http_client._HTTP2_AVAILABLE is True


def test_rag_text_keeps_estimate_tokens_reexport() -> None:
    from app.core import token_utils
    from app.rag.core import text as rag_text

    assert rag_text.estimate_tokens is token_utils.estimate_tokens


def test_reranker_factory_keeps_describe_provider_reexport() -> None:
    from app.rag.reranker import capabilities
    from app.rag.reranker import factory as reranker_factory

    assert reranker_factory.describe_reranker_provider is capabilities.describe_reranker_provider


@pytest.mark.parametrize("strategy", ["llama_index", "llama_index_hierarchical"])
def test_llama_strategy_does_not_hide_unrelated_runtime_errors(
    monkeypatch: pytest.MonkeyPatch,
    strategy: str,
) -> None:
    from app.rag.chunking import strategy_matrix

    _install_llama_index_stub(monkeypatch)

    assert strategy_matrix._is_expected_unavailable(strategy, RuntimeError("boom")) is False


@pytest.mark.parametrize("message", ["feature disabled", "dependency not installed"])
def test_llama_strategy_preserves_expected_unavailable_messages(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    from app.rag.chunking import strategy_matrix

    _install_llama_index_stub(monkeypatch)

    assert strategy_matrix._is_expected_unavailable("llama_index", RuntimeError(message)) is True


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, RuntimeError])
def test_llama_strategy_treats_missing_or_broken_import_as_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    from app.rag.chunking import strategy_matrix

    _fail_import(monkeypatch, "llama_index.core", error_type("optional dependency failed"))

    assert strategy_matrix._is_expected_unavailable("llama_index", RuntimeError("boom")) is True


def test_colbert_readiness_does_not_read_lazy_transformers_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.reranker import colbert

    _install_hf_stubs(monkeypatch)

    readiness = colbert.check_colbert_provider_readiness(
        provider_name="hf",
        model_name="stub-model",
        device="cpu",
    )

    assert readiness["ready"] is True
    assert readiness["reason"] == "none"
    assert readiness["dependency_ok"] is True


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, RuntimeError])
def test_colbert_readiness_handles_missing_or_broken_transformers(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    from app.rag.reranker import colbert

    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    _fail_import(monkeypatch, "transformers", error_type("optional dependency failed"))

    readiness = colbert.check_colbert_provider_readiness(
        provider_name="hf",
        model_name="stub-model",
        device="cpu",
    )

    assert readiness["ready"] is False
    assert readiness["reason"] == "dependency_missing"
    assert readiness["dependency_ok"] is False


def test_colbert_ann_readiness_does_not_read_lazy_transformers_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retrieval import colbert_ann

    _install_hf_stubs(monkeypatch)

    readiness = colbert_ann.resolve_colbert_ann_provider_capability(
        colbert_enabled=True,
        requested_provider="hf",
        model_name="stub-model",
        device="cpu",
        docs_count=1,
        max_docs=10,
    )

    assert readiness["status"] == "ready"
    assert readiness["reason"] == "none"
    assert readiness["effective_provider"] == "hf"
    assert readiness["ready"] is True


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, RuntimeError])
def test_colbert_ann_readiness_handles_missing_or_broken_transformers(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    from app.rag.retrieval import colbert_ann

    monkeypatch.setitem(sys.modules, "torch", ModuleType("torch"))
    _fail_import(monkeypatch, "transformers", error_type("optional dependency failed"))

    readiness = colbert_ann.resolve_colbert_ann_provider_capability(
        colbert_enabled=True,
        requested_provider="hf",
        model_name="stub-model",
        device="cpu",
        docs_count=1,
        max_docs=10,
    )

    assert readiness["status"] == "fallback"
    assert readiness["reason"] == "dependency_missing"
    assert readiness["effective_provider"] == "deterministic"
    assert readiness["ready"] is True


def test_faiss_probe_uses_import_without_reading_lazy_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.storage.vector import factory as vector_factory

    class FakeFAISS:
        pass

    monkeypatch.setattr(vector_factory, "_FAISS_CLS", None)
    monkeypatch.setitem(sys.modules, "faiss", _hostile_lazy_module("faiss"))
    _install_faiss_wrapper(monkeypatch, FakeFAISS)

    assert vector_factory._get_faiss_cls() is FakeFAISS


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, RuntimeError])
def test_faiss_probe_wraps_missing_or_broken_dependency(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    from app.storage.vector import factory as vector_factory

    monkeypatch.setattr(vector_factory, "_FAISS_CLS", None)
    _fail_import(monkeypatch, "faiss", error_type("optional dependency failed"))

    with pytest.raises(RuntimeError, match="FAISS vector backend") as exc_info:
        vector_factory._get_faiss_cls()

    assert isinstance(exc_info.value.__cause__, error_type)


def test_chroma_probe_uses_pypika_import_without_reading_lazy_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.storage.vector import factory as vector_factory

    class FakeChroma:
        pass

    chromadb = ModuleType("chromadb")
    chromadb.__dict__["__file__"] = "/stub/chromadb.py"
    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)
    monkeypatch.setitem(sys.modules, "chromadb", chromadb)
    monkeypatch.setitem(sys.modules, "pypika", _hostile_lazy_module("pypika"))
    _install_chroma_wrapper(monkeypatch, FakeChroma)

    assert vector_factory._get_chroma_cls() is FakeChroma


def test_chroma_probe_allows_fileless_module_seam_without_pypika(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.storage.vector import factory as vector_factory

    class FakeChroma:
        pass

    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)
    monkeypatch.setitem(sys.modules, "chromadb", ModuleType("chromadb"))
    _fail_import(monkeypatch, "pypika", RuntimeError("pypika must be skipped"))
    _install_chroma_wrapper(monkeypatch, FakeChroma)

    assert vector_factory._get_chroma_cls() is FakeChroma


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, RuntimeError])
def test_chroma_probe_wraps_missing_or_broken_chromadb(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    from app.storage.vector import factory as vector_factory

    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)
    _fail_import(monkeypatch, "chromadb", error_type("optional dependency failed"))

    with pytest.raises(RuntimeError, match="Chroma vector backend") as exc_info:
        vector_factory._get_chroma_cls()

    assert isinstance(exc_info.value.__cause__, error_type)


@pytest.mark.parametrize("error_type", [ModuleNotFoundError, RuntimeError])
def test_chroma_probe_wraps_missing_or_broken_pypika(
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[Exception],
) -> None:
    from app.storage.vector import factory as vector_factory

    chromadb = ModuleType("chromadb")
    chromadb.__dict__["__file__"] = "/stub/chromadb.py"
    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)
    monkeypatch.setitem(sys.modules, "chromadb", chromadb)
    _fail_import(monkeypatch, "pypika", error_type("optional dependency failed"))

    with pytest.raises(RuntimeError, match="Chroma vector backend") as exc_info:
        vector_factory._get_chroma_cls()

    assert isinstance(exc_info.value.__cause__, error_type)
