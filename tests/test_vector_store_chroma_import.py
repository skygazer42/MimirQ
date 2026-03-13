from __future__ import annotations

import sys
import types

import pytest

from app.storage.vector import factory as vector_factory


def test_get_chroma_cls_prefers_langchain_chroma(monkeypatch):
    class _PreferredChroma:
        pass

    class _FallbackChroma:
        pass

    langchain_chroma_mod = types.ModuleType("langchain_chroma")
    langchain_chroma_mod.Chroma = _PreferredChroma
    monkeypatch.setitem(sys.modules, "langchain_chroma", langchain_chroma_mod)
    monkeypatch.setitem(sys.modules, "chromadb", types.ModuleType("chromadb"))

    langchain_community_pkg = types.ModuleType("langchain_community")
    langchain_community_pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_community", langchain_community_pkg)

    vectorstores_mod = types.ModuleType("langchain_community.vectorstores")
    vectorstores_mod.Chroma = _FallbackChroma
    monkeypatch.setitem(sys.modules, "langchain_community.vectorstores", vectorstores_mod)
    langchain_community_pkg.vectorstores = vectorstores_mod  # type: ignore[attr-defined]

    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)

    chroma_cls = vector_factory._get_chroma_cls()
    assert chroma_cls is _PreferredChroma


def test_get_chroma_cls_falls_back_to_langchain_community(monkeypatch):
    class _FallbackChroma:
        pass

    broken_langchain_chroma_mod = types.ModuleType("langchain_chroma")
    monkeypatch.setitem(sys.modules, "langchain_chroma", broken_langchain_chroma_mod)
    monkeypatch.setitem(sys.modules, "chromadb", types.ModuleType("chromadb"))

    langchain_community_pkg = types.ModuleType("langchain_community")
    langchain_community_pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_community", langchain_community_pkg)

    vectorstores_mod = types.ModuleType("langchain_community.vectorstores")
    vectorstores_mod.Chroma = _FallbackChroma
    monkeypatch.setitem(sys.modules, "langchain_community.vectorstores", vectorstores_mod)
    langchain_community_pkg.vectorstores = vectorstores_mod  # type: ignore[attr-defined]

    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)

    chroma_cls = vector_factory._get_chroma_cls()
    assert chroma_cls is _FallbackChroma


def test_get_chroma_cls_raises_helpful_error_when_missing(monkeypatch):
    broken_langchain_chroma_mod = types.ModuleType("langchain_chroma")
    monkeypatch.setitem(sys.modules, "langchain_chroma", broken_langchain_chroma_mod)
    monkeypatch.setitem(sys.modules, "chromadb", types.ModuleType("chromadb"))

    langchain_community_pkg = types.ModuleType("langchain_community")
    langchain_community_pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_community", langchain_community_pkg)

    broken_vectorstores_mod = types.ModuleType("langchain_community.vectorstores")
    monkeypatch.setitem(sys.modules, "langchain_community.vectorstores", broken_vectorstores_mod)
    langchain_community_pkg.vectorstores = broken_vectorstores_mod  # type: ignore[attr-defined]

    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)

    with pytest.raises(RuntimeError) as excinfo:
        vector_factory._get_chroma_cls()

    msg = str(excinfo.value)
    assert "langchain-chroma" in msg
    assert "langchain-community" in msg
    assert "chromadb" in msg


def test_get_chroma_cls_raises_when_chromadb_import_broken(monkeypatch):
    class _PreferredChroma:
        pass

    class _FallbackChroma:
        pass

    langchain_chroma_mod = types.ModuleType("langchain_chroma")
    langchain_chroma_mod.Chroma = _PreferredChroma
    monkeypatch.setitem(sys.modules, "langchain_chroma", langchain_chroma_mod)

    langchain_community_pkg = types.ModuleType("langchain_community")
    langchain_community_pkg.__path__ = []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_community", langchain_community_pkg)

    vectorstores_mod = types.ModuleType("langchain_community.vectorstores")
    vectorstores_mod.Chroma = _FallbackChroma
    monkeypatch.setitem(sys.modules, "langchain_community.vectorstores", vectorstores_mod)
    langchain_community_pkg.vectorstores = vectorstores_mod  # type: ignore[attr-defined]

    monkeypatch.setattr(vector_factory, "_CHROMA_CLS", None)

    real_import = __import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):  # noqa: A002
        if name == "chromadb" or str(name).startswith("chromadb."):
            raise ImportError("chromadb import broken")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    with pytest.raises(RuntimeError) as excinfo:
        vector_factory._get_chroma_cls()

    assert "chromadb" in str(excinfo.value)
