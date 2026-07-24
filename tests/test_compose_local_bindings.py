from pathlib import Path

import yaml


def _compose(path: str) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def test_infrastructure_host_ports_bind_to_loopback() -> None:
    services = _compose("docker/docker-compose.infra.yml")["services"]

    assert services["mimirq-postgres"]["ports"] == ["127.0.0.1:5432:5432"]
    assert services["mimirq-redis"]["ports"] == ["127.0.0.1:6379:6379"]
    assert services["mimirq-minio"]["ports"] == [
        "127.0.0.1:9001:9001",
        "127.0.0.1:9000:9000",
    ]
    assert services["mimirq-milvus"]["ports"] == [
        "127.0.0.1:19530:19530",
        "127.0.0.1:9091:9091",
    ]


def test_retrieval_dev_api_binds_to_loopback() -> None:
    api = _compose("docker/docker-compose.retrieval-dev.yml")["services"]["mimirq-api"]

    assert api["ports"] == ["127.0.0.1:${BACKEND_PORT:-8000}:8000"]


def test_local_chroma_volume_uses_image_owned_directory() -> None:
    retrieval = _compose("docker/docker-compose.retrieval-dev.yml")
    lite = _compose("docker/docker-compose.lite.yml")

    assert retrieval["x-backend-env"]["CHROMA_PERSIST_PATH"] == "${CHROMA_PERSIST_PATH_DOCKER:-/app/vector_chroma}"
    assert retrieval["services"]["mimirq-api"]["volumes"] == [
        "upload_data:/data/uploads",
        "vector_data:/app/vector_chroma",
    ]
    assert lite["x-backend-env"]["CHROMA_PERSIST_PATH"] == "${CHROMA_PERSIST_PATH_DOCKER:-/app/vector_chroma}"
    assert "vector_data:/app/vector_chroma" in lite["services"]["mimirq-api"]["volumes"]
    assert "vector_data:/app/vector_chroma" in lite["services"]["mimirq-worker"]["volumes"]
