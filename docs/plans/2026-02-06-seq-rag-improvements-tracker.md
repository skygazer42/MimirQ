# RAG Improvements Tracker (Sequential)

This file is the “restart point”. Open this after a new window/session to see what’s done and what’s next.

**Branch:** `main`  
**Updated:** 2026-02-06  
**Next Up:** Task 25 (plan TBD)

## Checklist (1–30)

- [ ] 1. 回答前置证据门禁（证据不足拒答/追问）
- [ ] 2. 强制引用到 span（每个结论绑定 chunk 精确范围）
- [ ] 3. 检索链路可观测（rewrite/recall/rerank/context/拒答原因可回放）
- [ ] 4. 检索正确率回归集（Recall@K/Answerability）
- [ ] 5. 两阶段检索（Hybrid + 强 reranker，多路融合阈值拒答）
- [ ] 6. Query 分解（子问题独立证据门禁，再合成）
- [ ] 7. 数据录入可验证（connector 连通性/权限/只读自检）
- [ ] 8. （编号缺失于原清单）
- [x] 9. Catalog 增量 diff（schema diff + UI 可视化）
- [ ] 10. （编号缺失于原清单）
- [x] 11. Profiling 隐私阈值（小表/低基数默认不输出可还原统计）
- [x] 12. 画像缓存策略（entitlement_hash + fingerprint + profile_version）
- [x] 13. 解析质量打分（quality score + 人工复核桶）
- [x] 14. 多解析器竞赛（选最优 + 保留对比证据）
- [x] 15. 预处理流水线可复现（transform 版本化 hash + 版本 diff）
- [x] 16. 结构化 chunk（heading path / 列表层级 / 表格标题 元数据）
- [x] 17. 表格/Schema 专用 chunk（表格走 TAG；DB schema 虚拟 doc）
- [ ] 18. （编号缺失于原清单）
- [x] 19. KG 提取带溯源（chunk_id+offset；变更可回滚）
- [x] 20. KG 参与检索（实体链接 -> 结构化过滤）
- [x] 21. 召回策略分桶（按问题类型选 retriever/阈值）
- [x] 22. 生成前 context compression（保留引用，压缩无关句子/字段）
- [x] 23. 生成后 claim-check（逐条证据覆盖，不覆盖则删/降级）
- [x] 24. 不可见即不存在（只根据引用回答；拒答=成功路径）
- [ ] 25. 文档治理规则包（页眉页脚/免责声明/目录噪声/重复段落处理）
- [ ] 26. 端到端压测（ingest→retrieve→answer 吞吐 + P95）
- [ ] 27. 任务队列化（解析/重嵌入/同步：并发上限、取消、断点续跑）
- [ ] 28. 数据集隔离 DB 约束（unique/fk/tenant_id 复合索引）
- [ ] 29. 安全审计默认开启（SQL/连接信息默认隐藏；owner/auditor 脱敏可见）
- [ ] 30. 线上反馈→用例化（一键转回归用例，含检索轨迹）

## Pointers

- Task 9/11/12/13/14: `docs/plans/2026-02-06-db-catalog-virtual-schema-doc-and-observability.md`
- Task 15: `docs/plans/2026-02-06-pipeline-provenance-and-version-diff.md`
- Task 16: `docs/plans/2026-02-06-task16-structured-chunk-metadata.md`
- Task 17: `docs/plans/2026-02-06-task17-table-and-schema-special-chunks.md`
- Task 19: `docs/plans/2026-02-06-task19-kg-provenance-and-rollback.md`
- Task 20: `docs/plans/2026-02-06-task20-kg-assisted-retrieval-filtering.md`
- Task 21: `docs/plans/2026-02-06-task21-recall-strategy-buckets.md`
- Task 22: `docs/plans/2026-02-06-task22-context-compression.md`
- Task 23: `docs/plans/2026-02-06-task23-claim-check.md`
- Task 24: `docs/plans/2026-02-06-task24-visible-evidence-only.md`
