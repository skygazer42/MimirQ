from pathlib import Path

from scripts.docs import generate_fe_be_matrix


def test_extract_ts_paths_excludes_test_modules(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    (tmp_path / "datasets.ts").write_text(
        'const path = "/api/v1/datasets"\n',
        encoding="utf-8",
    )
    (tmp_path / "datasets.pagination.test.ts").write_text(
        "const path = '/api/v1/datasets'\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(generate_fe_be_matrix, "WEB_LIB_API", tmp_path)

    assert generate_fe_be_matrix.extract_ts_paths() == {
        "datasets.ts": ["/api/v1/datasets"],
    }
