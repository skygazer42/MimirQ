from __future__ import annotations

import ast
import hashlib
import importlib
import importlib.util
import json
import re
import shutil
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import lru_cache, wraps
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.rag.pipeline_plugins.contracts import (
    PipelinePluginContractError,
    summarize_contracts,
    validate_golden_rules_metadata_fields,
    validate_retrieval_policy_metadata_fields,
    validate_retrieval_text_schema_metadata_fields,
)
from app.services.pipeline_patch_validator import normalize_document_pipeline_patch

try:
    import yaml
except Exception:  # pragma: no cover - JSON manifests remain supported without PyYAML.
    yaml = None  # type: ignore[assignment]

PLUGIN_MANIFEST_FILENAMES = (
    "mimirq-plugin.json",
    "plugin.json",
    "mimirq-plugin.yaml",
    "mimirq-plugin.yml",
    "plugin.yaml",
    "plugin.yml",
)
PLUGIN_TEST_REPORT_FILENAME = ".mimirq-plugin-test.json"
_PLUGIN_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_PLUGIN_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,31}$")
_ENTRY_FUNCTION_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REGISTERED_PLUGIN_REF_RE = re.compile(
    r"^plugin:(?P<plugin_id>[a-z0-9][a-z0-9_.-]{0,63})@(?P<version>[A-Za-z0-9][A-Za-z0-9_.+-]{0,31}):(?P<stage>governance|chunk|kg)$"
)
_SUPPORTED_ENTRY_STAGES = ("governance", "chunk", "kg")
_SUPPORTED_MANIFEST_FIELDS = {
    "id",
    "version",
    "name",
    "description",
    "status",
    "entry",
    "metadata_schema",
    "retrieval_text_schema",
    "golden_rules",
    "retrieval_policy",
    "processing_templates",
    "suggested_pipeline_patch",
}
_SUPPORTED_CONTRACT_FIELDS = {
    "metadata_schema": {"schema", "fields", "record_identity"},
    "retrieval_text_schema": {"schema", "stages"},
    "golden_rules": {
        "schema",
        "expected_metadata",
        "answer_key_point_fields",
        "template_selector_fields",
        "tag_fields",
        "query_templates",
    },
    "retrieval_policy": {
        "schema",
        "query_expansion_fields",
        "query_expansion_values",
        "filter_fields",
        "boost_fields",
        "anchor_fields",
        "rerank_features",
        "fallback",
        "response_compaction",
    },
    "processing_templates": {"schema", "plugin_id", "version", "description", "templates"},
}
_PLUGIN_DOC_FILENAMES = {
    "changelog.md",
    "license",
    "license.md",
    "readme",
    "readme.md",
}
_PLUGIN_SUGGESTED_PATCH_ALLOWED_GOVERNANCE_FIELDS = {
    "governance_enabled",
    "governance_python_params",
    "governance_python_plugin",
}
_PLUGIN_SUGGESTED_PATCH_ALLOWED_FIELDS = {
    "governance_enabled",
    "governance_python_params",
    "chunk_python_params",
    "kg_python_params",
    "persist_parsed_content",
}
_PLUGIN_SUGGESTED_PATCH_FORBIDDEN_STRATEGY_FIELDS = {
    "chunk_size",
    "chunk_overlap",
    "chunk_merge_small_min_chars",
    "chunk_strategy_params",
}
_RESERVED_ENTRY_MODULE_ROOTS = {"app", "scripts", "tests"}
_PROCESSING_TEMPLATE_FIELDS = {"key", "name", "description", "stage", "implemented_by", "related_implementations"}
_PROCESSING_TEMPLATE_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,127}$")
_PLUGIN_IMPORT_LOCK = threading.RLock()


class PipelinePluginRegistryError(RuntimeError):
    """Raised when a registered pipeline plugin cannot be listed or loaded."""


@dataclass(frozen=True)
class PipelinePluginEntry:
    stage: str
    target: str


@dataclass(frozen=True)
class PipelinePluginDescriptor:
    id: str
    version: str
    name: str
    description: str
    published: bool
    executable: bool
    test_status: str
    plugin_dir: Path
    manifest_path: Path
    package_hash: str
    test_report: dict[str, Any] = field(default_factory=dict)
    entries: dict[str, PipelinePluginEntry] = field(default_factory=dict)
    refs: dict[str, str] = field(default_factory=dict)
    metadata_schema: dict[str, Any] = field(default_factory=dict)
    retrieval_text_schema: dict[str, Any] = field(default_factory=dict)
    golden_rules: dict[str, Any] = field(default_factory=dict)
    retrieval_policy: dict[str, Any] = field(default_factory=dict)
    processing_templates: dict[str, Any] = field(default_factory=dict)
    contract_summary: dict[str, Any] = field(default_factory=dict)
    suggested_pipeline_patch: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelinePluginDiscoveryError:
    plugin_dir: Path
    manifest_path: Path | None
    error: str


def is_registered_plugin_ref(plugin_ref: str) -> bool:
    return bool(_REGISTERED_PLUGIN_REF_RE.fullmatch(str(plugin_ref or "").strip()))


def parse_registered_plugin_ref(plugin_ref: str) -> tuple[str, str, str]:
    match = _REGISTERED_PLUGIN_REF_RE.fullmatch(str(plugin_ref or "").strip())
    if not match:
        raise PipelinePluginRegistryError("registered plugin ref must be plugin:<id>@<version>:<stage>")
    return match.group("plugin_id"), match.group("version"), match.group("stage")


def derive_registered_stage_plugin_ref(
    plugin_ref: str,
    target_stage: str,
    *,
    directories: list[str | Path] | None = None,
    require_test_report: bool | None = None,
) -> str:
    """Return the same plugin/version ref for another stage if the descriptor declares it."""
    stage = str(target_stage or "").strip()
    if stage not in {"governance", "chunk", "kg"}:
        return ""
    if not is_registered_plugin_ref(plugin_ref):
        return ""
    try:
        plugin_id, version, _source_stage = parse_registered_plugin_ref(plugin_ref)
        candidate = f"plugin:{plugin_id}@{version}:{stage}"
        descriptor = resolve_registered_plugin_descriptor(
            candidate,
            directories=directories,
            require_test_report=require_test_report,
        )
    except PipelinePluginRegistryError:
        return ""
    return candidate if stage in descriptor.entries else ""


