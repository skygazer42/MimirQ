from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_backend_image_does_not_mix_magicpdf_dependencies() -> None:
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile").read_text(encoding="utf-8")
    magicpdf_dockerfile = (REPO_ROOT / "docker" / "magicpdf" / "Dockerfile").read_text(encoding="utf-8")

    assert "magic-pdf==" not in dockerfile
    assert '"magic-pdf[full]==1.3.12"' in magicpdf_dockerfile


def test_backend_build_context_excludes_local_model_cache() -> None:
    dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    entries = {line.strip() for line in dockerignore}

    assert "app/deepdoc/resources/models/" in entries
    for entry in ("docs-site/", "work/", ".tmp/", ".playwright-cli/", ".playwright-mcp/"):
        assert entry in entries
    for required_runtime_dir in (
        "app/deepdoc/resources/data_parser/",
        "app/deepdoc/resources/nltk_data/",
        "app/deepdoc/resources/tiktoken/",
    ):
        assert required_runtime_dir not in entries
