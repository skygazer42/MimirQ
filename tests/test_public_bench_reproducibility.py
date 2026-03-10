from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_script(rel: str):
    path = _repo_root() / rel
    spec = importlib.util.spec_from_file_location(path.stem, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_miracl_seed_threads_hf_revision_into_list_and_download(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_script("scripts/seed_public_bench_miracl_zh_pool.py")

    captured: dict[str, object] = {"downloads": []}

    def fake_download(*, repo_id: str, repo_type: str, filename: str, revision: str | None = None, **_kwargs):
        captured["downloads"].append((repo_id, repo_type, filename, revision))
        return "/tmp/fake"

    class _FakeApi:
        def list_repo_files(self, repo_id: str, *, revision: str | None = None, repo_type: str | None = None, token=None):
            captured["list_repo_files"] = (repo_id, repo_type, revision)
            return ["miracl-corpus-v1.0-zh/docs-00000.jsonl.gz"]

    monkeypatch.setattr(mod, "hf_hub_download", fake_download, raising=True)
    monkeypatch.setattr(mod, "HfApi", lambda: _FakeApi(), raising=True)

    # These should accept revision and pass it through to hf_hub_download/HfApi.list_repo_files.
    mod._download_topics(split="train", revision="rev-topics")  # type: ignore[attr-defined]
    mod._download_qrels(split="train", revision="rev-qrels")  # type: ignore[attr-defined]
    files = mod._list_corpus_files(revision="rev-corpus")  # type: ignore[attr-defined]
    mod._download_corpus_files(files, revision="rev-corpus")  # type: ignore[attr-defined]

    assert captured["list_repo_files"] == ("miracl/miracl-corpus", "dataset", "rev-corpus")
    downloads = captured["downloads"]
    assert ("miracl/miracl", "dataset", "miracl-v1.0-zh/topics/topics.miracl-v1.0-zh-train.tsv", "rev-topics") in downloads
    assert ("miracl/miracl", "dataset", "miracl-v1.0-zh/qrels/qrels.miracl-v1.0-zh-train.tsv", "rev-qrels") in downloads
    assert ("miracl/miracl-corpus", "dataset", "miracl-corpus-v1.0-zh/docs-00000.jsonl.gz", "rev-corpus") in downloads


def test_cfever_seed_threads_hf_revision_into_list_and_download(monkeypatch: pytest.MonkeyPatch) -> None:
    mod = _load_script("scripts/seed_public_bench_cfever_dev.py")

    captured: dict[str, object] = {"downloads": []}

    def fake_download(*, repo_id: str, repo_type: str, filename: str, revision: str | None = None, **_kwargs):
        captured["downloads"].append((repo_id, repo_type, filename, revision))
        return "/tmp/fake"

    class _FakeApi:
        def list_repo_files(self, repo_id: str, *, revision: str | None = None, repo_type: str | None = None, token=None):
            captured["list_repo_files"] = (repo_id, repo_type, revision)
            return ["wiki-001.jsonl"]

    monkeypatch.setattr(mod, "hf_hub_download", fake_download, raising=True)
    monkeypatch.setattr(mod, "HfApi", lambda: _FakeApi(), raising=True)

    files = mod._list_wiki_files(revision="rev-wiki")  # type: ignore[attr-defined]
    mod._download_file("dev.jsonl", revision="rev-wiki")  # type: ignore[attr-defined]
    mod._download_file(files[0], revision="rev-wiki")  # type: ignore[attr-defined]

    assert captured["list_repo_files"] == ("IKMLab-team/cfever", "dataset", "rev-wiki")
    downloads = captured["downloads"]
    assert ("IKMLab-team/cfever", "dataset", "dev.jsonl", "rev-wiki") in downloads
    assert ("IKMLab-team/cfever", "dataset", "wiki-001.jsonl", "rev-wiki") in downloads
