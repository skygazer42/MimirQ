
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from langchain_core.documents import Document

from app.rag.pipeline_plugins.contracts import (
    PipelinePluginContractError,
    apply_metadata_schema_views,
    apply_retrieval_text_schema,
    strip_reserved_platform_metadata_views,
    validate_documents_metadata,
    validate_kg_events_metadata,
    validate_no_reserved_platform_metadata_views,
)
from app.rag.pipeline_plugins.golden_drafts import build_golden_draft_bundle_from_chunks
from app.rag.pipeline_plugins.registry import (
    PLUGIN_TEST_REPORT_FILENAME,
    PipelinePluginRegistryError,
    describe_plugin_dir,
    load_descriptor_stage_callable,
)
from app.rag.pipeline_plugins.runtime import (
    PythonPipelinePluginError,
    _coerce_documents,
    _coerce_kg_events,
    _invoke_plugin,
)

_LOCAL_GOLDEN_DATASET_ID = UUID("00000000-0000-0000-0000-000000000000")
_LOCAL_GOLDEN_NAMESPACE = UUID("0a6fd4d8-a590-4c9d-87de-c2c845ab8c48")


def _coerce_input_document(item: Any) -> Document:
    if isinstance(item, Document):
        return item
    if isinstance(item, str):
        return Document(page_content=item, metadata={})
    if isinstance(item, dict):
        content = item.get("page_content")
        if content is None:
            content = item.get("content")
        if content is None:
            content = item.get("text")
        metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
        return Document(page_content=str(content or ""), metadata=dict(metadata))
    raise PipelinePluginRegistryError(f"unsupported input document item: {type(item).__name__}")


def load_plugin_test_input(input_path: str | Path) -> list[Document]:
    path = Path(input_path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("documents"), list):
        raw_items = raw["documents"]
    elif isinstance(raw, list):
        raw_items = raw
    else:
        raise PipelinePluginRegistryError("plugin test input must be a JSON array or {documents: [...]}")
    return [_coerce_input_document(item) for item in raw_items]


class _LocalGoldenChunk:
    def __init__(self, *, document_id: UUID, chunk_id: UUID, chunk_index: int, content: str, metadata: dict[str, Any]):
        self.document_id = document_id
        self.id = chunk_id
        self.chunk_index = chunk_index
        self.content = content
        self.doc_metadata = metadata


def _local_golden_chunks(documents: list[Document], *, plugin_id: str, version: str) -> list[_LocalGoldenChunk]:
    chunks: list[_LocalGoldenChunk] = []
    for index, doc in enumerate(documents or []):
        seed = f"{plugin_id}@{version}:{index}:{doc.page_content or ''}"
        document_id = uuid5(_LOCAL_GOLDEN_NAMESPACE, f"doc:{seed}")
        chunk_id = uuid5(_LOCAL_GOLDEN_NAMESPACE, f"chunk:{seed}")
        chunks.append(
            _LocalGoldenChunk(
                document_id=document_id,
                chunk_id=chunk_id,
                chunk_index=index,
                content=str(doc.page_content or ""),
                metadata=dict(doc.metadata or {}),
            )
        )
    return chunks


def _build_golden_draft_report(
    *,
    descriptor: Any,
    output_documents: list[Document],
    max_sample_questions: int = 5,
) -> dict[str, Any]:
    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=_LOCAL_GOLDEN_DATASET_ID,
        chunks=_local_golden_chunks(output_documents, plugin_id=descriptor.id, version=descriptor.version),
        golden_rules=descriptor.golden_rules,
        plugin_id=descriptor.id,
        plugin_version=descriptor.version,
        plugin_ref=descriptor.refs["chunk"],
        plugin_package_hash=descriptor.package_hash,
        max_items=50,
    )
    items = bundle.get("items") if isinstance(bundle, dict) else []
    items = items if isinstance(items, list) else []
    questions = []
    for item in items[: max(0, int(max_sample_questions or 0))]:
        if isinstance(item, dict) and str(item.get("question") or "").strip():
            questions.append(str(item.get("question")).strip())
    return {
        "passed": bool(items),
        "items_total": len(items),
        "sample_questions": questions,
    }


