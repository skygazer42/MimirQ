# 📚 MimirQ 文档目录

欢迎来到项目文档中心。这里汇总了搭建、调优与扩展 MimirQ 的关键指引。

## 快速上手
- [quickstart.md](./quickstart.md)：5 分钟完成环境准备、服务启动与基础校验。
- [deployment/docker_compose.md](./deployment/docker_compose.md)：Docker Compose 的开发/生产模式与常见排错。

## API 参考（HTTP / OpenAPI）
- [api/README.md](./api/README.md)：Base URL、认证、**全量 OpenAPI Tag 对照表**、GitHub Pages 链接与本地静态站构建。
- [api/workflows.md](./api/workflows.md)：按场景的**端点顺序**（方法 + 完整路径）与依赖说明。
- 在线交互文档（部署 GitHub Pages 后）：`https://skygazer42.github.io/MimirQ/`（fork 请改为 `https://<owner>.github.io/<repo>/`）。
- **全栈手册（Docusaurus，可搜索）**：`https://skygazer42.github.io/MimirQ/handbook/`（与 Redoc 同域；源码在仓库 `docs-site/`）。

## 使用指南
- [guides/langchain_agent_migration.md](./guides/langchain_agent_migration.md)：当前纯 LangChain RAG 架构说明与迁移记录。
- [guides/rag_optimization.md](./guides/rag_optimization.md)：检索效果与回答质量优化方案。
- [guides/retrieval_debugging.md](./guides/retrieval_debugging.md)：检索质量排障 cookbook（召回/重排/缓存路径定位）。
- [examples/retrieval_api_examples.md](./examples/retrieval_api_examples.md)：检索 API 示例（profiles / explain / config-hash + 回归/消融 CLI）。
- [guides/lexical_fallback.md](./guides/lexical_fallback.md)：Lexical fallback（Postgres FTS + pg_trgm）配置、索引与可观测性。
- [guides/knowledge_graph.md](./guides/knowledge_graph.md)：知识图谱（KG）的开启、抽取、可视化与导出。
- [guides/explainability_workflows.md](./guides/explainability_workflows.md)：可解释性工作台使用工作流（检索/KG/入库/报告串联）。
- [guides/multimodal_ingest_debug.md](./guides/multimodal_ingest_debug.md)：多模态证据（图片/表格）入库与排障指南。
- [guides/chunk_preview.md](./guides/chunk_preview.md)：切块预览页（chunk preview）的使用说明、参数建议与快捷键。
- [guides/connectors.md](./guides/connectors.md)：连接器（Connectors）与批量导入/增量同步（Connector Runs / Configs）。
- [guides/milvus_guide.md](./guides/milvus_guide.md)：Milvus 的部署、调优与常见问题。
- [guides/dependencies.md](./guides/dependencies.md)：不同解析/Embedding 模式的依赖清单。
- [guides/marker_guide.md](./guides/marker_guide.md)：Marker（外部服务）解析器集成。
- [guides/paddlevl_guide.md](./guides/paddlevl_guide.md)：PaddleOCR-VL（外部服务）解析器集成。
- [guides/olmocr_guide.md](./guides/olmocr_guide.md)：olmOCR（外部服务）解析器集成。
- [guides/qianfan_ocr_guide.md](./guides/qianfan_ocr_guide.md)：Qianfan-OCR（外部服务）解析器集成。
- [guides/mineru_guide.md](./guides/mineru_guide.md)：MinerU（本地/在线）解析器集成（含本地 FastAPI）。
- [guides/textin_guide.md](./guides/textin_guide.md)：TextIn xParse（外部 API）解析器集成。
- [guides/magicpdf_guide.md](./guides/magicpdf_guide.md)：MagicPDF（独立服务优先，本地 magic-pdf CLI 兜底）解析器集成。

## 集成与架构迁移
- [integrations/mineru_integration.md](./integrations/mineru_integration.md)：MinerU 在线解析的配置与使用。
- [integration/FE_BE_DEBUG.md](./integration/FE_BE_DEBUG.md)：前后端联调排障清单（从“能跑”到“可用 + 可排障”）。
- [integration/API_CONTRACT.md](./integration/API_CONTRACT.md)：前后端接口契约检查（保证接口一一对应）。
- [integration/API_SMOKE.md](./integration/API_SMOKE.md)：全接口冒烟（OpenAPI 全量覆盖 + 调用验证）。

## 运维 / CI
- [operations.md](./operations.md)：doctor/verify/audit/回归门禁等脚本使用说明。

## 优化与审计
- [guides/regression_gate.md](./guides/regression_gate.md)：离线评测回归（Retrieval gate / RAGAS / CI）。
- [guides/retrieval_release_notes.md](./guides/retrieval_release_notes.md)：检索质量发布说明模板（hit@k/mrr/ndcg + artifact 链接）。
- [guides/evaluation_maturity_model.md](./guides/evaluation_maturity_model.md)：评测成熟度模型（从手工 QA → CI 门禁 → 持续评测）。
- 数据画像（Web）：`/datasets/{id}/profile`（入库后画像）
- 预检扫描（Web）：`/datasets/{id}/precheck`（入库前摸底）
- 报告中心（Web）：`/reports`（数据集报告 / RAG Audit 导出）
- 数据集报告（API）：`/api/v1/reports/datasets/{dataset_id}`、`/api/v1/reports/datasets/{dataset_id}/rag-audit/export-html`

> 若新增文档，请将其放入上面合适的子目录，如需新增分类可在 `docs/` 下创建新的文件夹。
