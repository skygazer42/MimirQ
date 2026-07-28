# 📚 MimirQ 文档目录

欢迎来到项目文档中心。本页是 `docs/` 的**完整索引**：按主题分类，覆盖全部指南与运维文档。新增文档请放入合适的子目录，并同步在本页登记一行。

## 快速上手

- [quickstart.md](./quickstart.md)：环境准备、服务启动与基础校验（含 Windows / 多平台步骤）。
- [guides/model_services.md](./guides/model_services.md)：`.env` 最小项、LLM / Embedding / Reranker 独立接入、初始管理员与 Docker / 主机地址差异。
- [deployment/docker_compose.md](./deployment/docker_compose.md)：Docker Compose 的开发/生产模式与常见排错。
- [guides/dependencies.md](./guides/dependencies.md)：不同解析 / Embedding 模式的依赖清单。

## API 参考（HTTP / OpenAPI）

- [api/README.md](./api/README.md)：Base URL、认证、**全量 OpenAPI Tag 对照表**、GitHub Pages 链接与本地静态站构建。
- [api/workflows.md](./api/workflows.md)：按场景的**端点顺序**（方法 + 完整路径）与依赖说明。
- [API.md](./API.md)：API 文档总览（SSOT 导航、长篇叙述的分片维护说明）。
- [api/reference/_index.md](./api/reference/_index.md)：长篇 API 叙述的分片索引（由脚本从 `api/source/legacy-api-narrative.md` 切分）。
- [examples/retrieval_api_examples.md](./examples/retrieval_api_examples.md)：检索 API 示例（profiles / explain / config-hash + 回归/消融 CLI）。
- [api-notes.md](./api-notes.md)：API 约定补充笔记。
- 在线交互文档（GitHub Pages）：`https://skygazer42.github.io/MimirQ/`（fork 请改为 `https://<owner>.github.io/<repo>/`）。
- **全栈手册（Docusaurus，可搜索）**：`https://skygazer42.github.io/MimirQ/handbook/`（与 Redoc 同域；源码在仓库 `docs-site/`）。

## 前后端集成与契约

- [integration/API_CONTRACT.md](./integration/API_CONTRACT.md)：前后端接口契约检查（保证接口一一对应）。
- [integration/API_SMOKE.md](./integration/API_SMOKE.md)：全接口冒烟（OpenAPI 全量覆盖 + 调用验证）。
- [integration/FE_BE_DEBUG.md](./integration/FE_BE_DEBUG.md)：前后端联调排障清单（从"能跑"到"可用 + 可排障"）。
- [guides/frontend_backend_integration.md](./guides/frontend_backend_integration.md)：前后端联调指南。
- [guides/ui_standards.md](./guides/ui_standards.md)：前端 UI 规范。

## 架构与设计

- [architecture.md](./architecture.md)：MimirQ 技术架构总览。
- [backend_structure.md](./backend_structure.md)：Backend 目录结构与路由认证约定。
- [guides/rag_platform_design_principles.md](./guides/rag_platform_design_principles.md)：RAG 平台设计准则。
- [guides/langchain_agent_migration.md](./guides/langchain_agent_migration.md)：LangChain / LangGraph 架构说明与迁移记录。
- [guides/pipeline_plugins.md](./guides/pipeline_plugins.md)：Pipeline 插件机制（可选行业示例的挂载方式）。
- [standards/import-policy.md](./standards/import-policy.md)：Import 与可选依赖策略。

## 文档解析（Parsing）

- [guides/parser_benchmark.md](./guides/parser_benchmark.md)：Parser Benchmark Harness。
- [guides/parsing_proof_policy.md](./guides/parsing_proof_policy.md)：Parsing Proof Policy（解析留证策略）。
- [guides/parsing_proof_workflow.md](./guides/parsing_proof_workflow.md)：Parsing Proof Workflow（解析留证工作流）。
- [guides/parse_quality_retrieval_diagnostics.md](./guides/parse_quality_retrieval_diagnostics.md)：解析质量 → 检索诊断联动。
- [guides/multimodal_ingest_debug.md](./guides/multimodal_ingest_debug.md)：多模态证据（图片/表格）入库与排障指南。
- 外部解析器集成：[Marker](./guides/marker_guide.md) · [PaddleOCR-VL](./guides/paddlevl_guide.md) · [olmOCR](./guides/olmocr_guide.md) · [Qianfan-OCR](./guides/qianfan_ocr_guide.md) · [MinerU](./guides/mineru_guide.md)（另见 [integrations/mineru_integration.md](./integrations/mineru_integration.md)）· [TextIn xParse](./guides/textin_guide.md) · [MagicPDF](./guides/magicpdf_guide.md)

## 入库与数据源（Ingestion / Connectors）

