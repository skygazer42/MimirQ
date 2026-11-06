import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _requirement_versions(filename: str = "requirements.txt") -> dict[str, str]:
    versions: dict[str, str] = {}
    for raw_line in ROOT.joinpath(filename).read_text(encoding="utf-8").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or line.startswith("-") or "==" not in line:
            continue
        name, version = line.split("==", 1)
        package = name.split("[", 1)[0].strip().lower()
        versions[package] = version.split(";", 1)[0].strip()
    return versions


def test_audit_remediation_pins_known_fixed_versions() -> None:
    versions = _requirement_versions()
    assert {
        "torch",
        "torchvision",
        "sentence-transformers",
        "accelerate",
        "hanlp",
        "chromadb",
        "langchain-chroma",
        "faiss-cpu",
        "rank-bm25",
    }.isdisjoint(versions)
    assert versions["nltk"] == "3.10.2"
    assert not ROOT.joinpath("requirements-local-models.txt").exists()
    assert _requirement_versions("requirements-chroma.txt")["chromadb"] == "1.5.7"
    assert _requirement_versions("requirements-faiss.txt")["faiss-cpu"] == "1.13.2"


def test_unused_direct_dependencies_stay_removed() -> None:
    versions = _requirement_versions()
    assert {"grpcio-tools", "roman-numbers", "backports.tarfile"}.isdisjoint(versions)


def test_langchain_milvus_imports_stay_isolated_to_adapter_boundaries() -> None:
    matches: list[str] = []
    for path in ROOT.joinpath("app").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module != "langchain_community.vectorstores":
                continue
            if any(alias.name == "Milvus" for alias in node.names):
                matches.append(path.relative_to(ROOT).as_posix())
                break

    assert matches == ["app/storage/vector/milvus.py"]
