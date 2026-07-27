import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def _read(rel_path: str) -> str:
    return (ROOT / rel_path).read_text(encoding="utf-8")


def _yaml(rel_path: str) -> dict:
    return yaml.safe_load(_read(rel_path))


def test_semantic_cache_retention_defaults_stay_safe_and_bounded() -> None:
    values = _yaml("deploy/helm/mimirq/values.yaml")

    cron = values["cronjobs"]["semanticCacheRetention"]
    assert cron["enabled"] is False
    assert cron["execute"] is True
    assert cron["allTenants"] is False
    assert cron["tenantId"] == ""
    assert int(cron["maxScan"]) == 1000
    assert int(cron["maxDelete"]) == 100


def test_semantic_cache_retention_prod_example_closes_the_loop() -> None:
    values = _yaml("deploy/helm/mimirq/examples/values-prod.yaml")

    api_extra_env = {str(item["name"]): str(item["value"]).lower() for item in values["api"]["extraEnv"]}
    worker_extra_env = {str(item["name"]): str(item["value"]).lower() for item in values["worker"]["extraEnv"]}
    assert api_extra_env["SEMANTIC_CACHE_ENABLED"] == "true"
    assert worker_extra_env["SEMANTIC_CACHE_ENABLED"] == "true"

    cron = values["cronjobs"]["semanticCacheRetention"]
    assert cron["enabled"] is True
    assert cron["allTenants"] is True
    assert cron["execute"] is True
    assert int(cron["maxScan"]) == 1000
    assert int(cron["maxDelete"]) == 100


def test_semantic_cache_retention_template_and_schema_expose_expected_knobs() -> None:
    template = _read("deploy/helm/mimirq/templates/cronjob-semantic-cache-retention.yaml")
    assert "scripts/run_retention_jobs.py" in template
    assert "--semantic-cache" in template
    assert "--all-tenants" in template
    assert "--tenant-id" in template
    assert "--execute" in template
    assert "--dry-run" in template
    assert "--max-scan" in template
    assert "--max-delete" in template
    assert 'include "mimirq.secretName"' in template
    assert 'include "mimirq.serviceAccountNameBlock"' in template

    schema = json.loads(_read("deploy/helm/mimirq/values.schema.json"))
    props = schema["properties"]["cronjobs"]["properties"]["semanticCacheRetention"]["properties"]
    for key in ("enabled", "schedule", "allTenants", "tenantId", "execute", "maxScan", "maxDelete"):
        assert key in props


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
def test_helm_template_renders_semantic_cache_retention_cronjob_from_prod_values() -> None:
    result = subprocess.run(
        [
            "helm",
            "template",
            "mimirq",
            "deploy/helm/mimirq",
            "-n",
            "mimirq",
            "-f",
            "deploy/helm/mimirq/examples/values-prod.yaml",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )

    docs = [doc for doc in yaml.safe_load_all(result.stdout) if isinstance(doc, dict)]
    cronjob = next(
        doc
        for doc in docs
        if doc.get("kind") == "CronJob" and doc.get("metadata", {}).get("name") == "mimirq-semantic-cache-retention"
    )
    container = cronjob["spec"]["jobTemplate"]["spec"]["template"]["spec"]["containers"][0]
    assert cronjob["spec"]["schedule"] == "17 * * * *"
    assert container["command"] == [
        "python",
        "scripts/run_retention_jobs.py",
        "--semantic-cache",
        "--all-tenants",
        "--execute",
        "--max-scan",
        "1000",
        "--max-delete",
        "100",
    ]
    assert container["envFrom"] == [{"secretRef": {"name": "mimirq-env"}}]
