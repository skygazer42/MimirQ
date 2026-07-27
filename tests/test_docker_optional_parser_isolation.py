from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_backend_image_does_not_mix_magicpdf_dependencies() -> None:
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    magicpdf_dockerfile = (REPO_ROOT / "docker" / "magicpdf" / "Dockerfile").read_text(encoding="utf-8")

    assert "magic-pdf==" not in dockerfile
    assert '"magic-pdf[full]==1.3.12"' in magicpdf_dockerfile


def test_backend_build_context_excludes_local_model_cache() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()

    assert "app/deepdoc/resources/models/" in {line.strip() for line in dockerignore}
