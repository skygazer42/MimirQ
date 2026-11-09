# 本轮列举范围之外的扩展扫描候选

以下由补充 AST 扫描发现，未加入本轮总指挥明确列举的位置集合；仅记录候选，不机械定性或顺手重构。后续 Phase 1A 切片应读取完整调用链再决定失败策略：

- `app/services/document_access_service.py` 的 `update_document_access`：审计 commit 后 rollback，无日志。
- `app/services/document_chunk_operations.py` 的 create/patch/delete 审计 suppress，以及 `_refresh_document_chunk_stats`、`_cleanup_deleted_chunk_kg` 的回滚静默分支。
- `app/services/document_lifecycle_service.py` 的 `patch_document_lifecycle_metadata` 审计提交后静默 rollback。
- `app/services/document_processing_dispatch.py` 的 `mark_document_processing_schedule_failed`：补偿写入有 error，但无 traceback，rollback 还被 suppress。
- `app/services/document_processing_operations.py` 的 `_maybe_skip_unchanged_retry` 审计 warning 无 traceback。
- `app/services/document_qa_service.py` 的 `generate_document_qa` 审计 commit 使用 suppress；Desktop 修复和本轮验收仅覆盖 `_update_document_chunk_stats`。

这些候选不构成本轮列举位置的并发跳过项。本轮没有跳过总指挥指定位置，也没有据此宣称 app 下所有同类缺陷已消除。`document_source_persistence` 的 IntegrityError 去重处理及最终清理后重抛属于另一个真实资源/冲突边界，不因宽捕获计数而删除。


PREVIEW_PARSE_CACHE_VERSION: document_chunk_preview.py:1034/1627 retains .strip() or "v1"; parentheses only removed, whitespace fallback awaits commander decision.
