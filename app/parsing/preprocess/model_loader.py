"""
Model loader scaffolding for document/image preprocessing.

This module intentionally keeps the core backend free of heavyweight ML deps.
It provides a thin optional-dependency wrapper that can be used by deployments
that choose to run DocTr/LaMa/etc in-process.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.core.optional_deps import require_dependency

if TYPE_CHECKING:
    from onnxruntime import InferenceSession


@dataclass(frozen=True, slots=True)
class LoadedModel:
    name: str
    backend: str
    handle: InferenceSession


def positive_onnx_dimension(value: Any) -> int | None:
    try:
        number = int(value)
    except Exception:
        return None
    return number if number > 0 else None


class PreprocessModelLoader:
    """
    Minimal singleton-style loader for optional preprocessing models.

    - Uses lazy imports and caches loaded handles.
    - Does not enforce any particular model layout; callers provide model ids/paths.
    """

    def __init__(self) -> None:
        self._cache: dict[str, LoadedModel] = {}

    def load_onnx(self, *, name: str, model_path: str) -> LoadedModel:
        key = f"onnx::{name}::{model_path}"
        if key in self._cache:
            return self._cache[key]

        ort = require_dependency("onnxruntime", feature="preprocess_onnxruntime", pip_name="onnxruntime")
        sess = ort.InferenceSession(model_path)  # type: ignore[attr-defined]
        loaded = LoadedModel(name=name, backend="onnxruntime", handle=sess)
        self._cache[key] = loaded
        return loaded


_LOADER: PreprocessModelLoader | None = None


def get_preprocess_model_loader() -> PreprocessModelLoader:
    global _LOADER
    if _LOADER is None:
        _LOADER = PreprocessModelLoader()
    return _LOADER


__all__ = ["LoadedModel", "PreprocessModelLoader", "get_preprocess_model_loader", "positive_onnx_dimension"]
