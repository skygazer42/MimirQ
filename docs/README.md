# 📚 MimirQ 文档目录

欢迎来到项目文档中心。这里汇总了搭建、调优与扩展 MimirQ 的关键指引。

## 快速上手
- [quickstart.md](./quickstart.md)：5 分钟完成环境准备、服务启动与基础校验。
- [deployment/docker_compose.md](./deployment/docker_compose.md)：Docker Compose 的开发/生产模式与常见排错。

## 使用指南
- [guides/langchain_agent_migration.md](./guides/langchain_agent_migration.md)：当前纯 LangChain RAG 架构说明与迁移记录。
- [guides/rag_optimization.md](./guides/rag_optimization.md)：检索效果与回答质量优化方案。
- [guides/knowledge_graph.md](./guides/knowledge_graph.md)：知识图谱（KG）的开启、抽取、可视化与导出。
- [guides/chunk_preview.md](./guides/chunk_preview.md)：切块预览页（chunk preview）的使用说明、参数建议与快捷键。
- [guides/milvus_guide.md](./guides/milvus_guide.md)：Milvus 的部署、调优与常见问题。
- [guides/dependencies.md](./guides/dependencies.md)：不同解析/Embedding 模式的依赖清单。
- [guides/marker_guide.md](./guides/marker_guide.md)：Marker（外部服务）解析器集成。
- [guides/paddlevl_guide.md](./guides/paddlevl_guide.md)：PaddleOCR-VL（外部服务）解析器集成。
- [guides/olmocr_guide.md](./guides/olmocr_guide.md)：olmOCR（外部服务）解析器集成。
- [guides/mineru_guide.md](./guides/mineru_guide.md)：MinerU（本地/在线）解析器集成（含本地 FastAPI）。

## 集成与架构迁移
- [integrations/mineru_integration.md](./integrations/mineru_integration.md)：MinerU 在线解析的配置与使用。
- [integrations/migration_chromadb_to_milvus.md](./integrations/migration_chromadb_to_milvus.md)：从 ChromaDB 迁移到 Milvus 的原因与步骤。
- [integration/FE_BE_DEBUG.md](./integration/FE_BE_DEBUG.md)：前后端联调排障清单（从“能跑”到“可用 + 可排障”）。
- [integration/API_CONTRACT.md](./integration/API_CONTRACT.md)：前后端接口契约检查（保证接口一一对应）。
- [integration/API_SMOKE.md](./integration/API_SMOKE.md)：全接口冒烟（OpenAPI 全量覆盖 + 调用验证）。

## 运维 / CI
- [operations.md](./operations.md)：doctor/verify/audit/回归门禁等脚本使用说明。

## 优化清单
- [optimization/OPTIMIZATION_20_TASKS_DOC_PARSING_CHUNKING_CLEANING.md](./optimization/OPTIMIZATION_20_TASKS_DOC_PARSING_CHUNKING_CLEANING.md)：文档解析/清洗/切块 20 项深度优化。

> 若新增文档，请将其放入上面合适的子目录，如需新增分类可在 `docs/` 下创建新的文件夹。
