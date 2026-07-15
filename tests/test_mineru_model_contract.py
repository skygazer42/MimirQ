import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_start_local_api():
    path = ROOT / "docker" / "mineru" / "start_local_api.py"
    spec = importlib.util.spec_from_file_location("mimirq_mineru_start_local_api_test", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_mineru_image_pins_the_validated_runtime_version():
    dockerfile = (ROOT / "docker" / "mineru" / "Dockerfile").read_text(encoding="utf-8")

    assert 'ARG MINERU_PIP_SPEC="mineru[core]==3.4.4"' in dockerfile


def test_pipeline_readiness_requires_current_ocr_models(tmp_path, monkeypatch):
    startup = _load_start_local_api()
    legacy_model = tmp_path / "models/OCR/paddleocr_torch/ch_PP-OCRv4_rec_server_doc_infer.pth"
    legacy_model.parent.mkdir(parents=True)
    legacy_model.touch()
    monkeypatch.setattr(startup, "_candidate_model_roots", lambda _model_type: [tmp_path])

    assert startup._required_files_ready("pipeline") is False

    expected = {
        "models/OCR/paddleocr_torch/ch_PP-OCRv6_small_det_infer.safetensors",
        "models/OCR/paddleocr_torch/ch_PP-OCRv6_small_rec_infer.safetensors",
        "models/MFR/pp_formulanet_plus_m/PP-FormulaNet_plus-M.pth",
    }
    assert expected.issubset(set(startup.PIPELINE_REQUIRED_FILES))
    for relative_path in startup.PIPELINE_REQUIRED_FILES:
        path = tmp_path / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    assert startup._required_files_ready("pipeline") is True


def test_vlm_discovery_uses_the_runtime_model_repository(tmp_path, monkeypatch):
    startup = _load_start_local_api()
    monkeypatch.setenv("HOME", str(tmp_path))
    snapshot = (
        tmp_path
        / ".cache/huggingface/hub/models--opendatalab--MinerU2.5-Pro-2605-1.2B/snapshots/revision"
    )
    snapshot.mkdir(parents=True)
    for relative_path in startup.VLM_REQUIRED_FILES:
        (snapshot / relative_path).touch()

    assert "model.safetensors" in startup.VLM_REQUIRED_FILES
    assert startup._discover_local_model_dirs()["vlm"] == str(snapshot)