def default_plugin_directories() -> list[Path]:
    raw = str(getattr(settings, "PYTHON_PIPELINE_PLUGIN_DIRS", "") or "").strip()
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return [Path(p).expanduser() for p in parts]


def _find_manifest(plugin_dir: Path) -> Path | None:
    for name in PLUGIN_MANIFEST_FILENAMES:
        candidate = plugin_dir / name
        if candidate.is_file():
            return candidate
    return None


def _candidate_plugin_dirs(root: Path) -> list[Path]:
    resolved = root.expanduser()
    if _find_manifest(resolved):
        return [resolved]
    if not resolved.is_dir():
        return []
    return sorted(p for p in resolved.iterdir() if p.is_dir() and _find_manifest(p))


def _load_manifest(manifest_path: Path) -> dict[str, Any]:
    suffix = manifest_path.suffix.lower()
    text = manifest_path.read_text(encoding="utf-8")
    if suffix == ".json":
        raw = json.loads(text)
    elif suffix in {".yaml", ".yml"}:
        if yaml is None:
            raise PipelinePluginRegistryError("YAML plugin manifests require PyYAML")
        raw = yaml.safe_load(text) or {}
    else:
        raise PipelinePluginRegistryError(f"unsupported plugin manifest suffix: {suffix}")
    if not isinstance(raw, dict):
        raise PipelinePluginRegistryError("plugin manifest must be an object")
    unknown = sorted(str(key or "").strip() or "<empty>" for key in raw if str(key or "").strip() not in _SUPPORTED_MANIFEST_FIELDS)
    if unknown:
        raise PipelinePluginRegistryError(f"plugin manifest contains unknown top-level fields: {', '.join(unknown[:20])}")
    return raw


def _validate_manifest_text(value: Any, *, field_name: str, pattern: re.Pattern[str]) -> str:
    text = str(value or "").strip()
    if not text or not pattern.fullmatch(text):
        raise PipelinePluginRegistryError(f"plugin manifest field '{field_name}' is invalid")
    return text


def _manifest_entries(raw: dict[str, Any]) -> dict[str, PipelinePluginEntry]:
    entry = raw.get("entry")
    if not isinstance(entry, dict):
        raise PipelinePluginRegistryError("plugin manifest must define entry object")
    unsupported = sorted(str(stage or "").strip() or "<empty>" for stage in entry if str(stage or "").strip() not in _SUPPORTED_ENTRY_STAGES)
    if unsupported:
        raise PipelinePluginRegistryError(f"plugin manifest entry contains unsupported stages: {', '.join(unsupported[:20])}")
    out: dict[str, PipelinePluginEntry] = {}
    for stage in _SUPPORTED_ENTRY_STAGES:
        raw_target = entry.get(stage)
        if raw_target is None:
            continue
        if not isinstance(raw_target, str):
            raise PipelinePluginRegistryError(f"plugin entry for {stage} must be a string module target")
        target = raw_target.strip()
        if not target:
            continue
        if "\x00" in target or target.startswith("/") or "\\" in target:
            raise PipelinePluginRegistryError(f"plugin entry for {stage} must be a relative module target")
        if ":" not in target:
            raise PipelinePluginRegistryError(f"plugin entry for {stage} must be module.py:function or module:function")
        _module_part, _, function_name = target.partition(":")
        if not _ENTRY_FUNCTION_RE.fullmatch(function_name):
            raise PipelinePluginRegistryError(f"plugin entry for {stage} must include a callable function name")
        out[stage] = PipelinePluginEntry(stage=stage, target=target)
    if not out:
        raise PipelinePluginRegistryError("plugin manifest must define at least one governance, chunk, or kg entry")
    return out


