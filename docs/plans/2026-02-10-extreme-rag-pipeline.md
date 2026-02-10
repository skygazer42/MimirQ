# 极致 RAG 管线精细化（数据分析→预处理→解析→治理→切块→KG→评估）Implementation Plan

> 目标：优化 **RAG 管线本身**（不是回答风格），把每个阶段的“数据分布 → 质量信号 → 报告/可观测”做到可复现、可度量、可回归。
>
> 说明：本计划按“每完成一项 = 一次 commit”的粒度执行；全部完成后会按你的要求删除该 plan 文档（保留在 git 历史中）。

## Task List（20）

### A. Chunking：分布与质量门槛（1–10）

1. [ ] 新增 token 维度的 chunking stats（ingest-time 写入文档 metadata，支持 histogram/percentiles）
2. [ ] 新增 chunk coverage 指标（coverage_ratio / overlap_waste_ratio / gap_count 等，ingest-time 写入 metadata）
3. [ ] 抽取 chunk 质量 gate 逻辑为可复用的 service（preview / ingest / 离线脚本共用）
4. [ ] ingestion 写入 chunk_quality_gate（pass/warn/fail + structured reasons），默认只记录不拦截
5. [ ] dataset profile 聚合 token-chunk 分布（chunk-level histogram + doc-level avg tokens/chunk）
6. [ ] dataset profile 聚合 coverage 分布与异常桶（例如 coverage < 98%）
7. [ ] dataset profile 新增 findings：chunk_coverage_low / chunk_quality_fail（可 drill-down）
8. [ ] dataset profile HTML 报告补充 token / coverage 可视化区块
9. [ ] dataset report（/reports）聚合并展示 chunk 质量汇总（gate grade 分布 + 关键计数）
10. [ ] deep scan backfill 支持补齐 token stats / coverage（保守开关，默认不增加成本）

### B. Precheck：入库前“数据分布报告”再强化（11–14）

11. [ ] precheck file record 增加 text_tokens_est（基于样本的 best-effort 估算）
12. [ ] precheck summary 增加 tokens 分布（percentiles + histogram）
13. [ ] precheck HTML 报告补充 tokens 可视化与“入库建议”提示区
14. [ ] precheck → ingestion policy suggestion：补充基于 tokens 分布的 chunk_size 建议（可开关/保守）

### C. KG & Eval：把“可用”升级为“可评估/可汇总”（15–19）

15. [ ] dataset report 增加 KG stats（events/entities/links/entity_types + updated_at；按 ACL 过滤）
16. [ ] dataset report HTML 增加 KG stats 区块
17. [ ] dataset report 增加最新 regression run summary（retrieval gate + ragas summary，best-effort）
18. [ ] dataset report HTML 增加评估 summary 区块（只展示客观指标）
19. [ ] 新增 /reports/datasets/{id}/rag-audit/export-html：合并 profile + governance + chunk + KG + eval 的一页式报告

### D. Docs / Cleanup（20）

20. [ ] 删除已完成的旧 plan 文档（docs/optimization 两份），并更新 docs/README.md；同时删除本 plan 文件