def _run_plugin_stages(
    *,
    descriptor: Any,
    input_documents: list[Document],
    stages: list[str] | tuple[str, ...],
    params: dict[str, Any] | None = None,
) -> tuple[list[Document], dict[str, Any], bool]:
    current_documents = list(input_documents)
    stage_reports: dict[str, Any] = {}
    passed = True
    for stage in stages:
        if stage not in descriptor.entries:
            raise PipelinePluginRegistryError(f"plugin has no {stage} entry")
        func = load_descriptor_stage_callable(descriptor, stage)
        context = {"stage": stage, "plugin_id": descriptor.id, "plugin_version": descriptor.version}
        plugin_input_documents = strip_reserved_platform_metadata_views(current_documents)
        try:
            result = _invoke_plugin(
                func,
                documents=plugin_input_documents,
                params=dict(params or {}),
                context=context,
            )
        except Exception as exc:  # noqa: BLE001
            validation = {"ok": False, "checked": 0, "errors": [{"reason": str(exc) or type(exc).__name__}]}
            passed = False
            if stage == "kg":
                stage_reports[stage] = {
                    "passed": False,
                    "input_count": len(current_documents),
                    "output_count": 0,
                    "output_chars": 0,
                    "kg_validation": validation,
                }
            else:
                stage_reports[stage] = {
                    "passed": False,
                    "input_count": len(current_documents),
                    "output_count": 0,
                    "output_chars": 0,
                    "metadata_validation": validation,
                }
            current_documents = []
            continue
        if stage == "kg":
            events = []
            try:
                events = _coerce_kg_events(result, documents=plugin_input_documents, plugin_ref=descriptor.refs[stage])
                kg_validation = validate_kg_events_metadata(events, metadata_schema=descriptor.metadata_schema)
                if current_documents and not events:
                    kg_validation = {
                        "ok": False,
                        "checked": 0,
                        "errors": [{"reason": "kg stage emitted no events"}],
                    }
            except (PipelinePluginContractError, PythonPipelinePluginError) as exc:
                kg_validation = {
                    "ok": False,
                    "checked": 0,
                    "errors": [{"reason": str(exc)}],
                }
            if not kg_validation["ok"]:
                passed = False
            stage_reports[stage] = {
                "passed": bool(kg_validation["ok"]),
                "input_count": len(current_documents),
                "output_count": len(events),
                "output_chars": sum(len(event.content or "") for event in events),
                "kg_validation": kg_validation,
            }
            continue
        output_documents = []
        try:
            output_documents = _coerce_documents(result, stage=stage, plugin_ref=descriptor.refs[stage])
            for document in output_documents:
                validate_no_reserved_platform_metadata_views(document.metadata, field_label=f"{stage} plugin metadata")
            metadata_validation = validate_documents_metadata(
                output_documents,
                metadata_schema=descriptor.metadata_schema,
                stage=stage,
            )
        except (PipelinePluginContractError, PythonPipelinePluginError) as exc:
            metadata_validation = {"ok": False, "checked": len(output_documents), "errors": [{"reason": str(exc)}]}
        if not metadata_validation.get("ok"):
            passed = False
        else:
            try:
                output_documents = apply_metadata_schema_views(
                    output_documents,
                    metadata_schema=descriptor.metadata_schema,
                    stage=stage,
                )
                output_documents = apply_retrieval_text_schema(
                    output_documents,
                    retrieval_text_schema=descriptor.retrieval_text_schema,
                    stage=stage,
                )
            except PipelinePluginContractError as exc:
                passed = False
                metadata_validation = {
                    "ok": False,
                    "checked": len(output_documents),
                    "errors": [{"reason": str(exc)}],
                }
        stage_reports[stage] = {
            "passed": bool(metadata_validation.get("ok")),
            "input_count": len(current_documents),
            "output_count": len(output_documents),
            "output_chars": sum(len(doc.page_content or "") for doc in output_documents),
            "metadata_validation": metadata_validation,
        }
        current_documents = output_documents
    return current_documents, stage_reports, passed


