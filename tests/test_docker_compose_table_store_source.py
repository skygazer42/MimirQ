from pathlib import Path


def test_docker_compose_overrides_table_store_dir_to_shared_upload_volume() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    compose_paths = [
        repo_root / "docker" / "docker-compose.yml",
        repo_root / "docker" / "docker-compose.lite.yml",
        repo_root / "docker" / "docker-compose.retrieval-dev.yml",
    ]

    for compose_path in compose_paths:
        text = compose_path.read_text(encoding="utf-8")
        assert "TABLE_STORE_DIR: /data/uploads/table_store" in text, compose_path.name