- [ingestion-policy.md](./ingestion-policy.md)：入库策略（解析前预处理）设计与使用。
- [guides/url_ingest.md](./guides/url_ingest.md)：远程 URL 抓取与批量导入。
- [guides/web_crawl.md](./guides/web_crawl.md)：网站抓取（站点级 Connector）。
- [guides/connectors.md](./guides/connectors.md)：连接器与批量导入/增量同步（Connector Runs / Configs）。
- [guides/connector_reconcile.md](./guides/connector_reconcile.md)：Connector Reconcile（对账）。
- [guides/connector_acl_inheritance.md](./guides/connector_acl_inheritance.md)：Connector ACL 继承（Source ACL → Document ACL）运维指南。
- [guides/document_versions.md](./guides/document_versions.md)：文档 Pipeline 版本管理与回滚。
- [minio_integration.md](./minio_integration.md)：MinIO 对象存储集成。
- [image_display_in_chat.md](./image_display_in_chat.md)：RAG 对话中的图片显示链路。

## 切块（Chunking）

- [guides/chunk_preview.md](./guides/chunk_preview.md)：切块预览页的使用说明、参数建议与快捷键。
- [guides/chunking_playbook.md](./guides/chunking_playbook.md)：切块调参与反模式 Playbook。
- [guides/chunk_strategies.md](./guides/chunk_strategies.md)：切块策略速查表。
- [llama_index_config.md](./llama_index_config.md)：LlamaIndex 分块策略的启用配置。

## 检索与重排（Retrieval / Reranking）

- [guides/rag_optimization.md](./guides/rag_optimization.md)：检索效果与回答质量优化方案。
- [guides/retrieval_debugging.md](./guides/retrieval_debugging.md)：检索质量排障 cookbook（召回/重排/缓存路径定位）。
- [guides/retrieval_fusion.md](./guides/retrieval_fusion.md)：多通道检索融合（Multi-Channel Fusion）。
- [guides/sparse_retrieval.md](./guides/sparse_retrieval.md)：SPLADE 风格稀疏检索通道。
- [guides/lexical_fallback.md](./guides/lexical_fallback.md)：Lexical fallback（Postgres FTS + pg_trgm）配置、索引与可观测性。
- [guides/colbert_ann_retrieval.md](./guides/colbert_ann_retrieval.md)：ColBERT ANN 候选召回通道。
- [guides/reranking_colbert.md](./guides/reranking_colbert.md)：ColBERT 晚交互重排指南。
- [guides/reranking_ltr.md](./guides/reranking_ltr.md)：LTR 重排（XGBoost）指南。
- [guides/table_tag.md](./guides/table_tag.md)：表格 / TAG（Table Augmented Generation）。
- [guides/milvus_guide.md](./guides/milvus_guide.md)：Milvus 的部署、调优与常见问题。

## 知识图谱（KG）

- [guides/knowledge_graph.md](./guides/knowledge_graph.md)：KG 的开启、抽取、可视化与导出。
- [guides/manual_kg_import.md](./guides/manual_kg_import.md)：手工 KG 导入。

## 证据与可观测性（Evidence / Observability）

- [guides/evidence_api.md](./guides/evidence_api.md)：Evidence API（Retrieval-Only）。
- [guides/evidence_capsule.md](./guides/evidence_capsule.md)：Evidence Capsule 契约（`mimirq.evidence_capsule.v1`）。
- [guides/explainability_workflows.md](./guides/explainability_workflows.md)：可解释性工作台使用工作流（检索/KG/入库/报告串联）。
- [guides/observability_dashboard.md](./guides/observability_dashboard.md)：监控面板（检索 / 重排 / 引用 Metrics）。
- [guides/otel_phoenix.md](./guides/otel_phoenix.md)：OpenTelemetry 与 Phoenix 可观测性。
- [ops/templates/README.md](./ops/templates/README.md)：Prometheus + Grafana 运维模板。

## 评测与回归（Evaluation / Regression）