def _manifest_contract_paths(raw: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in (
        "metadata_schema",
        "retrieval_text_schema",
        "golden_rules",
        "retrieval_policy",
        "processing_templates",
    ):
        value = raw.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise PipelinePluginRegistryError(f"plugin manifest field '{key}' must be a string relative file path")
        text = value.strip()
        if not text:
            raise PipelinePluginRegistryError(f"plugin manifest field '{key}' must be a non-empty relative file path")
        if "\x00" in text or "\\" in text or text.startswith("/") or ".." in Path(text).parts:
            raise PipelinePluginRegistryError(f"plugin manifest field '{key}' must be a relative file path")
        out[key] = text
    return out


def _manifest_suggested_pipeline_patch(
    raw: dict[str, Any],
    *,
    entries: dict[str, PipelinePluginEntry],
) -> dict[str, Any]:
    raw_patch = raw.get("suggested_pipeline_patch")
    if isinstance(raw_patch, dict):
        activation_refs = sorted(
            key
            for key in ("governance_python_plugin", "chunk_python_plugin", "kg_python_plugin")
            if raw_patch.get(key)
        )
        if activation_refs:
            joined = ", ".join(activation_refs)
            raise PipelinePluginRegistryError(f"suggested_pipeline_patch must not set plugin activation refs: {joined}")
    try:
        patch = normalize_document_pipeline_patch(
            raw_patch,
            field_label="suggested_pipeline_patch",
            invalid_message="plugin manifest field 'suggested_pipeline_patch' is invalid",
        )
    except ValueError as exc:
        message = str(exc)
        if message == "suggested_pipeline_patch must be an object":
            message = "plugin manifest field 'suggested_pipeline_patch' must be an object"
        raise PipelinePluginRegistryError(message) from exc
    activation_refs = sorted(
        key
        for key in ("governance_python_plugin", "chunk_python_plugin", "kg_python_plugin")
        if patch.get(key)
    )
    if activation_refs:
        joined = ", ".join(activation_refs)
        raise PipelinePluginRegistryError(f"suggested_pipeline_patch must not set plugin activation refs: {joined}")
    platform_strategy_fields = sorted(
        key
        for key in patch
        if key in _PLUGIN_SUGGESTED_PATCH_FORBIDDEN_STRATEGY_FIELDS
        or (key.startswith("governance_") and key not in _PLUGIN_SUGGESTED_PATCH_ALLOWED_GOVERNANCE_FIELDS)
    )
    if platform_strategy_fields:
        joined = ", ".join(platform_strategy_fields[:20])
        raise PipelinePluginRegistryError(f"suggested_pipeline_patch must not set platform strategy fields: {joined}")
    unsupported_fields = sorted(key for key in patch if key not in _PLUGIN_SUGGESTED_PATCH_ALLOWED_FIELDS)
    if unsupported_fields:
        joined = ", ".join(unsupported_fields[:20])
        raise PipelinePluginRegistryError(f"suggested_pipeline_patch may only set plugin suggested fields: {joined}")
    for key, stage in (
        ("governance_python_params", "governance"),
        ("chunk_python_params", "chunk"),
        ("kg_python_params", "kg"),
    ):
        if key in patch and stage not in entries:
            raise PipelinePluginRegistryError(f"suggested_pipeline_patch {key} requires plugin entry stage {stage}")
    return patch


def _entry_file_path(plugin_dir: Path, entry: PipelinePluginEntry) -> Path | None:
    module_part, _, _func = entry.target.partition(":")
    if module_part.endswith(".py") or "/" in module_part:
        first_part = next((part for part in Path(module_part).parts if part not in {"", "."}), "")
        if first_part in _RESERVED_ENTRY_MODULE_ROOTS:
            raise PipelinePluginRegistryError("plugin entry file must not use platform package names")
        candidate = (plugin_dir / module_part).resolve()
        root = plugin_dir.resolve()
        if root != candidate and root not in candidate.parents:
            raise PipelinePluginRegistryError("plugin entry file must stay inside plugin directory")
        if not candidate.is_file():
            raise PipelinePluginRegistryError(f"plugin entry file not found: {module_part}")
        return candidate
    return None


def _entry_import_module_file_path(plugin_dir: Path, entry: PipelinePluginEntry) -> Path | None:
    module_part, _, _func = entry.target.partition(":")
    if module_part.endswith(".py") or "/" in module_part:
        return _entry_file_path(plugin_dir, entry)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", module_part):
        raise PipelinePluginRegistryError("plugin entry module must be a local import path")
    if module_part.split(".", 1)[0] in _RESERVED_ENTRY_MODULE_ROOTS:
        raise PipelinePluginRegistryError("plugin entry module must not use platform package names")
    root = plugin_dir.resolve()
    rel_parts = module_part.split(".")
    candidates = [
        (root / Path(*rel_parts)).with_suffix(".py"),
        root / Path(*rel_parts) / "__init__.py",
    ]
    for candidate in candidates:
        resolved = candidate.resolve()
        if root != resolved and root not in resolved.parents:
            raise PipelinePluginRegistryError("plugin entry module must resolve inside plugin directory")
        if resolved.is_file():
            return resolved
    raise PipelinePluginRegistryError("plugin entry module must resolve inside plugin directory")


def _target_defines_symbol(target: ast.AST, symbol: str) -> bool:
    if isinstance(target, ast.Name):
        return target.id == symbol
    if isinstance(target, ast.Starred):
        return _target_defines_symbol(target.value, symbol)
    if isinstance(target, (ast.Tuple, ast.List)):
        return any(_target_defines_symbol(item, symbol) for item in target.elts)
    return False


def _source_file_defines_symbol(path: Path, symbol: str, *, label: str) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except Exception as exc:  # noqa: BLE001
        raise PipelinePluginRegistryError(f"{label} source file cannot be parsed") from exc
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name == symbol:
            return True
        if isinstance(node, ast.Assign) and any(_target_defines_symbol(target, symbol) for target in node.targets):
            return True
        if isinstance(node, ast.AnnAssign) and _target_defines_symbol(node.target, symbol):
            return True
    return False


def _validate_entry_module_paths(plugin_dir: Path, entries: dict[str, PipelinePluginEntry]) -> None:
    for entry in entries.values():
        _entry_import_module_file_path(plugin_dir, entry)


def _contract_file_path(plugin_dir: Path, rel_path: str) -> Path:
    candidate = (plugin_dir / rel_path).resolve()
    root = plugin_dir.resolve()
    if root != candidate and root not in candidate.parents:
        raise PipelinePluginRegistryError("plugin contract file must stay inside plugin directory")
    if not candidate.is_file():
        raise PipelinePluginRegistryError(f"plugin contract file not found: {rel_path}")
    return candidate


def _load_contract_json(plugin_dir: Path, rel_path: str) -> dict[str, Any]:
    path = _contract_file_path(plugin_dir, rel_path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PipelinePluginRegistryError(f"invalid plugin contract JSON '{rel_path}': {exc}") from exc
    if not isinstance(raw, dict):
        raise PipelinePluginRegistryError(f"plugin contract JSON '{rel_path}' must be an object")
    return raw


def _validate_declared_contract_schema(
    raw: dict[str, Any],
    *,
    contract_name: str,
    expected_schema: str,
    supported_fields: set[str],
) -> None:
    if raw.get("schema") != expected_schema:
        raise PipelinePluginRegistryError(f"{contract_name}.schema must be {expected_schema}")
    unknown = sorted(str(key or "").strip() or "<empty>" for key in raw if str(key or "").strip() not in supported_fields)
    if unknown:
        raise PipelinePluginRegistryError(f"{contract_name} contains unknown top-level fields: {', '.join(unknown[:20])}")


def _validate_processing_template_ref(plugin_dir: Path, ref: Any, *, label: str) -> str:
    if not isinstance(ref, str):
        raise PipelinePluginRegistryError(f"{label} must be a string")
    text = ref.strip()
    if not text:
        raise PipelinePluginRegistryError(f"{label} must be non-empty")
    if "\x00" in text or "\\" in text or ":" not in text:
        raise PipelinePluginRegistryError(f"{label} must be a local plugin symbol ref")
    module_part, _sep, symbol = text.partition(":")
    if not _ENTRY_FUNCTION_RE.fullmatch(symbol):
        raise PipelinePluginRegistryError(f"{label} must include a symbol name")
    try:
        source_path = _entry_import_module_file_path(
            plugin_dir,
            PipelinePluginEntry(stage="processing_template", target=text),
        )
    except PipelinePluginRegistryError as exc:
        message = str(exc)
        if "platform package names" in message:
            raise PipelinePluginRegistryError(f"{label} must not use platform package names") from exc
        raise PipelinePluginRegistryError(f"{label} is invalid: {message}") from exc
    if source_path is None or not _source_file_defines_symbol(source_path, symbol, label=label):
        raise PipelinePluginRegistryError(f"{label} must reference an existing plugin-local symbol")
    return text


@lru_cache(maxsize=1)
def _builtin_processing_template_keys() -> frozenset[str]:
    from app.services.governance_processing_scripts import list_builtin_processing_scripts

    return frozenset(str(script.key or "").strip() for script in list_builtin_processing_scripts() if script.key)


def _validate_processing_templates(
    raw: dict[str, Any],
    *,
    plugin_id: str,
    version: str,
    plugin_dir: Path,
    entries: dict[str, PipelinePluginEntry],
) -> dict[str, Any]:
    if not raw:
        return {}
    if raw.get("plugin_id") != plugin_id:
        raise PipelinePluginRegistryError("processing_templates.plugin_id must match plugin manifest id")
    if raw.get("version") != version:
        raise PipelinePluginRegistryError("processing_templates.version must match plugin manifest version")
    templates = raw.get("templates")
    if not isinstance(templates, list):
        raise PipelinePluginRegistryError("processing_templates.templates must be a list")

    cleaned_templates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(templates):
        if not isinstance(item, dict):
            raise PipelinePluginRegistryError(f"processing_templates.templates[{index}] must be an object")
        unknown = sorted(str(key or "").strip() or "<empty>" for key in item if str(key or "").strip() not in _PROCESSING_TEMPLATE_FIELDS)
        if unknown:
            raise PipelinePluginRegistryError(
                f"processing_templates.templates[{index}] contains unknown fields: {', '.join(unknown[:20])}"
            )
        key = str(item.get("key") or "").strip()
        if not _PROCESSING_TEMPLATE_KEY_RE.fullmatch(key):
            raise PipelinePluginRegistryError(f"processing_templates.templates[{index}].key is invalid")
        if key in _builtin_processing_template_keys():
            raise PipelinePluginRegistryError(
                f"processing_templates.templates[{index}].key collides with a platform built-in processing template"
            )
        if key in seen:
            raise PipelinePluginRegistryError(f"processing_templates.templates[{index}].key is duplicated")
        seen.add(key)
        name = str(item.get("name") or "").strip()
        if not name:
            raise PipelinePluginRegistryError(f"processing_templates.templates[{index}].name must be non-empty")
        stage = str(item.get("stage") or "").strip()
        if stage not in entries:
            raise PipelinePluginRegistryError(
                f"processing_templates.templates[{index}].stage must reference a plugin entry stage"
            )
        related = item.get("related_implementations")
        if related is None:
            related_refs: list[str] = []
        elif isinstance(related, list):
            related_refs = [
                _validate_processing_template_ref(plugin_dir, ref, label=f"processing_templates.templates[{index}].related_implementations[{ref_index}]")
                for ref_index, ref in enumerate(related)
            ]
        else:
            raise PipelinePluginRegistryError(
                f"processing_templates.templates[{index}].related_implementations must be a list"
            )
        cleaned_templates.append(
            {
                "key": key,
                "name": name,
                "description": str(item.get("description") or "").strip(),
                "stage": stage,
                "implemented_by": _validate_processing_template_ref(
                    plugin_dir,
                    item.get("implemented_by"),
                    label=f"processing_templates.templates[{index}].implemented_by",
                ),
                "related_implementations": related_refs,
            }
        )

    return {
        "schema": "mimirq.pipeline_plugin_processing_templates.v1",
        "plugin_id": plugin_id,
        "version": version,
        "description": str(raw.get("description") or "").strip(),
        "templates": cleaned_templates,
    }


def _plugin_python_source_paths(plugin_dir: Path) -> list[Path]:
    root = plugin_dir.resolve()
    out: list[Path] = []
    for path in root.rglob("*.py"):
        rel_parts = path.relative_to(root).parts
        if any(part == "__pycache__" or part.startswith(".") for part in rel_parts):
            continue
        if path.is_file():
            out.append(path.resolve())
    return out


def _literal_string_arg(node: ast.Call) -> str | None:
    if node.args:
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value
    for keyword in node.keywords:
        if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
            return keyword.value.value
    return None


def _is_importlib_import_module_getattr(node: ast.AST, importlib_module_names: set[str]) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
        return False
    if len(node.args) < 2:
        return False
    target, attr = node.args[0], node.args[1]
    return (
        isinstance(target, ast.Name)
        and target.id in importlib_module_names
        and isinstance(attr, ast.Constant)
        and attr.value == "import_module"
    )


def _is_importlib_import_module_attribute(node: ast.AST, importlib_module_names: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "import_module"
        and isinstance(node.value, ast.Name)
        and node.value.id in importlib_module_names
    )


def _is_module_string_getattr(node: ast.AST, module_names: set[str], attr_name: str) -> bool:
    if not isinstance(node, ast.Call):
        return False
    if not isinstance(node.func, ast.Name) or node.func.id != "getattr":
        return False
    if len(node.args) < 2:
        return False
    target, attr = node.args[0], node.args[1]
    return (
        isinstance(target, ast.Name)
        and target.id in module_names
        and isinstance(attr, ast.Constant)
        and attr.value == attr_name
    )


def _is_builtins_import_attribute(node: ast.AST, builtins_module_names: set[str]) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "__import__"
        and isinstance(node.value, ast.Name)
        and node.value.id in builtins_module_names
    )


def _is_builtins_import_subscript(node: ast.AST, builtins_module_names: set[str]) -> bool:
    return (
        isinstance(node, ast.Subscript)
        and isinstance(node.value, ast.Name)
        and node.value.id in builtins_module_names
        and isinstance(node.slice, ast.Constant)
        and node.slice.value == "__import__"
    )


def _validate_plugin_source_imports(plugin_dir: Path) -> None:
    root = plugin_dir.resolve()
    for path in _plugin_python_source_paths(root):
        rel_path = path.relative_to(root)
        first_part = rel_path.parts[0] if rel_path.parts else ""
        if first_part in _RESERVED_ENTRY_MODULE_ROOTS:
            raise PipelinePluginRegistryError("plugin source file must not use platform package names")
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=rel_path.as_posix())
        except SyntaxError as exc:
            raise PipelinePluginRegistryError(f"plugin source {rel_path.as_posix()} has invalid Python syntax: {exc.msg}") from exc
        builtins_module_names = {"__builtins__", "builtins"}
        importlib_module_names = {"importlib"}
        import_module_function_names = {"__import__"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "builtins":
                        builtins_module_names.add(alias.asname or alias.name)
                    if alias.name == "importlib":
                        importlib_module_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "builtins":
                for alias in node.names:
                    if alias.name == "__import__":
                        import_module_function_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == "importlib":
                for alias in node.names:
                    if alias.name == "import_module":
                        import_module_function_names.add(alias.asname or alias.name)
            elif isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Name) and node.value.id in builtins_module_names:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            builtins_module_names.add(target.id)
                if isinstance(node.value, ast.Name) and node.value.id in importlib_module_names:
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            importlib_module_names.add(target.id)
                value_is_import_module = isinstance(node.value, ast.Name) and node.value.id in import_module_function_names
                value_is_builtins_attribute = _is_builtins_import_attribute(node.value, builtins_module_names)
                value_is_builtins_subscript = _is_builtins_import_subscript(node.value, builtins_module_names)
                value_is_builtins_getattr = _is_module_string_getattr(node.value, builtins_module_names, "__import__")
                value_is_importlib_attribute = _is_importlib_import_module_attribute(node.value, importlib_module_names)
                value_is_importlib_getattr = _is_importlib_import_module_getattr(node.value, importlib_module_names)
                if (
                    value_is_import_module
                    or value_is_builtins_attribute
                    or value_is_builtins_subscript
                    or value_is_builtins_getattr
                    or value_is_importlib_attribute
                    or value_is_importlib_getattr
                ):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            import_module_function_names.add(target.id)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_name = str(alias.name or "").split(".", 1)[0]
                    if root_name in _RESERVED_ENTRY_MODULE_ROOTS:
                        raise PipelinePluginRegistryError(
                            f"plugin source {rel_path.as_posix()} must not import platform module {root_name}"
                        )
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                root_name = str(node.module or "").split(".", 1)[0]
                if root_name in _RESERVED_ENTRY_MODULE_ROOTS:
                    raise PipelinePluginRegistryError(
                        f"plugin source {rel_path.as_posix()} must not import platform module {root_name}"
                    )
            elif isinstance(node, ast.Call):
                dynamic_import_name: str | None = None
                if isinstance(node.func, ast.Name) and node.func.id in import_module_function_names:
                    dynamic_import_name = _literal_string_arg(node)
                elif _is_builtins_import_attribute(node.func, builtins_module_names):
                    dynamic_import_name = _literal_string_arg(node)
                elif _is_builtins_import_subscript(node.func, builtins_module_names):
                    dynamic_import_name = _literal_string_arg(node)
                elif _is_module_string_getattr(node.func, builtins_module_names, "__import__"):
                    dynamic_import_name = _literal_string_arg(node)
                elif _is_importlib_import_module_attribute(node.func, importlib_module_names):
                    dynamic_import_name = _literal_string_arg(node)
                elif _is_importlib_import_module_getattr(node.func, importlib_module_names):
                    dynamic_import_name = _literal_string_arg(node)
                root_name = str(dynamic_import_name or "").split(".", 1)[0]
                if root_name in _RESERVED_ENTRY_MODULE_ROOTS:
                    raise PipelinePluginRegistryError(
                        f"plugin source {rel_path.as_posix()} must not dynamically import platform module {root_name}"
                    )


