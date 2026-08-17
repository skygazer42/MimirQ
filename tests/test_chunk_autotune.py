import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

import scripts.chunk_autotune as chunk_autotune

_BASE_PREVIEW_SUFFIX = (
    "/api/v1/documents/chunk-preview?chunk_size=1000&chunk_overlap=200&include_chunks=false&include_original_text=false"
)


def _preview_body(
    *,
    file_sha256: str | None = None,
    token_p50: int = 300,
    short_count: int = 1,
    long_count: int = 0,
    total_chunks: int = 10,
    overlap_waste_ratio: float = 0.2,
    coverage_ratio: float = 0.99,
) -> dict[str, Any]:
    middle_count = max(total_chunks - short_count - long_count, 0)
    return {
        "file_sha256": file_sha256,
        "chunking_stats_tokens": {
            "count": total_chunks,
            "median": token_p50,
            "histogram": [
                {"label": "0-50", "count": 0},
                {"label": "50-100", "count": short_count},
                {"label": "100-200", "count": middle_count},
                {"label": "800+", "count": long_count},
            ],
        },
        "stats": {
            "overlap_waste_ratio": overlap_waste_ratio,
            "coverage_ratio": coverage_ratio,
        },
        "total_chunks": total_chunks,
        "total_characters": total_chunks * 100,
    }


class _FakeResponse:
    def __init__(
        self,
        *,
        status_code: int,
        payload: dict[str, Any] | None = None,
        text: str = "",
    ) -> None:
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeClient:
    def __init__(
        self,
        *,
        get_responder: Any = None,
        post_responder: Any = None,
    ) -> None:
        self._get_responder = get_responder
        self._post_responder = post_responder
        self.get_calls: list[str] = []
        self.post_calls: list[dict[str, Any]] = []

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        self.get_calls.append(url)
        if self._get_responder is None:
            raise AssertionError(f"unexpected GET {url}")
        return self._get_responder(url)

    def post(
        self,
        url: str,
        *,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
    ) -> _FakeResponse:
        payload = {
            "url": url,
            "data": dict(data or {}),
            "files": files,
        }
        self.post_calls.append(payload)
        if self._post_responder is None:
            raise AssertionError(f"unexpected POST {url}")
        return self._post_responder(url, payload["data"], files)


def _install_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    get_responder: Any = None,
    post_responder: Any = None,
) -> dict[str, _FakeClient]:
    holder: dict[str, _FakeClient] = {}

    def _factory(*_args: object, **_kwargs: object) -> _FakeClient:
        client = _FakeClient(
            get_responder=get_responder,
            post_responder=post_responder,
        )
        holder["client"] = client
        return client

    monkeypatch.setattr(chunk_autotune.httpx, "Client", _factory)
    return holder


def _run_main(monkeypatch: pytest.MonkeyPatch, args: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["chunk_autotune.py", *args])
    chunk_autotune.main()


def test_score_uses_default_targets_and_reason_order() -> None:
    score, reasons = chunk_autotune._score(
        {
            "token_p50": 150,
            "short_pct": 25,
            "long_pct": 20,
            "overlap_waste_pct": 40,
            "coverage_pct": 95,
            "total_chunks": 10_001,
        },
        chunk_autotune._default_targets(),
    )

    assert score == 3_485
    assert reasons == [
        "token_p50_too_small",
        "short_pct_warn",
        "long_pct_fail",
        "overlap_waste_warn",
        "coverage_warn",
        "too_many_chunks",
    ]


def test_score_is_zero_when_metrics_fit_default_targets() -> None:
    score, reasons = chunk_autotune._score(
        {
            "token_p50": 300,
            "short_pct": 10,
            "long_pct": 5,
            "overlap_waste_pct": 20,
            "coverage_pct": 99,
            "total_chunks": 100,
        },
        chunk_autotune._default_targets(),
    )

    assert score == 0
    assert reasons == []