def run_pipeline_plugin_test(
    plugin_dir: str | Path,
    *,
    input_path: str | Path,
    stages: list[str] | tuple[str, ...],
    params: dict[str, Any] | None = None,
    write_report: bool = True,
) -> dict[str, Any]:
    descriptor = describe_plugin_dir(Path(plugin_dir), require_test_report=False)
    input_documents = load_plugin_test_input(input_path)
    report: dict[str, Any] = {
        "plugin_id": descriptor.id,
        "version": descriptor.version,
        "package_hash": descriptor.package_hash,
        "tested_at": datetime.now(UTC).isoformat(),
        "passed": True,
        "stages": {},
    }
    current_documents, stage_reports, stages_passed = _run_plugin_stages(
        descriptor=descriptor,
        input_documents=input_documents,
        stages=stages,
        params=params,
    )
    report["passed"] = bool(stages_passed)
    report["stages"] = stage_reports

    if descriptor.golden_rules and "chunk" in report["stages"]:
        golden_report = _build_golden_draft_report(descriptor=descriptor, output_documents=current_documents)
        report["golden_draft"] = golden_report
        if not golden_report.get("passed"):
            report["passed"] = False

    if write_report:
        report_path = Path(plugin_dir) / PLUGIN_TEST_REPORT_FILENAME
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def build_pipeline_plugin_golden_draft_from_sample(
    plugin_dir: str | Path,
    *,
    input_path: str | Path,
    dataset_id: UUID,
    stages: list[str] | tuple[str, ...] | None = None,
    params: dict[str, Any] | None = None,
    max_items: int = 500,
) -> dict[str, Any]:
    descriptor = describe_plugin_dir(Path(plugin_dir), require_test_report=False)
    if not isinstance(descriptor.golden_rules, dict) or descriptor.golden_rules.get("schema") != "mimirq.golden_rules.v1":
        raise PipelinePluginRegistryError("plugin has no mimirq.golden_rules.v1 golden rules")
    selected_stages = list(stages or [stage for stage in ("governance", "chunk") if stage in descriptor.entries])
    if "chunk" not in selected_stages:
        raise PipelinePluginRegistryError("golden draft generation requires the chunk stage")
    output_documents, stage_reports, stages_passed = _run_plugin_stages(
        descriptor=descriptor,
        input_documents=load_plugin_test_input(input_path),
        stages=selected_stages,
        params=params,
    )
    if not stages_passed:
        failed = [stage for stage, info in stage_reports.items() if isinstance(info, dict) and info.get("passed") is not True]
        raise PipelinePluginRegistryError(f"plugin stage validation failed: {', '.join(failed) or 'unknown'}")
    bundle = build_golden_draft_bundle_from_chunks(
        dataset_id=dataset_id,
        chunks=_local_golden_chunks(output_documents, plugin_id=descriptor.id, version=descriptor.version),
        golden_rules=descriptor.golden_rules,
        plugin_id=descriptor.id,
        plugin_version=descriptor.version,
        plugin_ref=descriptor.refs["chunk"],
        plugin_package_hash=descriptor.package_hash,
        max_items=max_items,
    )
    bundle["review_only"] = True
    bundle["reference_source_mode"] = "local_sample_synthetic"
    bundle["note"] = (
        "Local sample golden drafts use synthetic document_id/chunk_id values. "
        "Use them for review or CI fixtures; generate/import dataset goldens from indexed chunks for production."
    )
    for item in bundle.get("items") or []:
        if not isinstance(item, dict):
            continue
        extra = item.get("extra")
        if not isinstance(extra, dict):
            extra = {}
        extra["reference_source_mode"] = "local_sample_synthetic"
        extra["review_only"] = True
        item["extra"] = extra
    return bundle


__all__ = ["build_pipeline_plugin_golden_draft_from_sample", "load_plugin_test_input", "run_pipeline_plugin_test"]
