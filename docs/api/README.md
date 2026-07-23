# MimirQ HTTP API 参考（导读）

本目录提供 **人类可读** 的 API 导览；**完整路径、请求/响应模型** 以 OpenAPI 为准。

| 资源 | 说明 |
|------|------|
| **在线交互文档（GitHub Pages）** | 部署成功后访问：`https://skygazer42.github.io/MimirQ/`（fork 后请改为 `https://<owner>.github.io/<repo>/`） |
| **全栈手册（Docusaurus）** | 同域：`https://skygazer42.github.io/MimirQ/handbook/`（叙事 + 分区侧栏 + 搜索；与 Redoc 分工） |
| **仓库内 OpenAPI JSON** | 运行 `make openapi-export` 生成 [`web/openapi.json`](../../web/openapi.json)（若本地被 gitignore，以导出结果为准） |
| **本地运行时 Swagger** | 后端启动后：`http://<backend>/docs` 与 `http://<backend>/openapi.json` |
| **端到端调用顺序** | [workflows.md](./workflows.md) |
| **前后端契约检查** | [../integration/API_CONTRACT.md](../integration/API_CONTRACT.md) |
| **检索示例** | [../examples/retrieval_api_examples.md](../examples/retrieval_api_examples.md) |

## 基础约定

- **Base path**：`/api/v1`（所有下列前缀均相对于该前缀；OpenAPI 内路径已包含此前缀）。
- **认证**：多数业务接口需在 Header 携带 JWT：`Authorization: Bearer <access_token>`。获取令牌见 **Auth** 分组（如 `POST /api/v1/auth/login`）。企业场景可能另有 SAML/SCIM，见对应 Tag。
- **权威来源**：路由注册见 [`app/api/v1/__init__.py`](../../app/api/v1/__init__.py)；导出契约见 `scripts/export_openapi.py`。

## OpenAPI Tag 与模块对照（全量）

下表与 `app/api/v1` 中 `include_router(..., tags=[...])` **一一对应**（同一 Tag 在 OpenAPI 中合并展示；**Retrieval** 下含多个子路由文件）。

| OpenAPI Tag | 职责摘要 | 典型路径前缀 | 延伸阅读 |
|-------------|----------|--------------|----------|
| Health | 健康检查 | `/health` | [../integration/FE_BE_DEBUG.md](../integration/FE_BE_DEBUG.md) |
| Meta | 后端元数据 / 能力发现 | `/meta` | — |
| Auth | 注册、登录、当前用户、SAML 等 | `/auth` | — |
| Documents | 文档上传、状态、内容、分块等 | `/documents` | [../guides/multimodal_ingest_debug.md](../guides/multimodal_ingest_debug.md) |
| Parsing Workspace | 解析工作台、预览相关 | `/parsing` | [../guides/marker_guide.md](../guides/marker_guide.md) 等 |
| Chunk Preview | 切块预设与预览 | `/chunk-presets` | [../guides/chunk_preview.md](../guides/chunk_preview.md) |
| Chat | 对话、流式回答 | `/chat` | — |
| Datasets | 数据集 CRUD、画像、文档列表等 | `/datasets` | [../guides/explainability_workflows.md](../guides/explainability_workflows.md) |
| Datasets Precheck | 入库前预检 | `/datasets/.../precheck` 等 | — |
| Dataset Tables (TAG) | 表格存储（TAG） | `/datasets/.../tables` 等 | — |
| DB Catalog | 数据集数据库目录 | `/datasets/.../db-catalog` 等 | — |
| Dataset Categories | 数据集分类 | `/dataset-categories` | — |
| Knowledge Graph (KG) | 图谱构建、查询、诊断 | `/kg` | [../guides/knowledge_graph.md](../guides/knowledge_graph.md) |
| Evidence Workbench | 证据工作台 | `/evidence` | [../guides/explainability_workflows.md](../guides/explainability_workflows.md) |
| Evidence Capsules | 证据胶囊 | `/evidence`（capsules 相关路径） | — |
| LTR | 学习排序模型注册与激活 | `/ltr` | — |
| Settings | 运行时配置读写 | `/settings` | — |
| Governance | 数据治理策略 | `/governance` | — |
| Evaluations | RAGAS / 回归 / queryset 等评测 | `/evaluations` | [../guides/regression_gate.md](../guides/regression_gate.md) |
| Prompt Templates | 提示模板 | `/prompt-templates` | — |
| RAG Config Templates | RAG 配置模板 | `/rag-config-templates` | — |
| Feedback | 消息反馈与回归用例转化 | `/feedback` | — |
| Pipeline | 流水线编排相关 | `/pipeline` | — |
| Connectors | 外部连接器与同步 | `/connectors` | [../guides/connectors.md](../guides/connectors.md) |
| Ingestion Runs | 批量入库运行记录 | `/ingestion` | [../guides/connectors.md](../guides/connectors.md) |
| RAG | RAG 核心配置、生成、检索入口等 | `/rag` | [../guides/rag_optimization.md](../guides/rag_optimization.md) |
| Retrieval | 检索配置档案、解释、配置哈希 | `/retrieval` | [../examples/retrieval_api_examples.md](../examples/retrieval_api_examples.md) |
| RAG Visualization (RAGViz) | 检索可视化调试 | `/ragviz` | [../guides/retrieval_debugging.md](../guides/retrieval_debugging.md) |
| External Conversation Integration | 外部会话导入与会话绑定 | `/integrations/conversations` | [workflows.md](./workflows.md) |
| Dify Integration | Dify External Knowledge 检索与 conversation-turns 回填 | `/integrations/dify` | [workflows.md](./workflows.md) |
| Groups | 用户组 | `/groups` | — |
| RBAC | 角色权限 | `/rbac` | — |
| SCIM v2 | SCIM 供应 | `/scim/v2` | — |
| Reports | 数据集报告、导出 | `/reports` | — |
| Observability | 可观测性 API | `/observability` | — |
| Audit | 审计日志查询 | `/audit` | — |
| Usage | 用量统计 | `/usage` | — |

## 构建本地静态站（与 CI 一致）

```bash
make api-docs-build
# 产物：docs/api/site/index.html + docs/api/site/openapi.json
```

本地预览（任选其一）：

```bash
cd docs/api/site && python3 -m http.server 8765
# 浏览器打开 http://127.0.0.1:8765/
```

## GitHub Pages 部署说明

1. 仓库 **Settings → Pages**：Build source 选择 **GitHub Actions**。  
2. 推送 `main` 触发 [`.github/workflows/api-docs.yml`](../../.github/workflows/api-docs.yml)，或手动 **Run workflow**。  
3. 将 **About → Website** 指向 Pages URL，便于从仓库首页直达本文档站。
