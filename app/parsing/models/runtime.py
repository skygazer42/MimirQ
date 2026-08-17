import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.optional_deps import require_dependency
from app.parsing.models.hf_cache import download_hf_snapshot
from app.parsing.models.manifest import SmallModelManifest, SmallModelSpec, load_default_small_model_manifest

_DEFAULT_CPU_MODEL_LIMIT_MB = 500.0


def _onnx_gpu_enabled() -> bool:
    for name in ("PARSING_SMALL_MODELS_USE_GPU", "DEEPDOC_ONNX_USE_GPU"):
        if str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


@dataclass(frozen=True, slots=True)
class SmallModelStatus:
    task: str
    model_id: str
    kind: str
    available: bool
    optional: bool
    reason: str | None = None
    path: Path | None = None
    repo_id: str | None = None
    revision: str | None = None
    version: str | None = None
    size_mb: float | None = None
    elapsed_ms: int = 0

    def to_metadata(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "model_id": self.model_id,
            "kind": self.kind,
            "available": bool(self.available),
            "optional": bool(self.optional),
            "reason": self.reason,
            "path": str(self.path) if self.path is not None else None,
            "repo_id": self.repo_id,
            "revision": self.revision,
            "version": self.version or ("local" if self.available else "unresolved"),
            "size_mb": self.size_mb,
            "elapsed_ms": int(self.elapsed_ms),
        }


@dataclass(frozen=True, slots=True)
class LoadedSmallModel:
    task: str
    model_id: str
    kind: str
    available: bool
    handle: Any
    path: Path | None = None
    repo_id: str | None = None
    metadata: dict[str, Any] | None = None