def _plugin_package_file_paths(plugin_dir: Path) -> list[Path]:
    root = plugin_dir.resolve()
    out: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(root).parts
        if any(part == "__pycache__" or part.startswith(".") for part in rel_parts):
            continue
        if path.name == PLUGIN_TEST_REPORT_FILENAME or path.suffix == ".pyc":
            continue
        if path.name.lower() in _PLUGIN_DOC_FILENAMES:
            continue
        out.append(path.resolve())
    return out


def _plugin_local_module_names(plugin_dir: Path) -> set[str]:
    root = plugin_dir.resolve()
    names: set[str] = set()
    for path in _plugin_python_source_paths(root):
        rel = path.relative_to(root).with_suffix("")
        if rel.name == "__init__":
            rel = rel.parent
        parts = [part for part in rel.parts if part and part != "."]
        if not parts:
            continue
        names.add(".".join(parts))
        names.add(parts[0])
    return names


def _module_file_path(module: Any) -> Path | None:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return None
    try:
        return Path(module_file).resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None


def _path_inside_plugin(path: Path | None, root: Path) -> bool:
    if path is None:
        return False
    return root == path or root in path.parents


def _purge_plugin_modules(plugin_dir: Path) -> dict[str, Any]:
    root = plugin_dir.resolve()
    local_names = _plugin_local_module_names(root)
    stale_names: list[str] = []
    external_snapshot: dict[str, Any] = {}
    for module_name, module in list(sys.modules.items()):
        module_path = _module_file_path(module)
        is_local_name = module_name in local_names or any(module_name.startswith(f"{name}.") for name in local_names)
        is_plugin_path = _path_inside_plugin(module_path, root)
        if is_local_name or is_plugin_path:
            if not is_plugin_path:
                external_snapshot[module_name] = module
            stale_names.append(module_name)
    for module_name in stale_names:
        sys.modules.pop(module_name, None)
    return external_snapshot


