#!/usr/bin/env python3
"""Live API smoke for plugin-backed corpus ingest plus Golden regression."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import requests
except ModuleNotFoundError:  # pragma: no cover - depends on integration environment
    requests = None  # type: ignore[assignment]

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from plugin_golden_closed_loop_smoke import (  # noqa: E402
    DEFAULT_TENANT_ID,
    ClosedLoopResult,
    LiveApiClient,
    _join_url,
    run_closed_loop_smoke,
)

DEFAULT_EXTENSIONS = (".txt", ".docx", ".xlsx", ".doc")
TERMINAL_STATUSES = {"completed", "failed", "quarantined", "cancelled"}
REGISTERED_CHUNK_PLUGIN_REF_RE = re.compile(
    r"^plugin:[a-z0-9][a-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9_.+-]{0,31}:chunk$"
)
REGISTERED_STAGE_PLUGIN_REF_RE = re.compile(
    r"^plugin:[a-z0-9][a-z0-9_.-]{0,63}@[A-Za-z0-9][A-Za-z0-9_.+-]{0,31}:(?P<stage>governance|chunk|kg)$"
)
PLUGIN_ACTIVATION_REF_KEYS = frozenset(
    {"governance_python_plugin", "chunk_python_plugin", "kg_python_plugin"}
)


@dataclass(frozen=True)
class CorpusFile:
    path: Path
    rel_path: str
    size: int


@dataclass(frozen=True)
class UploadedDocument:
    document_id: str
    file: CorpusFile
    upload_status: str


@dataclass(frozen=True)
class CorpusClosedLoopResult:
    dataset_id: str
    source_dir: str
    uploaded_count: int
    skipped: list[dict[str, Any]]
    documents: list[dict[str, Any]]
    golden: dict[str, Any]


class CorpusApiClient(LiveApiClient):
    def json(
        self,
        method: str,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        for attempt in range(1, 8):
            try:
                return super().json(method, path, payload=payload, query=query)
            except TimeoutError as exc:
                if str(method or "").upper() != "GET" or attempt >= 7:
                    raise RuntimeError(f"{method} {path} timed out after transient retries") from exc
                time.sleep(_retry_after_seconds(exc, attempt=attempt))
            except RuntimeError as exc:
                if not _is_rate_limit_error(exc) or attempt >= 7:
                    raise
                time.sleep(_retry_after_seconds(exc, attempt=attempt))
        raise RuntimeError(f"{method} {path} failed after rate-limit retries")

    def upload_file(self, path: str, *, data: dict[str, str], file: CorpusFile) -> dict[str, Any]:
        if requests is None:
            raise RuntimeError("requests is required for multipart uploads")

        headers = {
            key: value
            for key, value in self.headers.items()
            if key.lower() not in {"content-type", "accept"}
        }
        url = _join_url(self.base_url, path)
        with file.path.open("rb") as fh:
            try:
                response = requests.post(
                    url,
                    data=data,
                    files={"file": (file.rel_path, fh)},
                    headers=headers,
                    timeout=self.timeout_sec,
                )
            except requests.RequestException as exc:
                raise RuntimeError(f"POST {url} failed for {file.rel_path}: {exc}") from exc
        if not 200 <= int(response.status_code) < 300:
            raise RuntimeError(
                f"POST {url} failed for {file.rel_path}: HTTP {response.status_code}: {response.text[:800]}"
            )
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"POST {url} returned non-object JSON for {file.rel_path}")
        return payload


def _progress(message: str) -> None:
    print(f"[plugin-corpus-smoke] {message}", file=sys.stderr, flush=True)


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc)
    return "HTTP 429" in text or "RATE_LIMIT_EXCEEDED" in text


def _retry_after_seconds(exc: BaseException, *, attempt: int) -> float:
    text = str(exc)
    match = re.search(r"retry_after_sec['\"]?\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)", text)
    if match:
        try:
            return max(0.1, min(30.0, float(match.group(1))))
        except ValueError:
            pass
    return min(30.0, max(0.5, float(attempt)))


def _normalize_extensions(extensions: set[str] | list[str] | tuple[str, ...] | str | None) -> set[str]:
    if extensions is None:
        values = DEFAULT_EXTENSIONS
    elif isinstance(extensions, str):
        values = tuple(part.strip() for part in extensions.split(","))
    else:
        values = tuple(str(part or "").strip() for part in extensions)

    out = set()
    for value in values:
        if not value:
            continue
        ext = value.lower()
        out.add(ext if ext.startswith(".") else f".{ext}")
    return out or set(DEFAULT_EXTENSIONS)


def discover_corpus_files(
    source_dir: Path | str,
    *,
    extensions: set[str] | list[str] | tuple[str, ...] | str | None = None,
    skip_empty: bool = True,
    max_files: int = 0,
    max_files_per_group: int = 0,
    sample_group_depth: int = 1,
    include_root_name: bool = False,
    include_hidden: bool = False,
) -> tuple[list[CorpusFile], list[dict[str, Any]]]:
    root = Path(source_dir).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise RuntimeError(f"source_dir is not a directory: {root}")

    allowed = _normalize_extensions(extensions)
    files: list[CorpusFile] = []
    skipped: list[dict[str, Any]] = []
    group_counts: dict[str, int] = {}
    per_group_cap = max(0, int(max_files_per_group or 0))
    group_depth = max(1, int(sample_group_depth or 1))
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        local_rel = path.relative_to(root)
        if not include_hidden and any(part.startswith(".") for part in local_rel.parts):
            continue
        if path.suffix.lower() not in allowed:
            continue
        rel = (Path(root.name) / local_rel).as_posix() if include_root_name else local_rel.as_posix()
        size = int(path.stat().st_size)
        if skip_empty and size <= 0:
            skipped.append({"path": rel, "reason": "empty_file", "size": size})
            continue
        if per_group_cap > 0:
            parent_parts = local_rel.parent.parts
            group_key = "/".join(parent_parts[:group_depth]) if parent_parts and parent_parts != (".",) else "."
            current_count = group_counts.get(group_key, 0)
            if current_count >= per_group_cap:
                skipped.append({"path": rel, "reason": "group_sample_limit", "size": size, "group": group_key})
                continue
            group_counts[group_key] = current_count + 1
        files.append(CorpusFile(path=path, rel_path=rel, size=size))
        if max_files > 0 and len(files) >= max_files:
            break
    return files, skipped


def validate_chunk_plugin_ref(chunk_plugin_ref: str) -> str:
    ref = str(chunk_plugin_ref or "").strip()
    if not ref:
        raise RuntimeError("chunk plugin ref is required")
    if not REGISTERED_CHUNK_PLUGIN_REF_RE.fullmatch(ref):
        if ref.startswith("plugin:") and "@" in ref and not ref.endswith(":chunk"):
            raise RuntimeError("chunk plugin ref must target the chunk stage")
        raise RuntimeError("registered chunk plugin ref is required for corpus closed-loop ingest")
    return ref


def _validate_stage_plugin_ref(plugin_ref: str | None, stage: str) -> str:
    ref = str(plugin_ref or "").strip()
    if not ref:
        return ""
    match = REGISTERED_STAGE_PLUGIN_REF_RE.fullmatch(ref)
    if not match or match.group("stage") != stage:
        raise RuntimeError(f"{stage} plugin ref must target the {stage} stage")
    return ref


def build_plugin_pipeline(
    *,
    chunk_plugin_ref: str,
    pipeline_patch: dict[str, Any] | None = None,
    governance_plugin_ref: str | None = None,
    kg_plugin_ref: str | None = None,
) -> dict[str, Any]:
    chunk_ref = validate_chunk_plugin_ref(chunk_plugin_ref)
    governance_ref = _validate_stage_plugin_ref(governance_plugin_ref, "governance")
    kg_ref = _validate_stage_plugin_ref(kg_plugin_ref, "kg")
    patch = _reject_pipeline_patch_activation_refs(
        pipeline_patch,
        label="pipeline patch",
    )
    pipeline = {
        "governance_enabled": True,
        "persist_parsed_content": True,
        "persist_parsed_content_max_chars": 1_000_000,
        "chunk_vector_enabled": True,
        "bm25_index_enabled": True,
        "kg_enabled": False,
        "event_vector_enabled": False,
        "entity_vector_enabled": False,
        **patch,
        "chunk_python_plugin": chunk_ref,
    }
    if governance_ref:
        pipeline["governance_python_plugin"] = governance_ref
    if kg_ref:
        pipeline["kg_enabled"] = True
        pipeline["event_vector_enabled"] = True
        pipeline["entity_vector_enabled"] = True
        pipeline["kg_python_plugin"] = kg_ref
    return pipeline


def build_upload_form(
    file: CorpusFile,
    *,
    dataset_id: str,
    chunk_plugin_ref: str,
    pipeline_patch: dict[str, Any] | None = None,
    governance_plugin_ref: str | None = None,
    kg_plugin_ref: str | None = None,
) -> dict[str, str]:
    pipeline = build_plugin_pipeline(
        chunk_plugin_ref=chunk_plugin_ref,
        pipeline_patch=pipeline_patch,
        governance_plugin_ref=governance_plugin_ref,
        kg_plugin_ref=kg_plugin_ref,
    )
    metadata = {
        "corpus_closed_loop": True,
        "source_rel_path": file.rel_path,
        "plugin_ref": str(chunk_plugin_ref).strip(),
    }
    return {
        "dataset_id": str(dataset_id),
        "parser_backend": "auto",
        "chunk_strategy": "langchain_recursive",
        "pipeline": json.dumps(pipeline, ensure_ascii=False, separators=(",", ":")),
        "user_metadata": json.dumps(metadata, ensure_ascii=False, separators=(",", ":")),
    }


def create_dataset(
    client: LiveApiClient,
    *,
    name: str,
    chunk_plugin_ref: str,
    pipeline_patch: dict[str, Any] | None = None,
    governance_plugin_ref: str | None = None,
    kg_plugin_ref: str | None = None,
) -> str:
    payload = {
        "name": name,
        "description": "Automated plugin corpus closed-loop smoke dataset.",
        "default_parser_backend": "auto",
        "default_chunk_strategy": "langchain_recursive",
        "pipeline": build_plugin_pipeline(
            chunk_plugin_ref=chunk_plugin_ref,
            pipeline_patch=pipeline_patch,
            governance_plugin_ref=governance_plugin_ref,
            kg_plugin_ref=kg_plugin_ref,
        ),
        "rag_defaults": {
            "top_k": 10,
            "score_threshold": 0.0,
            "retrieval_mode": "hybrid",
            "enable_reranker": False,
        },
    }
    response = client.json("POST", "/api/v1/datasets/", payload=payload)
    dataset_id = str(response.get("id") or "").strip()
    if not dataset_id:
        raise RuntimeError(f"dataset create response missing id: {json.dumps(response, ensure_ascii=False)[:800]}")
    return dataset_id


def upload_corpus_files(
    client: CorpusApiClient,
    files: list[CorpusFile],
    *,
    dataset_id: str,
    chunk_plugin_ref: str,
    pipeline_patch: dict[str, Any] | None = None,
    governance_plugin_ref: str | None = None,
    kg_plugin_ref: str | None = None,
) -> list[UploadedDocument]:
    uploaded: list[UploadedDocument] = []
    for file in files:
        form = build_upload_form(
            file,
            dataset_id=dataset_id,
            chunk_plugin_ref=chunk_plugin_ref,
            pipeline_patch=pipeline_patch,
            governance_plugin_ref=governance_plugin_ref,
            kg_plugin_ref=kg_plugin_ref,
        )
        payload = client.upload_file("/api/v1/documents/upload", data=form, file=file)
        doc_id = str(payload.get("id") or "").strip()
        if not doc_id:
            raise RuntimeError(f"upload response missing document id for {file.rel_path}")
        uploaded.append(
            UploadedDocument(
                document_id=doc_id,
                file=file,
                upload_status=str(payload.get("status") or ""),
            )
        )
    return uploaded


def wait_for_uploaded_documents(
    client: LiveApiClient,
    uploaded: list[UploadedDocument],
    *,
    timeout_sec: float,
    poll_interval_sec: float,
) -> list[dict[str, Any]]:
    deadline = time.monotonic() + float(timeout_sec)
    pending = {item.document_id: item for item in uploaded}
    final: dict[str, dict[str, Any]] = {}

    while pending and time.monotonic() < deadline:
        for doc_id, item in list(pending.items()):
            detail = client.json("GET", f"/api/v1/documents/{doc_id}")
            status = str(detail.get("status") or "").strip().lower()
            if status not in TERMINAL_STATUSES:
                continue

            if status != "completed":
                raise RuntimeError(f"{item.file.rel_path} ended with status={status}: {json.dumps(detail, ensure_ascii=False)[:800]}")

            chunks = client.json("GET", f"/api/v1/documents/{doc_id}/chunks", query={"limit": 2000})
            chunk_total = int(chunks.get("total") or 0)
            if item.file.size > 0 and chunk_total <= 0:
                raise RuntimeError(f"{item.file.rel_path} completed without chunks")

            final[doc_id] = {
                "document_id": doc_id,
                "source_rel_path": item.file.rel_path,
                "filename": detail.get("filename"),
                "status": status,
                "chunk_total": chunk_total,
                "file_size": detail.get("file_size"),
                "parser_backend": (detail.get("doc_metadata") or detail.get("metadata") or {}).get("parser_backend"),
                "pipeline_hash": (detail.get("doc_metadata") or detail.get("metadata") or {}).get("pipeline_hash"),
            }
            pending.pop(doc_id, None)

        if pending:
            time.sleep(max(0.0, float(poll_interval_sec)))

    if pending:
        sample = [item.file.rel_path for item in list(pending.values())[:5]]
        raise RuntimeError(f"document processing timed out for {len(pending)} documents: {sample}")

    return [final[item.document_id] for item in uploaded]


def run_corpus_closed_loop_smoke(
    *,
    client: CorpusApiClient,
    source_dir: Path,
    dataset_id: str,
    dataset_name: str,
    chunk_plugin_ref: str,
    pipeline_patch: dict[str, Any] | None,
    governance_plugin_ref: str | None = None,
    kg_plugin_ref: str | None = None,
    extensions: str,
    skip_empty: bool,
    max_files: int,
    max_files_per_group: int,
    sample_group_depth: int,
    include_root_name: bool,
    include_hidden: bool,
    upload_batch_size: int,
    processing_timeout_sec: float,
    poll_interval_sec: float,
    golden_max_items: int,
    golden_max_chunks: int,
    regression_top_k: int,
    overwrite_goldens: bool,
    regression_score_threshold: float = 0.0,
) -> CorpusClosedLoopResult:
    files, skipped = discover_corpus_files(
        source_dir,
        extensions=extensions,
        skip_empty=skip_empty,
        max_files=max_files,
        max_files_per_group=max_files_per_group,
        sample_group_depth=sample_group_depth,
        include_root_name=include_root_name,
        include_hidden=include_hidden,
    )
    if not files:
        raise RuntimeError(f"no supported corpus files found under {source_dir}")
    _progress(f"discovered files={len(files)} skipped={len(skipped)} source_dir={source_dir}")

    resolved_dataset_id = str(dataset_id or "").strip()
    if not resolved_dataset_id:
        _progress(f"creating dataset name={dataset_name}")
        resolved_dataset_id = create_dataset(
            client,
            name=dataset_name,
            chunk_plugin_ref=chunk_plugin_ref,
            pipeline_patch=pipeline_patch,
            governance_plugin_ref=governance_plugin_ref,
            kg_plugin_ref=kg_plugin_ref,
        )
        _progress(f"created dataset={resolved_dataset_id}")
    else:
        _progress(f"using dataset={resolved_dataset_id}")

    uploaded: list[UploadedDocument] = []
    documents: list[dict[str, Any]] = []
    batch_size = max(0, int(upload_batch_size or 0))
    if batch_size <= 0:
        _progress(f"uploading files={len(files)} batch=all")
        uploaded = upload_corpus_files(
            client,
            files,
            dataset_id=resolved_dataset_id,
            chunk_plugin_ref=chunk_plugin_ref,
            pipeline_patch=pipeline_patch,
            governance_plugin_ref=governance_plugin_ref,
            kg_plugin_ref=kg_plugin_ref,
        )
        _progress(f"waiting uploaded={len(uploaded)} batch=all")
        documents = wait_for_uploaded_documents(
            client,
            uploaded,
            timeout_sec=processing_timeout_sec,
            poll_interval_sec=poll_interval_sec,
        )
    else:
        for start in range(0, len(files), batch_size):
            batch = files[start : start + batch_size]
            batch_no = start // batch_size + 1
            _progress(f"uploading batch {batch_no} files={len(batch)}/{len(files)}")
            batch_uploaded = upload_corpus_files(
                client,
                batch,
                dataset_id=resolved_dataset_id,
                chunk_plugin_ref=chunk_plugin_ref,
                pipeline_patch=pipeline_patch,
                governance_plugin_ref=governance_plugin_ref,
                kg_plugin_ref=kg_plugin_ref,
            )
            uploaded.extend(batch_uploaded)
            _progress(f"waiting batch {batch_no} uploaded={len(batch_uploaded)}")
            documents.extend(
                wait_for_uploaded_documents(
                    client,
                    batch_uploaded,
                    timeout_sec=processing_timeout_sec,
                    poll_interval_sec=poll_interval_sec,
                )
            )
            _progress(f"completed batch {batch_no} documents={len(documents)}/{len(files)}")
    _progress(f"golden regression starting dataset={resolved_dataset_id} uploaded={len(uploaded)}")
    golden: ClosedLoopResult = run_closed_loop_smoke(
        client=client,
        dataset_id=resolved_dataset_id,
        plugin_ref=chunk_plugin_ref,
        max_items=golden_max_items,
        max_chunks=golden_max_chunks,
        include_unmarked_chunks=False,
        overwrite=overwrite_goldens,
        poll_timeout_sec=processing_timeout_sec,
        poll_interval_sec=poll_interval_sec,
        regression_top_k=regression_top_k,
        regression_score_threshold=regression_score_threshold,
    )
    _progress(f"golden regression completed run={golden.run_id} cases={len(golden.case_ids)}")
    return CorpusClosedLoopResult(
        dataset_id=resolved_dataset_id,
        source_dir=str(source_dir),
        uploaded_count=len(uploaded),
        skipped=skipped,
        documents=documents,
        golden=asdict(golden),
    )


def _default_dataset_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"Plugin Corpus Closed Loop {stamp}"


def parse_pipeline_patch_json(raw: str | None) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"--pipeline-patch-json must be valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError("--pipeline-patch-json must decode to a JSON object")
    return _reject_pipeline_patch_activation_refs(
        value,
        label="--pipeline-patch-json",
    )


def _reject_pipeline_patch_activation_refs(raw: dict[str, Any] | None, *, label: str) -> dict[str, Any]:
    patch = dict(raw or {})
    activation_refs = sorted(key for key in patch if key in PLUGIN_ACTIVATION_REF_KEYS)
    if activation_refs:
        joined = ", ".join(activation_refs)
        raise RuntimeError(f"{label} must not set plugin activation refs: {joined}")
    return patch


def _plugin_item_for_ref(plugin_list: dict[str, Any], plugin_ref: str) -> dict[str, Any]:
    target = str(plugin_ref or "").strip()
    if not target:
        raise RuntimeError("plugin ref is required to resolve plugin config")
    items = plugin_list.get("items") if isinstance(plugin_list, dict) else []
    if not isinstance(items, list):
        raise RuntimeError("plugin list response must contain items[]")

    for item in items:
        if not isinstance(item, dict):
            continue
        refs = item.get("refs")
        if not isinstance(refs, dict):
            continue
        if target not in {str(value or "").strip() for value in refs.values()}:
            continue
        return dict(item)
    raise RuntimeError(f"plugin ref not found in /api/v1/pipeline/plugins: {target}")


def _suggested_pipeline_patch_from_item(item: dict[str, Any]) -> dict[str, Any]:
    patch = item.get("suggested_pipeline_patch")
    if patch is None:
        return {}
    if not isinstance(patch, dict):
        raise RuntimeError("plugin suggested_pipeline_patch must be a JSON object")
    return dict(patch)


def _registered_stage_ref(refs: dict[str, Any], stage: str) -> str:
    ref = str(refs.get(stage) or "").strip()
    if not ref:
        return ""
    match = REGISTERED_STAGE_PLUGIN_REF_RE.fullmatch(ref)
    if not match or match.group("stage") != stage:
        raise RuntimeError(f"plugin refs.{stage} must be a registered {stage} plugin ref")
    return ref


def suggested_pipeline_patch_for_ref(plugin_list: dict[str, Any], plugin_ref: str) -> dict[str, Any]:
    return _suggested_pipeline_patch_from_item(_plugin_item_for_ref(plugin_list, plugin_ref))


def resolve_plugin_pipeline_for_run(
    client: Any,
    *,
    chunk_plugin_ref: str,
    pipeline_patch_json: str | None,
) -> dict[str, Any]:
    raw = str(pipeline_patch_json or "").strip()
    item = _plugin_item_for_ref(
        client.json("GET", "/api/v1/pipeline/plugins"),
        chunk_plugin_ref,
    )
    refs = item.get("refs") if isinstance(item.get("refs"), dict) else {}
    return {
        "pipeline_patch": parse_pipeline_patch_json(raw) if raw else _suggested_pipeline_patch_from_item(item),
        "governance_plugin_ref": _registered_stage_ref(refs, "governance"),
        "kg_plugin_ref": _registered_stage_ref(refs, "kg"),
    }


def resolve_pipeline_patch_for_run(
    client: Any,
    *,
    chunk_plugin_ref: str,
    pipeline_patch_json: str | None,
) -> dict[str, Any]:
    return dict(
        resolve_plugin_pipeline_for_run(
            client,
            chunk_plugin_ref=chunk_plugin_ref,
            pipeline_patch_json=pipeline_patch_json,
        ).get("pipeline_patch")
        or {}
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run plugin-backed corpus ingest + Golden regression smoke.")
    parser.add_argument("--source-dir", required=True, help="Local corpus directory to upload recursively.")
    parser.add_argument("--dataset-id", default="", help="Existing dataset UUID. If omitted, an isolated dataset is created.")
    parser.add_argument("--dataset-name", default="", help="Dataset name when --dataset-id is omitted.")
    parser.add_argument("--plugin-ref", required=True, help="Registered chunk plugin ref.")
    parser.add_argument(
        "--pipeline-patch-json",
        default="",
        help="Optional DocumentPipelineOptions JSON object. Omit to use the plugin manifest suggested_pipeline_patch.",
    )
    parser.add_argument("--extensions", default=",".join(DEFAULT_EXTENSIONS))
    parser.add_argument("--include-empty-files", action="store_true", help="Upload zero-byte files instead of reporting them as skipped.")
    parser.add_argument(
        "--include-source-root-name",
        action="store_true",
        help="Prefix uploaded source_rel_path values with the source directory name.",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include files under hidden directories and hidden files. Defaults to false to skip editor/conversion artifacts.",
    )
    parser.add_argument("--max-files", type=int, default=0, help="Limit uploaded files for smoke debugging. 0 means all.")
    parser.add_argument(
        "--max-files-per-group",
        type=int,
        default=0,
        help=(
            "Limit uploaded files per first-level corpus group after filtering. "
            "0 means no per-group sampling. Grouping uses paths relative to --source-dir, "
            "so --include-source-root-name does not collapse every file into one group."
        ),
    )
    parser.add_argument(
        "--sample-group-depth",
        type=int,
        default=1,
        help="Number of path levels under --source-dir used for --max-files-per-group grouping.",
    )
    parser.add_argument(
        "--upload-batch-size",
        type=int,
        default=0,
        help="Upload all files before waiting when 0; otherwise upload and wait for this many files at a time.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("MIMIRQ_API_BASE_URL") or os.getenv("BACKEND_BASE_URL") or "http://127.0.0.1:8000",
    )
    parser.add_argument("--tenant-id", default=os.getenv("MIMIRQ_TENANT_ID") or DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default=os.getenv("MIMIRQ_ACCOUNT_ID") or "demo")
    parser.add_argument("--user-id", default=os.getenv("MIMIRQ_USER_ID") or "demo")
    parser.add_argument("--bearer", default=os.getenv("MIMIRQ_API_TOKEN") or os.getenv("AUTH_TOKEN") or "")
    parser.add_argument("--timeout", type=float, default=float(os.getenv("MIMIRQ_API_TIMEOUT_SEC") or "120"))
    parser.add_argument("--processing-timeout", type=float, default=float(os.getenv("MIMIRQ_PROCESSING_TIMEOUT_SEC") or "1800"))
    parser.add_argument("--poll-interval", type=float, default=float(os.getenv("MIMIRQ_POLL_INTERVAL_SEC") or "2"))
    parser.add_argument("--golden-max-items", type=int, default=200)
    parser.add_argument("--golden-max-chunks", type=int, default=5000)
    parser.add_argument(
        "--regression-top-k",
        type=int,
        default=20,
        help="Retrieval-only Golden regression top_k/citation evaluation window.",
    )
    parser.add_argument(
        "--regression-score-threshold",
        type=float,
        default=0.0,
        help="Retrieval-only Golden regression score_threshold.",
    )
    parser.add_argument("--overwrite-goldens", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    client = CorpusApiClient(
        base_url=str(args.base_url),
        tenant_id=str(args.tenant_id),
        account_id=str(args.account_id),
        user_id=str(args.user_id),
        bearer=str(args.bearer or ""),
        timeout_sec=float(args.timeout),
    )
    try:
        plugin_pipeline = resolve_plugin_pipeline_for_run(
            client,
            chunk_plugin_ref=str(args.plugin_ref or "").strip(),
            pipeline_patch_json=str(args.pipeline_patch_json or ""),
        )
        result = run_corpus_closed_loop_smoke(
            client=client,
            source_dir=Path(args.source_dir).expanduser().resolve(),
            dataset_id=str(args.dataset_id or ""),
            dataset_name=str(args.dataset_name or "") or _default_dataset_name(),
            chunk_plugin_ref=str(args.plugin_ref or "").strip(),
            pipeline_patch=dict(plugin_pipeline.get("pipeline_patch") or {}),
            governance_plugin_ref=str(plugin_pipeline.get("governance_plugin_ref") or ""),
            kg_plugin_ref=str(plugin_pipeline.get("kg_plugin_ref") or ""),
            extensions=str(args.extensions or ""),
            skip_empty=not bool(args.include_empty_files),
            max_files=int(args.max_files),
            max_files_per_group=int(args.max_files_per_group),
            sample_group_depth=int(args.sample_group_depth),
            include_root_name=bool(args.include_source_root_name),
            include_hidden=bool(args.include_hidden),
            upload_batch_size=int(args.upload_batch_size or 0),
            processing_timeout_sec=float(args.processing_timeout),
            poll_interval_sec=float(args.poll_interval),
            golden_max_items=int(args.golden_max_items),
            golden_max_chunks=int(args.golden_max_chunks),
            regression_top_k=int(args.regression_top_k),
            regression_score_threshold=float(args.regression_score_threshold),
            overwrite_goldens=bool(args.overwrite_goldens),
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[plugin-corpus-smoke] ERR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
