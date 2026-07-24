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