def _restore_plugin_modules(plugin_dir: Path, external_snapshot: dict[str, Any]) -> None:
    root = plugin_dir.resolve()
    for module_name, module in list(sys.modules.items()):
        if _path_inside_plugin(_module_file_path(module), root):
            sys.modules.pop(module_name, None)
    sys.modules.update(external_snapshot)


def _purge_plugin_bytecode(plugin_dir: Path) -> None:
    root = plugin_dir.resolve()
    for cache_dir in root.rglob("__pycache__"):
        if cache_dir.is_dir():
            shutil.rmtree(cache_dir, ignore_errors=True)


@contextmanager
def _suppress_plugin_bytecode(plugin_dir: Path):
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        yield
    finally:
        sys.dont_write_bytecode = previous_dont_write_bytecode
        _purge_plugin_bytecode(plugin_dir)


def compute_plugin_package_hash(
    plugin_dir: Path,
    manifest_path: Path,
    entries: dict[str, PipelinePluginEntry],
    contract_paths: dict[str, str] | None = None,
) -> str:
    hasher = hashlib.sha256()
    files: list[Path] = [manifest_path]
    for file_path in _plugin_package_file_paths(plugin_dir):
        if file_path not in files:
            files.append(file_path)
    for entry in entries.values():
        file_path = _entry_import_module_file_path(plugin_dir, entry)
        if file_path is not None and file_path not in files:
            files.append(file_path)
    for rel_path in (contract_paths or {}).values():
        file_path = _contract_file_path(plugin_dir, rel_path)
        if file_path not in files:
            files.append(file_path)
    root = plugin_dir.resolve()
    for path in sorted(files, key=lambda p: str(p.resolve().relative_to(root)) if p.resolve() != manifest_path.resolve() else p.name):
        resolved = path.resolve()
        rel = resolved.relative_to(root) if resolved != manifest_path.resolve() else Path(path.name)
        hasher.update(str(rel).encode("utf-8", "ignore"))
        hasher.update(b"\0")
        hasher.update(resolved.read_bytes())
        hasher.update(b"\0")
    return hasher.hexdigest()


