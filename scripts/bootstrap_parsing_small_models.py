#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.parsing.models.hf_cache import HfSnapshotResult, download_hf_snapshot  # noqa: E402,F401
from app.parsing.models.manifest import SmallModelManifest, SmallModelSpec, load_small_model_manifest  # noqa: E402

_DEFAULT_MANIFEST = _REPO_ROOT / "configs" / "parsing_small_models.yaml"
_DEFAULT_OUTPUT_ROOT = _REPO_ROOT / "app" / "deepdoc" / "resources" / "models"
_SAFE_SLUG_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _slug(value: str) -> str:
    return _SAFE_SLUG_RE.sub("__", str(value or "").strip()).strip("_") or "model"


def _model_cache_name(spec: SmallModelSpec) -> str:
    return "__".join([_slug(spec.task), _slug(spec.model_id), _slug(spec.repo_id or spec.model_id)])


def _iter_hf_specs(
    manifest: SmallModelManifest,
    *,
    selections: list[str] | tuple[str, ...],
    all_optional: bool = False,
) -> list[SmallModelSpec]:
    if all_optional:
        out: list[SmallModelSpec] = []
        for task in manifest.tasks:
            out.extend([spec for spec in manifest.list_task_models(task) if spec.kind == "hf_transformers"])
        return out

    if not selections:
        raise ValueError("at least one --model task:model_id selection is required unless --all-optional is used")

    out = []
    for raw in selections:
        if ":" not in str(raw):
            raise ValueError(f"invalid model selection {raw!r}; expected task:model_id")
        task, model_id = str(raw).split(":", 1)
        spec = manifest.get(task.strip(), model_id=model_id.strip())
        if spec.kind != "hf_transformers":
            raise ValueError(f"selection {raw!r} is not a HuggingFace model")
        out.append(spec)
    return out


def _find_onnx_files(path: Path) -> list[Path]:
    if not path.exists():
        return []
    return sorted(p for p in path.rglob("*.onnx") if p.is_file())


def _cpu_skip_reason(spec: SmallModelSpec) -> str | None:
    if not spec.cpu_feasible:
        return "cpu_inference_not_supported"
    limit_mb = float(spec.max_size_mb or 500.0)
    estimated = spec.metadata.get("estimated_size_mb") if isinstance(spec.metadata, dict) else None
    try:
        estimated_mb = float(estimated) if estimated is not None else None
    except (TypeError, ValueError):
        estimated_mb = None
    if estimated_mb is not None and estimated_mb > limit_mb:
        return "model_too_large_for_cpu"
    return None


def _convert_transformers_to_onnx(
    *,
    spec: SmallModelSpec,
    snapshot_path: Path,
    onnx_path: Path,
    opset: int,
) -> dict[str, Any]:
    try:
        from optimum.exporters.onnx import main_export  # type: ignore
    except Exception as exc:  # noqa: BLE001
        main_export = None
        optimum_error = exc
    else:
        optimum_error = None

    out_dir = onnx_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    task = str(spec.pipeline_task or "auto").replace("_", "-")
    if main_export is not None:
        main_export(  # type: ignore[misc]
            model_name_or_path=str(snapshot_path),
            output=str(out_dir),
            task=task,
            opset=int(opset),
            device="cpu",
        )
        produced = _find_onnx_files(out_dir)
        if not produced:
            raise RuntimeError(f"ONNX conversion finished without an .onnx file for {spec.task}.{spec.model_id}")
        if produced[0] != onnx_path:
            shutil.copy2(produced[0], onnx_path)
        return {"backend": "optimum", "task": task, "opset": int(opset)}

    # Transformers' built-in ONNX exporter supports a smaller but useful set of
    # model families (for example DETR/Table Transformer). This keeps the table
    # model path real without requiring a new dependency in the default stack.
    try:
        from transformers import AutoConfig, AutoFeatureExtractor, AutoImageProcessor, AutoTokenizer  # type: ignore
        from transformers.onnx import FeaturesManager, export  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            "ONNX conversion requires either `optimum[onnxruntime]` or transformers' ONNX exporter."
        ) from exc

    config = AutoConfig.from_pretrained(str(snapshot_path))
    if str(getattr(config, "model_type", "") or "") == "table-transformer":
        import torch  # type: ignore
        from transformers import TableTransformerForObjectDetection  # type: ignore

        model = TableTransformerForObjectDetection.from_pretrained(str(snapshot_path))
        model.eval()
        dummy_pixel_values = torch.zeros((1, 3, 800, 800), dtype=torch.float32)
        with torch.no_grad():
            torch.onnx.export(
                model,
                (dummy_pixel_values,),
                str(onnx_path),
                input_names=["pixel_values"],
                output_names=["logits", "pred_boxes"],
                dynamic_axes={
                    "pixel_values": {0: "batch", 2: "height", 3: "width"},
                    "logits": {0: "batch"},
                    "pred_boxes": {0: "batch"},
                },
                opset_version=int(opset),
            )
        return {"backend": "torch.onnx", "task": task, "opset": int(opset), "model_type": "table-transformer"}

    supported = FeaturesManager.get_supported_features_for_model_type(str(config.model_type))
    if task == "auto" or task not in supported:
        task = "default" if "default" in supported else sorted(supported)[0]
    model_class = FeaturesManager.get_model_class_for_feature(task, framework="pt")
    model = model_class.from_pretrained(str(snapshot_path))
    onnx_config = FeaturesManager.get_config(str(config.model_type), task)(config)

    preprocessor = None
    for loader in (AutoImageProcessor, AutoFeatureExtractor, AutoTokenizer):
        try:
            preprocessor = loader.from_pretrained(str(snapshot_path))
            break
        except Exception:
            continue
    if preprocessor is None:
        raise RuntimeError(
            f"Cannot load tokenizer/image processor for ONNX conversion of {spec.task}.{spec.model_id}"
        ) from optimum_error

    export(
        preprocessor=preprocessor,
        model=model,
        config=onnx_config,
        opset=int(opset),
        output=onnx_path,
        device="cpu",
    )
    return {"backend": "transformers.onnx", "task": task, "opset": int(opset)}


