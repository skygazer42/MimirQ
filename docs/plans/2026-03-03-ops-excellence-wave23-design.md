# Ops Excellence (Wave23) Design: Top-tier Knowledge Base Operations

**Date:** 2026-03-03  
**Scope:** 运维（SRE/平台/生产排障）视角，把 MimirQ 的知识库从“能用/能排障”推进到“可量化、可告警、可回滚、可演练”的顶尖运维闭环。

## 目标（What “Top-tier” Looks Like）

顶尖运维知识库不是“内容多”，而是具备下面闭环能力：

1. **可观测（Observe）**：能回答“现在系统状态如何？”  
   - SLI：延迟 p95/p99、错误率、zero-hit/abstain、ingestion 失败率、队列积压
   - 指标全程 **PII-safe**（hash + 聚合，不回传原 query/文档原文）
2. **可告警（Alert）**：能回答“什么时候需要叫醒人？”  
   - 预置 PrometheusRule / Grafana 模板 + 阈值建议 + Runbook 链接
3. **可定位（Debug）**：能回答“出了问题我怎么最快定位到层级？”  
   - request_id 一键导出诊断包（trace bundle）
   - 配置指纹/对比（retrieval_config_hash + config snapshot）
4. **可止血（Mitigate）**：能回答“怎么先把系统救回来？”  
   - 限流/配额/降级开关（reranker/multi-query/overfetch）
5. **可回滚（Rollback）**：能回答“我怎么回到已知可用状态？”  
   - 配置回滚 + 文档 pipeline 版本回滚 + 发布回滚指导
6. **可治理（Govern）**：能回答“知识库怎么保持新鲜、权威、不过期？”  
   - 文档生命周期（owner/review_due/authority/supersedes）+ stale 报表 + 审计
7. **可演练（Drill）**：能回答“如何持续证明我们真的能恢复？”  
   - smoke test + DR drill + chaos 场景（可选）

## 当前基座（Repo 已具备）

- Health/Ready：`/api/v1/health`、`/api/v1/health/ready`
- Prometheus：`/metrics`（`PROMETHEUS_ENABLED=true` 时）
- Observability admin API：
  - `GET /api/v1/observability/rag-metrics/summary`（JSONL 聚合）
  - `GET /api/v1/observability/ingestion/summary`
  - `GET /api/v1/observability/index-audit`
- Audit log：列表/导出/SIEM 友好 + retention purge + runner
- 数据导出/清理：dataset export / purge、regression runs retention 等
- Runbook：`docs/deployment/runbook.md`（按 ingest → index → retrieval/rerank → LLM 定位）

## 主要差距（运维视角）

1. **Query analytics / zero-hit 监控**：缺少“哪些 query 经常 0 引用/慢/报错”的聚合与可视化
2. **request_id 一键排障能力不足**：缺少“把这次请求相关 trace/配置/健康快照打包”的入口
3. **Helm 运维默认值不够完备**：缺少 ServiceMonitor、PDB、HPA 等常见生产落地组件
4. **知识库内容的生命周期治理缺口**：缺少 review_due/authority/supersedes 等字段与 stale 报表

## Beads Epic 与 40 个任务

已在 beads 中建立 epic：`MimirQ-eh26`，并创建 40 个子任务（`MimirQ-eh26.1`…`MimirQ-eh26.40`）。

任务分为四大簇：

1. **Observability & SLO**：query analytics、SLI/SLO、告警模板、成本聚合
2. **Incident Response**：trace bundle、config snapshot、CLI/UI 工具、结构化日志、smoke test
3. **Freshness & Lifecycle Governance**：生命周期字段、stale 报表、检索偏好、定时审计
4. **Reliability & Deploy**：Helm（ServiceMonitor/PDB/HPA）、队列指标、backpressure、备份/演练

## 已落地（P0 完成项）

1. **Query Analytics API（PII-safe）**
   - `GET /api/v1/observability/rag-metrics/query-analytics`
   - 输出：zero-hit rate、slow rate、retrieval p50/p95/p99、top query_hash（不含原文）
2. **Trace Bundle Export（PII-safe）**
   - `GET /api/v1/observability/rag-metrics/trace-bundle?request_id=...`
   - 输出：rag_trace + rag_done 等相关记录（自动剥离 question/query/citation snippets）
3. **Helm 运维增强**
   - ServiceMonitor（可选）、PDB（可选）、HPA（可选），并在 NOTES 中补充说明

## 下一步（建议执行顺序）

1. 继续 P0：`Ops-T021`（生命周期字段 + stale 报表的最小闭环）
2. 做 P1：把 query analytics / trace bundle 接入 `/observability` 前端面板
3. 做 P1：把关键 SLI 暴露为 Prometheus metrics，并提供 PrometheusRule/Grafana 模板