def _load_test_report(plugin_dir: Path) -> dict[str, Any] | None:
    path = plugin_dir / PLUGIN_TEST_REPORT_FILENAME
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise PipelinePluginRegistryError(f"invalid plugin test report: {exc}") from exc
    return raw if isinstance(raw, dict) else None


def _test_report_summary(report: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {}

    stages: dict[str, Any] = {}
    raw_stages = report.get("stages")
    if isinstance(raw_stages, dict):
        for stage, raw in raw_stages.items():
            if not isinstance(raw, dict):
                continue
            stage_name = str(stage)
            if stage_name not in _SUPPORTED_ENTRY_STAGES:
                continue
            validation_key = "kg_validation" if stage_name == "kg" else "metadata_validation"
            validation = raw.get(validation_key) if isinstance(raw.get(validation_key), dict) else {}
            stages[stage_name] = {
                "passed": raw.get("passed") is True,
                "input_count": int(raw.get("input_count") or 0),
                "output_count": int(raw.get("output_count") or 0),
                "output_chars": int(raw.get("output_chars") or 0),
                "metadata_ok": validation.get("ok") is True if validation else None,
            }

    golden_report: dict[str, Any] = {}
    raw_golden = report.get("golden_draft")
    if isinstance(raw_golden, dict):
        sample_questions = raw_golden.get("sample_questions")
        golden_report = {
            "passed": raw_golden.get("passed") is True,
            "items_total": int(raw_golden.get("items_total") or 0),
            "sample_questions": [str(item) for item in sample_questions[:5]] if isinstance(sample_questions, list) else [],
        }

    return {
        "plugin_id": str(report.get("plugin_id") or ""),
        "version": str(report.get("version") or ""),
        "package_hash": str(report.get("package_hash") or ""),
        "tested_at": str(report.get("tested_at") or ""),
        "passed": report.get("passed") is True,
        "stages": stages,
        "golden_draft": golden_report,
    }


def _stage_report_validation_ok(stage: str, raw: Any) -> bool:
    if not isinstance(raw, dict) or raw.get("passed") is not True:
        return False
    if int(raw.get("input_count") or 0) <= 0 or int(raw.get("output_count") or 0) <= 0:
        return False
    validation_key = "kg_validation" if stage == "kg" else "metadata_validation"
    validation = raw.get(validation_key)
    if isinstance(validation, dict):
        return validation.get("ok") is True
    return False


def _test_status(
    *,
    plugin_id: str,
    version: str,
    published: bool,
    require_test_report: bool,
    package_hash: str,
    entries: dict[str, PipelinePluginEntry],
    golden_rules: dict[str, Any],
    report: dict[str, Any] | None,
) -> tuple[bool, str]:
    if not published:
        return False, "draft"
    if not require_test_report:
        return True, "not_required"
    if not report:
        return False, "missing"
    if str(report.get("plugin_id") or "") != plugin_id or str(report.get("version") or "") != version:
        return False, "mismatch"
    if report.get("package_hash") != package_hash:
        return False, "stale"
    if report.get("passed") is not True:
        return False, "failed"
    stages = report.get("stages")
    if not isinstance(stages, dict):
        return False, "failed"
    unknown = [str(stage) for stage in stages if str(stage) not in _SUPPORTED_ENTRY_STAGES]
    if unknown:
        return False, "failed"
    missing = [stage for stage in entries if not isinstance(stages.get(stage), dict)]
    if missing:
        return False, "missing"
    failed = [stage for stage in entries if not _stage_report_validation_ok(stage, stages.get(stage))]
    if failed:
        return False, "failed"
    if golden_rules.get("schema") == "mimirq.golden_rules.v1" and "chunk" in entries:
        golden_report = report.get("golden_draft")
        if not isinstance(golden_report, dict) or golden_report.get("passed") is not True:
            return False, "golden_missing"
    return True, "passed"


def describe_plugin_dir(plugin_dir: Path, *, require_test_report: bool | None = None) -> PipelinePluginDescriptor:
    manifest_path = _find_manifest(plugin_dir)
    if manifest_path is None:
        raise PipelinePluginRegistryError(f"plugin manifest not found in {plugin_dir}")
    manifest = _load_manifest(manifest_path)
    plugin_id = _validate_manifest_text(manifest.get("id"), field_name="id", pattern=_PLUGIN_ID_RE)
    version = _validate_manifest_text(manifest.get("version"), field_name="version", pattern=_PLUGIN_VERSION_RE)
    entries = _manifest_entries(manifest)
    _validate_entry_module_paths(plugin_dir, entries)
    _validate_plugin_source_imports(plugin_dir)
    contract_paths = _manifest_contract_paths(manifest)
    suggested_pipeline_patch = _manifest_suggested_pipeline_patch(manifest, entries=entries)
    metadata_schema = (
        _load_contract_json(plugin_dir, contract_paths["metadata_schema"])
        if "metadata_schema" in contract_paths
        else {}
    )
    retrieval_text_schema = (
        _load_contract_json(plugin_dir, contract_paths["retrieval_text_schema"])
        if "retrieval_text_schema" in contract_paths
        else {}
    )
    golden_rules = (
        _load_contract_json(plugin_dir, contract_paths["golden_rules"])
        if "golden_rules" in contract_paths
        else {}
    )
    retrieval_policy = (
        _load_contract_json(plugin_dir, contract_paths["retrieval_policy"])
        if "retrieval_policy" in contract_paths
        else {}
    )
    processing_templates = (
        _load_contract_json(plugin_dir, contract_paths["processing_templates"])
        if "processing_templates" in contract_paths
        else {}
    )
    if "metadata_schema" in contract_paths:
        _validate_declared_contract_schema(
            metadata_schema,
            contract_name="metadata_schema",
            expected_schema="mimirq.metadata_schema.v1",
            supported_fields=_SUPPORTED_CONTRACT_FIELDS["metadata_schema"],
        )
    if "retrieval_text_schema" in contract_paths:
        _validate_declared_contract_schema(
            retrieval_text_schema,
            contract_name="retrieval_text_schema",
            expected_schema="mimirq.retrieval_text_schema.v1",
            supported_fields=_SUPPORTED_CONTRACT_FIELDS["retrieval_text_schema"],
        )
    if "golden_rules" in contract_paths:
        _validate_declared_contract_schema(
            golden_rules,
            contract_name="golden_rules",
            expected_schema="mimirq.golden_rules.v1",
            supported_fields=_SUPPORTED_CONTRACT_FIELDS["golden_rules"],
        )
    if "retrieval_policy" in contract_paths:
        _validate_declared_contract_schema(
            retrieval_policy,
            contract_name="retrieval_policy",
            expected_schema="mimirq.retrieval_policy.v1",
            supported_fields=_SUPPORTED_CONTRACT_FIELDS["retrieval_policy"],
        )
    if "processing_templates" in contract_paths:
        _validate_declared_contract_schema(
            processing_templates,
            contract_name="processing_templates",
            expected_schema="mimirq.pipeline_plugin_processing_templates.v1",
            supported_fields=_SUPPORTED_CONTRACT_FIELDS["processing_templates"],
        )
        processing_templates = _validate_processing_templates(
            processing_templates,
            plugin_id=plugin_id,
            version=version,
            plugin_dir=plugin_dir,
            entries=entries,
        )
    try:
        validate_retrieval_text_schema_metadata_fields(
            retrieval_text_schema=retrieval_text_schema,
            metadata_schema=metadata_schema,
        )
        validate_golden_rules_metadata_fields(golden_rules=golden_rules, metadata_schema=metadata_schema)
        validate_retrieval_policy_metadata_fields(
            retrieval_policy=retrieval_policy,
            metadata_schema=metadata_schema,
        )
    except PipelinePluginContractError as exc:
        raise PipelinePluginRegistryError(str(exc)) from exc
    contract_summary = summarize_contracts(
        metadata_schema=metadata_schema,
        retrieval_text_schema=retrieval_text_schema,
        golden_rules=golden_rules,
        retrieval_policy=retrieval_policy,
    )
    package_hash = compute_plugin_package_hash(plugin_dir, manifest_path, entries, contract_paths)
    report = _load_test_report(plugin_dir)
    published = str(manifest.get("status") or "draft").strip().lower() == "published"
    require_report = (
        bool(getattr(settings, "PYTHON_PIPELINE_PLUGIN_REQUIRE_TEST_REPORT", True))
        if require_test_report is None
        else require_test_report
    )
    executable, test_status = _test_status(
        plugin_id=plugin_id,
        version=version,
        published=published,
        require_test_report=require_report,
        package_hash=package_hash,
        entries=entries,
        golden_rules=golden_rules,
        report=report,
    )
    refs = {stage: f"plugin:{plugin_id}@{version}:{stage}" for stage in entries}
    return PipelinePluginDescriptor(
        id=plugin_id,
        version=version,
        name=str(manifest.get("name") or plugin_id).strip() or plugin_id,
        description=str(manifest.get("description") or "").strip(),
        published=published,
        executable=executable,
        test_status=test_status,
        plugin_dir=plugin_dir,
        manifest_path=manifest_path,
        package_hash=package_hash,
        test_report=_test_report_summary(report),
        entries=entries,
        refs=refs,
        metadata_schema=metadata_schema,
        retrieval_text_schema=retrieval_text_schema,
        golden_rules=golden_rules,
        retrieval_policy=retrieval_policy,
        processing_templates=processing_templates,
        contract_summary=contract_summary,
        suggested_pipeline_patch=suggested_pipeline_patch,
    )


def list_pipeline_plugins(
    directories: list[str | Path] | None = None,
    *,
    require_test_report: bool | None = None,
) -> list[PipelinePluginDescriptor]:
    roots = [Path(p) for p in directories] if directories is not None else default_plugin_directories()
    plugins: list[PipelinePluginDescriptor] = []
    for root in roots:
        for plugin_dir in _candidate_plugin_dirs(root):
            plugins.append(describe_plugin_dir(plugin_dir, require_test_report=require_test_report))
    return sorted(plugins, key=lambda item: (item.id, item.version))


def list_pipeline_plugins_with_errors(
    directories: list[str | Path] | None = None,
    *,
    require_test_report: bool | None = None,
) -> tuple[list[PipelinePluginDescriptor], list[PipelinePluginDiscoveryError]]:
    roots = [Path(p) for p in directories] if directories is not None else default_plugin_directories()
    plugins: list[PipelinePluginDescriptor] = []
    errors: list[PipelinePluginDiscoveryError] = []
    for root in roots:
        for plugin_dir in _candidate_plugin_dirs(root):
            try:
                plugins.append(describe_plugin_dir(plugin_dir, require_test_report=require_test_report))
            except Exception as exc:  # noqa: BLE001 - listing should surface broken plugins without hiding valid ones.
                errors.append(
                    PipelinePluginDiscoveryError(
                        plugin_dir=plugin_dir,
                        manifest_path=_find_manifest(plugin_dir),
                        error=str(exc),
                    )
                )
    return sorted(plugins, key=lambda item: (item.id, item.version)), sorted(
        errors,
        key=lambda item: str(item.plugin_dir),
    )


def _load_file_entry_callable(plugin_dir: Path, entry: PipelinePluginEntry) -> Any:
    file_path = _entry_file_path(plugin_dir, entry)
    if file_path is None:
        return None
    _module_part, _, function_name = entry.target.partition(":")
    with _PLUGIN_IMPORT_LOCK:
        importlib.invalidate_caches()
        external_snapshot = _purge_plugin_modules(plugin_dir)
        _purge_plugin_bytecode(plugin_dir)
        module_seed = hashlib.sha256(
            f"{file_path.resolve()}:{file_path.stat().st_mtime_ns}".encode("utf-8")
        ).hexdigest()[:16]
        module_name = f"_mimirq_pipeline_plugin_{module_seed}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise PipelinePluginRegistryError(f"failed to load plugin module from {file_path}")
        module = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(plugin_dir.resolve()))
        try:
            with _suppress_plugin_bytecode(plugin_dir):
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
        finally:
            try:
                sys.path.remove(str(plugin_dir.resolve()))
            except ValueError:
                pass
            _restore_plugin_modules(plugin_dir, external_snapshot)
    func = getattr(module, function_name, None)
    if not callable(func):
        raise PipelinePluginRegistryError(f"plugin entry '{entry.target}' has no callable '{function_name}'")
    return func