class SmallModelRuntime:
    def __init__(self, *, manifest: SmallModelManifest | None = None) -> None:
        self.manifest = manifest or load_default_small_model_manifest()
        self._cache: dict[tuple[str, str], LoadedSmallModel] = {}

    def _spec(self, task: str, model_id: str | None = None) -> SmallModelSpec:
        if model_id:
            return self.manifest.get(task, model_id=model_id)
        return self.manifest.get_default(task)

    @staticmethod
    def _path_size_bytes(path: Path) -> int:
        if not path.exists():
            return 0
        if path.is_file():
            return int(path.stat().st_size)
        total = 0
        for item in path.rglob("*"):
            if item.is_file():
                total += int(item.stat().st_size)
        return total

    @staticmethod
    def _size_mb(size_bytes: int) -> float:
        return round(float(size_bytes) / (1024.0 * 1024.0), 3)

    def _cpu_rejection_reason(
        self, spec: SmallModelSpec, *, path: Path | None = None
    ) -> tuple[str | None, float | None]:
        if not spec.cpu_feasible:
            return "cpu_inference_not_supported", None
        limit_mb = float(spec.max_size_mb or _DEFAULT_CPU_MODEL_LIMIT_MB)
        estimated = spec.metadata.get("estimated_size_mb") if isinstance(spec.metadata, dict) else None
        try:
            estimated_mb = float(estimated) if estimated is not None else None
        except (TypeError, ValueError):
            estimated_mb = None
        if estimated_mb is not None and estimated_mb > limit_mb:
            return "model_too_large_for_cpu", round(estimated_mb, 3)
        if path is not None and path.exists():
            size_mb = self._size_mb(self._path_size_bytes(path))
            if size_mb > limit_mb:
                return "model_too_large_for_cpu", size_mb
            return None, size_mb
        return None, estimated_mb

    @staticmethod
    def _available_onnx_providers(ort: Any) -> list[str]:
        try:
            providers = ort.get_available_providers()
        except Exception:
            providers = []
        return [str(provider) for provider in providers or []]

    def _select_onnx_providers(self, spec: SmallModelSpec, ort: Any) -> list[str] | None:
        available = self._available_onnx_providers(ort)
        selected: list[str] = []
        gpu_enabled = _onnx_gpu_enabled()

        if gpu_enabled and spec.cpu_feasible and "CUDAExecutionProvider" in available:
            selected.append("CUDAExecutionProvider")
        if "CPUExecutionProvider" in available:
            selected.append("CPUExecutionProvider")

        for provider in spec.providers:
            if provider == "CUDAExecutionProvider" and not gpu_enabled:
                continue
            if provider in available and provider not in selected:
                selected.append(provider)
        if selected:
            return selected
        return list(spec.providers) if spec.providers else None

    @staticmethod
    def _cpu_provider_fallback(ort: Any) -> list[str] | None:
        available = SmallModelRuntime._available_onnx_providers(ort)
        if "CPUExecutionProvider" in available:
            return ["CPUExecutionProvider"]
        return None

    @staticmethod
    def _status(
        spec: SmallModelSpec,
        *,
        available: bool,
        optional: bool,
        version: str,
        elapsed_ms: int,
        reason: str | None = None,
        path: Path | None = None,
        repo_id: str | None = None,
        revision: str | None = None,
        size_mb: float | None = None,
    ) -> SmallModelStatus:
        return SmallModelStatus(
            task=spec.task,
            model_id=spec.model_id,
            kind=spec.kind,
            available=available,
            optional=optional,
            reason=reason,
            path=path,
            repo_id=repo_id,
            revision=revision,
            version=version,
            size_mb=size_mb,
            elapsed_ms=elapsed_ms,
        )

    def _resolve_onnx_status(
        self,
        spec: SmallModelSpec,
        *,
        version: str,
        elapsed_ms: int,
    ) -> SmallModelStatus:
        path = spec.resolved_path()
        if not path.exists():
            return self._status(
                spec,
                available=False,
                optional=spec.optional,
                reason="local_model_missing",
                path=path,
                version=version or "unresolved",
                elapsed_ms=elapsed_ms,
            )
        rejection_reason, size_mb = self._cpu_rejection_reason(spec, path=path)
        return self._status(
            spec,
            available=rejection_reason is None,
            optional=spec.optional,
            reason=rejection_reason,
            path=path,
            version=version or ("local" if rejection_reason is None else "unresolved"),
            size_mb=size_mb,
            elapsed_ms=elapsed_ms,
        )

    def _resolve_hf_status(
        self,
        spec: SmallModelSpec,
        *,
        version: str,
        elapsed_ms: int,
        allow_download: bool,
    ) -> SmallModelStatus:
        local_path = spec.resolved_path() if spec.path else None
        if local_path is not None and local_path.exists():
            rejection_reason, size_mb = self._cpu_rejection_reason(spec, path=local_path)
            return self._status(
                spec,
                available=rejection_reason is None,
                optional=spec.optional,
                reason=rejection_reason,
                path=local_path,
                repo_id=spec.repo_id,
                revision=spec.revision,
                version=version or ("local" if rejection_reason is None else "unresolved"),
                size_mb=size_mb,
                elapsed_ms=elapsed_ms,
            )
        rejection_reason, size_mb = self._cpu_rejection_reason(spec)
        if rejection_reason:
            return self._status(
                spec,
                available=False,
                optional=spec.optional,
                reason=rejection_reason,
                repo_id=spec.repo_id,
                revision=spec.revision,
                version=version or "unresolved",
                size_mb=size_mb,
                elapsed_ms=elapsed_ms,
            )
        if not allow_download:
            return self._status(
                spec,
                available=False,
                optional=spec.optional,
                reason="hf_download_disabled",
                repo_id=spec.repo_id,
                revision=spec.revision,
                version=version or "unresolved",
                elapsed_ms=elapsed_ms,
            )
        if not spec.repo_id:
            return self._status(
                spec,
                available=False,
                optional=spec.optional,
                reason="hf_repo_missing",
                version=version or "unresolved",
                elapsed_ms=elapsed_ms,
            )
        snapshot = download_hf_snapshot(repo_id=spec.repo_id, revision=spec.revision)
        rejection_reason, size_mb = self._cpu_rejection_reason(spec, path=snapshot.path)
        return self._status(
            spec,
            available=rejection_reason is None,
            optional=spec.optional,
            reason=rejection_reason,
            path=snapshot.path,
            repo_id=spec.repo_id,
            revision=spec.revision,
            version=version or ("downloaded" if rejection_reason is None else "unresolved"),
            size_mb=size_mb,
            elapsed_ms=elapsed_ms,
        )

    def resolve(self, task: str, *, model_id: str | None = None, allow_download: bool = False) -> SmallModelStatus:
        started = time.perf_counter()
        spec = self._spec(task, model_id=model_id)
        version = str(spec.metadata.get("version") or spec.revision or "").strip() or None

        def elapsed_ms() -> int:
            return max(0, int(round((time.perf_counter() - started) * 1000)))

        if spec.kind == "onnx":
            return self._resolve_onnx_status(spec, version=version or "", elapsed_ms=elapsed_ms())

        if spec.kind == "hf_transformers":
            return self._resolve_hf_status(
                spec,
                version=version or "",
                elapsed_ms=elapsed_ms(),
                allow_download=allow_download,
            )

        return self._status(
            spec,
            available=False,
            optional=spec.optional,
            reason="unsupported_model_kind",
            version=version or "unresolved",
            elapsed_ms=elapsed_ms(),
        )

    def load(self, task: str, *, model_id: str | None = None) -> LoadedSmallModel:
        spec = self._spec(task, model_id=model_id)
        cache_key = (spec.task, spec.model_id)
        if cache_key in self._cache:
            return self._cache[cache_key]

        status = self.resolve(spec.task, model_id=spec.model_id)
        if not status.available:
            raise RuntimeError(
                f"Small parsing model unavailable: task={spec.task} model={spec.model_id} reason={status.reason}"
            )

        if spec.kind == "onnx":
            ort = require_dependency("onnxruntime", feature="parsing_small_model_onnx", pip_name="onnxruntime")
            providers = self._select_onnx_providers(spec, ort)
            fallback_reason: str | None = None
            try:
                handle = ort.InferenceSession(str(status.path), providers=providers)  # type: ignore[attr-defined]
                selected_providers = providers
            except Exception as exc:
                cpu_providers = self._cpu_provider_fallback(ort)
                if not providers or "CUDAExecutionProvider" not in providers or not cpu_providers:
                    raise
                fallback_reason = str(exc)[:300]
                handle = ort.InferenceSession(str(status.path), providers=cpu_providers)  # type: ignore[attr-defined]
                selected_providers = cpu_providers
            metadata = spec.to_metadata()
            metadata["selected_providers"] = list(selected_providers) if selected_providers else None
            if fallback_reason:
                metadata["provider_fallback_reason"] = fallback_reason
            loaded = LoadedSmallModel(
                task=spec.task,
                model_id=spec.model_id,
                kind=spec.kind,
                available=True,
                path=status.path,
                repo_id=spec.repo_id,
                handle=handle,
                metadata=metadata,
            )
            self._cache[cache_key] = loaded
            return loaded

        raise RuntimeError(f"Loading HF transformers models is explicit-download only: {spec.task}.{spec.model_id}")


__all__ = ["LoadedSmallModel", "SmallModelRuntime", "SmallModelStatus"]
