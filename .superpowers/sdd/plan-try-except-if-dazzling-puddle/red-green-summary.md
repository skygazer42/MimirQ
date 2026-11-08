# 红绿验收摘要

完整原始输出在 progress.md 指定的仓库外证据目录；本页不保存 pytest 堆栈或全量 Ruff 输出。

| 组 | 修复前 | 修复后 | 失败断言原因 |
|---|---|---|---|
| table audit | 3 failed | 14 passed | `test_audit_commit_failure_rolls_back_and_warns` 三参数未 rollback |
| Desktop 八组验收 | 临时旧分支 9 failed | 34 passed, 2 skipped | `test_audit_degradation_has_rollback_and_traceback` 等缺 traceback；版本清理错误返回 204 |
| API 审计/补偿 | 11 failed | 42 passed | `test_api_audit_commit_failure_is_observable` 与后台 scan 组丢原异常/未恢复事务 |
| 服务/解析 | 8 个新例 failed | 17 passed | Confluence 吞 commit；precheck 返回未持久化对象；旁路缺 traceback |
| worker/KG | 7 failed, 5 passed | 22 passed | rollback 错误被吞；KG 完成 commit 失败仍返回成功 |
| precheck 响应/refresh | 4 failed | 36 passed | `test_failed_persisted_scan_remains_linked_in_batch_response` 无 run ID；三类 refresh 未抛错 |
| Phase1B retrieval 限定片 | 9 failed, 2 passed | 11 新例 passed；相关 56 passed, 4 既有 failed | 零权重/容量/阈值回退；必需 None 被伪造零快照 |
| 可选策略建议边界 | 2 failed, 4 passed | 16 passed | `test_optional_policy_failure_rolls_back_and_retains_scan_link` 无异常堆栈/事务恢复 |

已记录的既有失败：retry-queue 三例引用不存在的 `document_processing.settings`；task-lock 两例测试替身参数签名过期；retrieval 四例引用已退出的 `generate_alias_queries`、`get_vector_store`、`_candidate_metadata_from_doc`。具体用例名在 progress.md 各组条目。未据此扩大源码修改范围。