def _load_import_entry_callable(plugin_dir: Path, entry: PipelinePluginEntry) -> Any:
    module_name, _, function_name = entry.target.partition(":")
    with _PLUGIN_IMPORT_LOCK:
        importlib.invalidate_caches()
        external_snapshot = _purge_plugin_modules(plugin_dir)
        _purge_plugin_bytecode(plugin_dir)
        sys.path.insert(0, str(plugin_dir.resolve()))
        try:
            with _suppress_plugin_bytecode(plugin_dir):
                module = importlib.import_module(module_name)
        finally:
            try:
                sys.path.remove(str(plugin_dir.resolve()))
            except ValueError:
                pass
            _restore_plugin_modules(plugin_dir, external_snapshot)
    func = getattr(module, function_name, None)
    if not callable(func):
        raise PipelinePluginRegistryError(f"plugin entry '{entry.target}' has no callable '{function_name}'")
    return func


@contextmanager
def _plugin_execution_context(plugin_dir: Path):
    with _PLUGIN_IMPORT_LOCK:
        importlib.invalidate_caches()
        external_snapshot = _purge_plugin_modules(plugin_dir)
        sys.path.insert(0, str(plugin_dir.resolve()))
        try:
            with _suppress_plugin_bytecode(plugin_dir):
                yield
        finally:
            try:
                sys.path.remove(str(plugin_dir.resolve()))
            except ValueError:
                pass
            _restore_plugin_modules(plugin_dir, external_snapshot)


