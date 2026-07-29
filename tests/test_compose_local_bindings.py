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


def test_web_compose_uses_docker_scoped_api_env_vars_with_same_origin_default() -> None:
    web = _compose("docker/docker-compose.web.yml")["services"]["web"]

    assert web["build"]["args"]["NEXT_PUBLIC_API_URL"] == "${NEXT_PUBLIC_API_URL_DOCKER:-/}"
    assert web["build"]["args"]["NEXT_PUBLIC_ADMIN_CONTACT_URL"] == (
        "${NEXT_PUBLIC_ADMIN_CONTACT_URL:-https://github.com/skygazer42/MimirQ/issues}"
    )
    assert web["build"]["args"]["API_INTERNAL_URL"] == "${API_INTERNAL_URL_DOCKER:-http://mimirq-api:8000}"
    assert web["environment"]["NEXT_PUBLIC_API_URL"] == "${NEXT_PUBLIC_API_URL_DOCKER:-/}"
    assert web["environment"]["NEXT_PUBLIC_ADMIN_CONTACT_URL"] == (
        "${NEXT_PUBLIC_ADMIN_CONTACT_URL:-https://github.com/skygazer42/MimirQ/issues}"
    )
    assert web["environment"]["API_INTERNAL_URL"] == "${API_INTERNAL_URL_DOCKER:-http://mimirq-api:8000}"


def test_worker_compose_healthcheck_uses_lightweight_arq_check() -> None:
    for path in ("docker/docker-compose.yml", "docker/docker-compose.lite.yml"):
        worker = _compose(path)["services"]["mimirq-worker"]
        assert worker["healthcheck"]["test"] == [
            "CMD",
            "arq",
            "--check",
            "app.tasks.queue.WorkerHealthSettings",
        ]
        assert worker["healthcheck"]["start_period"] == "${WORKER_HEALTHCHECK_START_PERIOD:-45s}"