def bootstrap_selected_models(
    *,
    manifest_path: str | Path = _DEFAULT_MANIFEST,
    selections: list[str] | tuple[str, ...] = (),
    output_root: str | Path = _DEFAULT_OUTPUT_ROOT,
    all_optional: bool = False,
    convert_onnx: bool = False,
    onnx_opset: int = 17,
) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    output_root = Path(output_root).resolve()
    manifest = load_small_model_manifest(manifest_path, base_dir=_REPO_ROOT)
    specs = _iter_hf_specs(manifest, selections=list(selections), all_optional=bool(all_optional))

    models: list[dict[str, Any]] = []
    downloaded = 0
    converted = 0
    for spec in specs:
        cpu_skip = _cpu_skip_reason(spec)
        if cpu_skip:
            models.append(
                {
                    "task": spec.task,
                    "model_id": spec.model_id,
                    "kind": spec.kind,
                    "repo_id": spec.repo_id,
                    "revision": spec.revision,
                    "status": "skipped",
                    "reason": cpu_skip,
                }
            )
            continue
        if not spec.repo_id:
            models.append(
                {
                    "task": spec.task,
                    "model_id": spec.model_id,
                    "kind": spec.kind,
                    "status": "skipped",
                    "reason": "hf_repo_missing",
                }
            )
            continue

        cache_name = _model_cache_name(spec)
        snapshot_dir = output_root / "hf" / cache_name
        snapshot = download_hf_snapshot(repo_id=spec.repo_id, revision=spec.revision, local_dir=snapshot_dir)
        downloaded += 1

        onnx_files = _find_onnx_files(snapshot.path)
        onnx_path = output_root / "hf_onnx" / cache_name / "model.onnx"
        conversion: dict[str, Any] | None = None
        conversion_error: str | None = None
        status = "downloaded"
        if convert_onnx and not onnx_files:
            try:
                conversion = _convert_transformers_to_onnx(
                    spec=spec,
                    snapshot_path=snapshot.path,
                    onnx_path=onnx_path,
                    opset=int(onnx_opset),
                )
            except Exception as exc:  # noqa: BLE001
                if not spec.optional:
                    raise
                conversion_error = str(exc)[:500]
                status = "downloaded_conversion_failed"
            else:
                converted += 1
                status = "downloaded_converted"
        elif onnx_files:
            onnx_path = onnx_files[0]
            status = "downloaded_with_onnx"

        models.append(
            {
                "task": spec.task,
                "model_id": spec.model_id,
                "kind": spec.kind,
                "repo_id": spec.repo_id,
                "revision": spec.revision,
                "status": status,
                "snapshot_path": str(snapshot.path),
                "onnx_path": str(onnx_path) if (onnx_files or conversion) else None,
                "conversion": conversion,
                "conversion_error": conversion_error,
            }
        )

    return {
        "schema": "mimirq.parsing_small_model_bootstrap.v1",
        "manifest_path": str(manifest_path),
        "output_root": str(output_root),
        "downloaded": int(downloaded),
        "converted": int(converted),
        "models": models,
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download explicitly selected parsing small models into project resources.")
    parser.add_argument(
        "--manifest",
        default=str(_DEFAULT_MANIFEST),
        help="Small-model manifest path. Defaults to configs/parsing_small_models.yaml.",
    )
    parser.add_argument(
        "--model",
        dest="models",
        action="append",
        default=[],
        help="Model selection in task:model_id form, for example table_structure:tatr_v1_1_all.",
    )
    parser.add_argument("--all-optional", action="store_true", help="Download every optional HuggingFace model in the manifest.")
    parser.add_argument(
        "--output-root",
        default=str(_DEFAULT_OUTPUT_ROOT),
        help="Project model resource root. Defaults to app/deepdoc/resources/models.",
    )
    parser.add_argument("--convert-onnx", action="store_true", help="Try ONNX conversion when the HF snapshot has no .onnx file.")
    parser.add_argument("--onnx-opset", type=int, default=17, help="ONNX opset used by optional conversion.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    result = bootstrap_selected_models(
        manifest_path=args.manifest,
        selections=list(args.models or []),
        output_root=args.output_root,
        all_optional=bool(args.all_optional),
        convert_onnx=bool(args.convert_onnx),
        onnx_opset=int(args.onnx_opset),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