- [guides/regression_gate.md](./guides/regression_gate.md)：离线评测回归（Retrieval gate / RAGAS / CI）。
- [guides/evaluation_maturity_model.md](./guides/evaluation_maturity_model.md)：评测成熟度模型（从手工 QA → CI 门禁 → 持续评测）。
- [guides/release_gate.md](./guides/release_gate.md)：Release Gate（回归 + SLO + 成本预算）。
- [guides/evidence_retrieval_gate.md](./guides/evidence_retrieval_gate.md)：Evidence Retrieval Gate（Retrieval-only 回归门禁）。
- [guides/evidence_pack_to_regression.md](./guides/evidence_pack_to_regression.md)：Evidence Pack → 回归用例（企业级证据闭环）。
- [guides/retrieval_ablation.md](./guides/retrieval_ablation.md)：检索参数消融评测（Ablation / Leaderboard / Diff）。
- [guides/retrieval_release_notes.md](./guides/retrieval_release_notes.md)：检索质量发布说明模板（hit@k/mrr/ndcg + artifact 链接）。
- [guides/hardcase_feedback_automation.md](./guides/hardcase_feedback_automation.md)：Hardcase 反馈自动化。
- [guides/training_export.md](./guides/training_export.md)：训练数据导出。
- [guides/public_benchmarks_zh.md](./guides/public_benchmarks_zh.md)：公开中文 benchmark（Milvus / Ollama）。
- [benchmarks/changzhou_dify.md](./benchmarks/changzhou_dify.md)：常州政务 800 题 Dify / MimirQ 评测记录（方法、指标与历史复测）。
- [templates/retrieval_debt_audit_template.md](./templates/retrieval_debt_audit_template.md)：Retrieval Debt Audit 模板。
- [contributing/retrieval_pr_checklist.md](./contributing/retrieval_pr_checklist.md)：Retrieval PR Checklist。

## 发布与版本（Releases / Versions）

- [releases/README.md](./releases/README.md)：最新发布与版本索引。
- [releases/v1.0.0.md](./releases/v1.0.0.md)：当前最新稳定版的对外发布说明。

## 数据治理（Governance）

- [guides/data_governance.md](./guides/data_governance.md)：数据治理/清洗工作台。
- [guides/dataset_precheck.md](./guides/dataset_precheck.md)：预检扫描（入库前摸底）。
- [data-governance-profiles.md](./data-governance-profiles.md)：治理预设 Profiles 与脚本。
- [governance-rule-packs.md](./governance-rule-packs.md)：治理规则包（Rule Packs）。

## 权限与企业能力（AuthZ / Enterprise）

- [guides/document_acl.md](./guides/document_acl.md)：文档级访问控制（Security Trimming）。
- [guides/dataset_permissions.md](./guides/dataset_permissions.md)：数据集权限。
- [guides/saml_sso.md](./guides/saml_sso.md)：SAML 单点登录集成。
- [guides/scim.md](./guides/scim.md)：SCIM v2 用户/组同步（Enterprise，可选）。
- [guides/oidc_groups_claim.md](./guides/oidc_groups_claim.md)：OIDC / JWT Groups Claim 同步（Enterprise）。

## 部署与运维（Deployment / Ops）

- [deployment/helm.md](./deployment/helm.md)：Helm / Kubernetes 部署指南。
- [deployment/runbook.md](./deployment/runbook.md)：Operations Runbook（生产运维与排障）。
- [deployment/security_baseline.md](./deployment/security_baseline.md)：安全基线（Kubernetes）。
- [deployment/backup_restore.md](./deployment/backup_restore.md)：备份 / 恢复指南（Postgres + MinIO + 向量后端）。
- [deployment/db_maintenance.md](./deployment/db_maintenance.md)：DB 维护（VACUUM/ANALYZE + Retention）。
- [deployment/dr_drill.md](./deployment/dr_drill.md)：DR 灾备演练（恢复验证 Checklist + 自动化）。
- [deployment/chaos_tests.md](./deployment/chaos_tests.md)：Chaos Tests（Redis / MinIO / Milvus 依赖故障演练）。
- [deployment/incident_response_cookbook.md](./deployment/incident_response_cookbook.md)：Incident Response Cookbook。
- [deployment/quota_rate_limit.md](./deployment/quota_rate_limit.md)：配额与限流（Quotas & Rate Limits）。
- [deployment/private_delivery_checklist.md](./deployment/private_delivery_checklist.md)：私有化交付 Checklist。
- [deployment/content_governance_sop.md](./deployment/content_governance_sop.md)：Runbook 内容治理 SOP（作者/审核/更新/废弃）。
- [operations.md](./operations.md)：doctor/verify/audit/回归门禁等脚本使用说明。
- [guides/task_queue_ops.md](./guides/task_queue_ops.md)：任务队列运维（arq）。

## 提示词（Prompts）

- [prompts/mimirq-prompt-library-2026-q2.md](./prompts/mimirq-prompt-library-2026-q2.md)：MimirQ 提示词全集（业界采集 + 现状基线中文化）。

## Web 工作台入口（页面路径速查）

- 数据画像：`/datasets/{id}/profile`（入库后画像）
- 预检扫描：`/datasets/{id}/precheck`（入库前摸底）
- 报告中心：`/reports`（数据集报告 / RAG Audit 导出）
- 数据集报告（API）：`/api/v1/reports/datasets/{dataset_id}`、`/api/v1/reports/datasets/{dataset_id}/rag-audit/export-html`

> 若新增文档，请将其放入上面合适的子目录并在本页登记；如需新增分类可在 `docs/` 下创建新的文件夹。