def _wrap_plugin_iterator(plugin_dir: Path, iterator: Iterator[Any]) -> Iterator[Any]:
    while True:
        with _plugin_execution_context(plugin_dir):
            try:
                item = next(iterator)
            except StopIteration:
                return
        yield item


def _wrap_plugin_callable(plugin_dir: Path, func: Any) -> Any:
    @wraps(func)
    def _wrapped(*args: Any, **kwargs: Any) -> Any:
        with _plugin_execution_context(plugin_dir):
            result = func(*args, **kwargs)
        if isinstance(result, Iterator):
            return _wrap_plugin_iterator(plugin_dir, result)
        return result

    return _wrapped


def load_descriptor_stage_callable(descriptor: PipelinePluginDescriptor, stage: str) -> Any:
    entry = descriptor.entries.get(stage)
    if entry is None:
        raise PipelinePluginRegistryError(f"plugin '{descriptor.id}@{descriptor.version}' has no {stage} entry")
    func = _load_file_entry_callable(descriptor.plugin_dir, entry)
    if func is None:
        func = _load_import_entry_callable(descriptor.plugin_dir, entry)
    return _wrap_plugin_callable(descriptor.plugin_dir, func)


def resolve_registered_plugin_callable(
    plugin_ref: str,
    *,
    directories: list[str | Path] | None = None,
    require_test_report: bool | None = None,
) -> Any:
    plugin_id, version, stage = parse_registered_plugin_ref(plugin_ref)
    for descriptor in list_pipeline_plugins(directories, require_test_report=require_test_report):
        if descriptor.id != plugin_id or descriptor.version != version:
            continue
        if not descriptor.published:
            raise PipelinePluginRegistryError(f"plugin '{plugin_id}@{version}' is not published")
        if not descriptor.executable:
            raise PipelinePluginRegistryError(
                f"plugin '{plugin_id}@{version}' is not executable; local test report status is {descriptor.test_status}"
            )
        return load_descriptor_stage_callable(descriptor, stage)
    raise PipelinePluginRegistryError(f"registered plugin not found: {plugin_id}@{version}")


def resolve_registered_plugin_descriptor(
    plugin_ref: str,
    *,
    directories: list[str | Path] | None = None,
    require_test_report: bool | None = None,
) -> PipelinePluginDescriptor:
    plugin_id, version, stage = parse_registered_plugin_ref(plugin_ref)
    for descriptor in list_pipeline_plugins(directories, require_test_report=require_test_report):
        if descriptor.id == plugin_id and descriptor.version == version:
            if stage not in descriptor.entries:
                raise PipelinePluginRegistryError(f"plugin '{plugin_id}@{version}' has no {stage} entry")
            return descriptor
    raise PipelinePluginRegistryError(f"registered plugin not found: {plugin_id}@{version}")


__all__ = [
    "PipelinePluginDescriptor",
    "PipelinePluginDiscoveryError",
    "PipelinePluginEntry",
    "PipelinePluginRegistryError",
    "PLUGIN_TEST_REPORT_FILENAME",
    "compute_plugin_package_hash",
    "describe_plugin_dir",
    "derive_registered_stage_plugin_ref",
    "is_registered_plugin_ref",
    "list_pipeline_plugins",
    "list_pipeline_plugins_with_errors",
    "load_descriptor_stage_callable",
    "parse_registered_plugin_ref",
    "resolve_registered_plugin_callable",
    "resolve_registered_plugin_descriptor",
]