def test_main_uses_defaults_and_writes_default_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("sample body", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    sha = "a" * 64

    def _post_responder(url: str, data: dict[str, Any], files: dict[str, Any] | None) -> _FakeResponse:
        if url.endswith(_BASE_PREVIEW_SUFFIX):
            assert data["parser_backend"] == "auto"
            assert data["chunk_strategy"] == "langchain_recursive"
            assert files is not None
            assert files["file"][0] == "sample.txt"
            return _FakeResponse(status_code=200, payload=_preview_body(file_sha256=sha, token_p50=320))
        if "/api/v1/documents/chunk-preview/by-sha?" in url:
            assert data["file_sha256"] == sha
            assert data["parser_backend"] == "auto"
            return _FakeResponse(status_code=200, payload=_preview_body(token_p50=320))
        raise AssertionError(f"unexpected POST {url}")

    holder = _install_client(monkeypatch, post_responder=_post_responder)

    result = _run_main(monkeypatch, ["--file", str(sample)])

    assert result is None
    client = holder["client"]
    assert client.get_calls == []
    assert len(client.post_calls) == 61

    out_dir = tmp_path / "chunk_autotune_out"
    assert sorted(path.name for path in out_dir.iterdir()) == [
        "diff.json",
        "leaderboard.json",
        "preset_patch.json",
        "targets.json",
    ]

    targets = json.loads((out_dir / "targets.json").read_text(encoding="utf-8"))
    leaderboard = json.loads((out_dir / "leaderboard.json").read_text(encoding="utf-8"))
    preset_patch = json.loads((out_dir / "preset_patch.json").read_text(encoding="utf-8"))
    diff = json.loads((out_dir / "diff.json").read_text(encoding="utf-8"))

    assert targets == chunk_autotune._default_targets()
    assert leaderboard["targets"] == targets
    assert len(leaderboard["rows"]) == 60
    assert set(leaderboard["rows"][0]) == {
        "candidate",
        "http_status",
        "metrics",
        "rank",
        "score",
        "score_reasons",
    }
    assert preset_patch["pipeline"]["chunk_size"] == leaderboard["rows"][0]["candidate"]["chunk_size"]
    assert preset_patch["pipeline"]["chunk_overlap"] == leaderboard["rows"][0]["candidate"]["chunk_overlap"]
    assert diff["base"]["candidate"] == {
        "chunk_strategy": "langchain_recursive",
        "chunk_size": 1000,
        "chunk_overlap": 200,
    }
    assert diff["best"]["candidate"] == leaderboard["rows"][0]["candidate"]
    assert diff["targets"] == targets

    stdout_lines = capsys.readouterr().out.strip().splitlines()
    assert stdout_lines[0].startswith("[chunk_autotune] upload ok sha=aaaaaaaaaa")
    assert stdout_lines[-1] == "[chunk_autotune] done. candidates=60 best_score=0 out_dir=chunk_autotune_out"


def test_main_preserves_current_zero_score_and_http_error_ranking_behavior(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("sample body", encoding="utf-8")
    out_dir = tmp_path / "out"
    sha = "b" * 64

    def _post_responder(url: str, data: dict[str, Any], files: dict[str, Any] | None) -> _FakeResponse:
        if url.endswith(_BASE_PREVIEW_SUFFIX):
            return _FakeResponse(status_code=200, payload=_preview_body(file_sha256=sha))
        if "/api/v1/documents/chunk-preview/by-sha?" not in url:
            raise AssertionError(f"unexpected POST {url}")

        strategy = str(data["chunk_strategy"])
        if strategy == "markdown_header":
            return _FakeResponse(status_code=503, text="upstream unavailable")

        query = parse_qs(urlparse(url).query)
        assert query["chunk_size"] == ["200"]
        assert query["chunk_overlap"] == ["20"]
        assert files is None
        return _FakeResponse(status_code=200, payload=_preview_body(token_p50=300))

    _install_client(monkeypatch, post_responder=_post_responder)

    result = _run_main(
        monkeypatch,
        [
            "--file",
            str(sample),
            "--out-dir",
            str(out_dir),
            "--strategies",
            "outline,langchain_recursive,markdown_header",
            "--chunk-sizes",
            "200",
            "--overlap-ratios",
            "0.1",
        ],
    )

    assert result is None

    leaderboard = json.loads((out_dir / "leaderboard.json").read_text(encoding="utf-8"))
    rows = leaderboard["rows"]
    assert [row["rank"] for row in rows] == [1, 2, 3]
    assert [row["candidate"]["chunk_strategy"] for row in rows] == [
        "langchain_recursive",
        "markdown_header",
        "outline",
    ]
    assert rows[0]["score"] == 0
    assert rows[1]["score"] == 9_999_999
    assert rows[1]["score_reasons"] == ["http_error"]
    assert rows[1]["http_status"] == 503
    assert rows[1]["http_error"] == "upstream unavailable"
    assert rows[2]["score"] == 0

    preset_patch = json.loads((out_dir / "preset_patch.json").read_text(encoding="utf-8"))
    assert preset_patch == {
        "default_chunk_strategy": "langchain_recursive",
        "pipeline": {"chunk_size": 200, "chunk_overlap": 20},
        "chunk_targets_v2": chunk_autotune._default_targets(),
    }

    stdout_lines = capsys.readouterr().out.strip().splitlines()
    assert len(stdout_lines) == 2
    assert stdout_lines[0].startswith("[chunk_autotune] upload ok sha=bbbbbbbbbb")
    assert stdout_lines[1] == f"[chunk_autotune] done. candidates=3 best_score=0 out_dir={out_dir}"


def test_main_exits_with_code_two_when_upload_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    sample = tmp_path / "sample.txt"
    sample.write_text("sample body", encoding="utf-8")

    def _post_responder(_url: str, _data: dict[str, Any], _files: dict[str, Any] | None) -> _FakeResponse:
        return _FakeResponse(status_code=502, text="bad gateway")

    _install_client(monkeypatch, post_responder=_post_responder)

    with pytest.raises(SystemExit) as exc_info:
        _run_main(monkeypatch, ["--file", str(sample)])

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.strip() == "[chunk_autotune] ERROR: chunk-preview upload failed: 502 bad gateway"
