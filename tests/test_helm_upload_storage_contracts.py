import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_default_and_production_shared_upload_mounts_require_multi_node_storage() -> None:
    for name in ("values.yaml", "examples/values-prod.yaml"):
        values = yaml.safe_load((ROOT / "deploy/helm/mimirq" / name).read_text(encoding="utf-8"))
        assert values["persistence"]["uploads"]["accessModes"] == ["ReadWriteMany"]


@pytest.mark.skipif(shutil.which("helm") is None, reason="helm is not installed")
@pytest.mark.parametrize(
    "overrides,valid",
    [
        ([], True),
        (["persistence.uploads.accessModes[0]=ReadWriteOnce"], False),
        (
            [
                "persistence.uploads.accessModes[0]=ReadWriteOnce",
                "secretEnv.MINIO_ENABLED=true",
                "secretEnv.MINIO_DOCUMENTS_ENABLED=true",
            ],
            False,
        ),
        (["worker.enabled=false", "persistence.uploads.accessModes[0]=ReadWriteOnce"], True),
        (["api.enabled=false", "persistence.uploads.accessModes[0]=ReadWriteOnce"], True),
        (
            [
                "worker.enabled=false",
                "api.autoscaling.enabled=true",
                "api.autoscaling.minReplicas=1",
                "api.autoscaling.maxReplicas=3",
                "persistence.uploads.accessModes[0]=ReadWriteOnce",
            ],
            False,
        ),
        (["persistence.uploads.enabled=false"], False),
        (
            [
                "persistence.uploads.enabled=false",
                "secretEnv.MINIO_ENABLED=true",
                "secretEnv.MINIO_DOCUMENTS_ENABLED=true",
            ],
            True,
        ),
    ],
)
def test_helm_validates_actual_shared_upload_consumers(overrides, valid) -> None:
    command = ["helm", "template", "mimirq", "deploy/helm/mimirq"]
    for override in overrides:
        flag = "--set-string" if override.startswith("secretEnv.") else "--set"
        command.extend([flag, override])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, check=False)
    assert (result.returncode == 0) is valid, result.stderr
    if not valid:
        assert "ReadWriteMany" in result.stderr, result.stderr
