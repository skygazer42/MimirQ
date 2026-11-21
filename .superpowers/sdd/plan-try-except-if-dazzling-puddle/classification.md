# 本轮逐处定性与验收

| 当前位置（函数入口） | 定性/裁决 | 证据组 |
|---|---|---|
| `app/api/v1/datasets.py:130` `_commit_dataset_audit` | 8 calls: audit fail-open / rollback+traceback | Desktop acceptance |
| `app/api/v1/datasets.py:244` `_mark_dataset_profile_scan_run_failed` | enqueue compensation; caller still raises 503 | API regression |
| `app/api/v1/datasets.py:2378` `_run_deep_scan_background` | background failure; primary logged before rollback+compensation | API regression |
| `app/api/v1/document_versions.py:505` `delete_document_version` | authoritative KG cleanup: rollback+raise; route returns 500 | Desktop acceptance |
| `app/api/v1/document_versions.py:65` `_commit_document_version_audit` | audit fail-open; 2 calls | Desktop acceptance |
| `app/services/document_qa_service.py:745` `_update_document_chunk_stats` | generated chunks already committed; stats projection warning+rollback | Desktop acceptance |
| `app/api/v1/ingestion_runs.py:48` `_commit_ingestion_run_audit` | 4 audit calls; no new primary write swallowing | Desktop acceptance |
| `app/api/v1/dataset_precheck.py:167` `_mark_precheck_scan_run_failed` | compensation; enqueue caller still raises 503 | Desktop acceptance |
| `app/api/v1/dataset_precheck.py:212` `_run_precheck_scan_background` | background primary failure logged; rollback before compensation | API regression |
| `app/services/rag_config_template_resolver.py:34` `record_rag_config_template_usage` | optional usage counter; rag.py and chat_bootstrap_runtime.py use same owner | Desktop acceptance |
| `app/rag/kg/api/routes_support/extraction.py:164` `_audit_kg_extraction` | audit fail-open with rollback+traceback | Desktop acceptance |
| `app/rag/kg/api/routes.py:2376` `delete_kg_for_document` | locally documented best-effort relation cleanup and audit; both traceback tested | Desktop acceptance + KG relation red |
| `app/api/v1/audit.py:333` `purge_audit_logs` | post-purge audit only; primary service commit=True propagates | API regression |
| `app/api/v1/audit.py:480` `_delete_audit_logs_by_id` | post-delete audit only; primary service commit=True propagates | API regression |
| `app/api/v1/audit.py:760` `_audit_access_graph_export` | read-only result audit fail-open | API regression |
| `app/api/v1/audit.py:908` `access_graph_summary` | read-only result audit fail-open | API regression |
| `app/api/v1/evidence.py:215` `_audit_reference_repair_enqueue` | post-enqueue audit fail-open | API regression |
| `app/api/v1/evaluations.py:1843` `purge_ragas_regression_runs` | post-purge audit fail-open; primary service commit=True propagates | API regression |
| `app/rag/kg/extraction/extractor.py:1187` `_resolve_prompt_template_content` | optional prompt usage: rollback+traceback | service regression |
| `app/rag/kg/extraction/extractor.py:3888` `_writeback_document_metadata` | post-extraction metrics projection: rollback+traceback | service regression |
| `app/rag/evaluation/ragas.py:299` `_commit_regression_progress` | intermediate progress projection: rollback+traceback | service regression |
| `app/parsing/processors/support/recovery.py:201` `apply_pending_retry_cleanup` | explicit deferred failure; marker restored; traceback added | service regression |
| `app/services/connector_execution/confluence.py:778` `_patch_confluence_page_document_metadata` | required connector identity metadata: rollback+raise | service regression |
| `app/services/document_batch_ingestion.py:730` `_run_precheck_scan` | precheck_only rollback+raise; optional precheck_first rollback+warning+None | service regression |
| `app/services/document_batch_ingestion.py:800` `_run_precheck_scan_job` | compensation rollback+traceback; original scan failure rethrown | service regression |
| `app/tasks/jobs.py:666` `evidence_reference_sources_repair_job` | documented job-level audit; rollback+traceback, primary result retained | worker regression |
| `app/tasks/jobs.py:1816` `_finalize_kg_job_success` | dataset cache revision is authoritative completion write; rollback+raise | worker regression |
| `app/rag/kg/api/routes.py:1545` `create_kg_entity_alias` | primary commit already propagated; rollback failure now also propagates with original context | worker regression, both error cases |
| `app/rag/kg/api/routes.py:1630` `delete_kg_entity_alias` | primary commit already propagated; rollback failure now also propagates with original context | worker regression, both error cases |
| `app/rag/kg/api/routes.py:1815` `create_kg_predicate_ontology` | primary commit already propagated; rollback failure now also propagates with original context | worker regression, both error cases |
| `app/rag/kg/api/routes.py:1886` `update_kg_predicate_ontology` | primary commit already propagated; rollback failure now also propagates with original context | worker regression, both error cases |
| `app/rag/kg/api/routes.py:1944` `delete_kg_predicate_ontology` | primary commit already propagated; rollback failure now also propagates with original context | worker regression, both error cases |

## 共享 owner 的全部调用点

| 调用位置 | 调用方 | action / 用途 |
|---|---|---|
| `app/api/v1/datasets.py:1180` | `create_dataset` | `'dataset.create'` |
| `app/api/v1/datasets.py:1573` | `update_dataset` | `'dataset.update'` |
| `app/api/v1/datasets.py:1687` | `import_dataset_config` | `'dataset.config.import'` |
| `app/api/v1/datasets.py:1728` | `put_dataset_retrieval_audit` | `'dataset.retrieval_audit.put'` |
| `app/api/v1/datasets.py:1794` | `clone_dataset` | `'dataset.clone'` |
| `app/api/v1/datasets.py:1949` | `_record_dataset_purge_audit` | `'dataset.purge'` |
| `app/api/v1/datasets.py:2990` | `_record_dataset_documents_export_audit` | `'dataset.documents.export'` |
| `app/api/v1/datasets.py:3086` | `_record_dataset_bundle_export_audit` | `'dataset.export_bundle'` |
| `app/api/v1/ingestion_runs.py:177` | `_audit_replay_creation` | `'ingestion.run.replay'` |
| `app/api/v1/ingestion_runs.py:343` | `export_ingestion_run_json` | `'ingestion.run.export_json'` |
| `app/api/v1/ingestion_runs.py:382` | `export_ingestion_run_html` | `'ingestion.run.export_html'` |
| `app/api/v1/ingestion_runs.py:444` | `compare_ingestion_runs` | `'ingestion.run.compare'` |
| `app/api/v1/document_versions.py:491` | `activate_document_version` | `'document.version.activate'` |
| `app/api/v1/document_versions.py:616` | `delete_document_version` | `'document.version.delete'` |
| `app/api/v1/rag.py:347` | `_resolve_preview_rag_template_meta` | `optional RAG usage counter` |
| `app/services/chat_bootstrap_runtime.py:250` | `_resolve_rag_template_runtime` | `optional RAG usage counter` |
