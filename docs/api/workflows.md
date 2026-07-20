# API 调用流程（场景化）

本文档按 **典型集成顺序** 列出 HTTP 方法与**完整路径**（均含前缀 `/api/v1`）。字段与 body 以 OpenAPI / GitHub Pages 上的 Redoc 为准。

**通用请求头**（除明确标注可匿名的接口外）：

- `Authorization: Bearer <access_token>`
- `Content-Type: application/json`（JSON 请求体时）

---

## 场景 A：账号与租户

1. 未初始化部署仅可调用一次 `POST /api/v1/auth/register` 创建首个 owner；之后使用 `POST /api/v1/auth/login` 获取 `access_token`，其他账号由管理员、SSO 或 SCIM 配置。
2. `GET /api/v1/auth/me` — 校验会话与用户信息。  

（若启用 SAML/SCIM，见 OpenAPI 中 **Auth**、**SCIM v2** 下其余路径。）

---

## 场景 B：数据集与文档入库

1. `POST /api/v1/datasets` — 创建数据集（保存返回的 `dataset_id`）。  
2. `POST /api/v1/documents`（或文档多部分上传相关路径，见 **Documents**）— 上传文件并关联数据集。  
3. 轮询或使用 Webhook/任务队列（若集成）：`GET /api/v1/documents/{document_id}` 或列表接口 — 直至 `status` 为完成态。  

可选：**Datasets Precheck** 下路径 — 入库前扫描（与 Web 预检页一致）。

---

## 场景 C：解析、切块与流水线

1. **Parsing Workspace**：`GET/POST .../parsing/...` — 解析任务与预览（具体路径见 Redoc **Parsing Workspace**）。  
2. **Chunk Preview**：`/chunk-presets/...` — 预设与切块预览。  
3. **Pipeline**：`/pipeline/...` — 编排执行（若使用统一流水线 API）。  

详细参数见 OpenAPI；解析器侧环境见 [../guides/dependencies.md](../guides/dependencies.md)。

---

## 场景 D：检索与 RAG 回答

1. **Retrieval**（推荐先读 [../examples/retrieval_api_examples.md](../examples/retrieval_api_examples.md)）：  
   - `GET/POST /api/v1/retrieval/profiles/...` — 检索配置档案。  
   - `POST /api/v1/retrieval/explain`（或当前版本等价路径）— 解释一次检索。  
   - `GET /api/v1/retrieval/config-hash` — 配置指纹。  
2. **RAG**：`POST /api/v1/rag/...` — 生成、检索增强等（以 OpenAPI 列表为准）。  
3. **RAG Visualization (RAGViz)**：`/ragviz/...` — 调试可视化。  

---

## 场景 E：对话（Chat）

1. `POST /api/v1/chat/...` — 非流式或流式对话（见 **Chat** 下各 `POST`）。  

常与场景 D 共用同一后端与认证。

---

## 场景 F：知识图谱（KG）

1. `POST /api/v1/kg/...` — 构建、查询、导出（见 **Knowledge Graph (KG)**）。  

背景说明：[../guides/knowledge_graph.md](../guides/knowledge_graph.md)。

---

## 场景 G：评测与质量

1. **Evaluations**：`/evaluations/...` — RAGAS 运行、回归用例、queryset 健康度等。  
2. **Feedback**：`POST /api/v1/feedback/...` — 用户反馈；可转回归用例。  

---

## 场景 H：治理、审计与报表

1. **Governance**：`/governance/...`  
2. **Audit**：`/audit/...`  
3. **Reports**：`/reports/datasets/{dataset_id}` 及导出 HTML 等路径（与 Web「报告中心」一致）。  

---

## 场景 I：企业账号与权限

1. **Groups**：`/groups/...`  
2. **RBAC**：`/rbac/...`  
3. **SCIM v2**：`/scim/v2/...`  

---

## 场景 J：运维与可观测

1. **Health**：`/health/...`  
2. **Meta**：`/meta`  
3. **Observability**：`/observability/...`  
4. **Usage**：`/usage/...`  
5. **Settings**：`GET/PATCH /api/v1/settings/...` — 动态配置（需管理员权限时以服务端校验为准）。  

---

## 排障与契约

- 联调清单：[../integration/FE_BE_DEBUG.md](../integration/FE_BE_DEBUG.md)  
- 接口契约与前端覆盖：[../integration/API_CONTRACT.md](../integration/API_CONTRACT.md)  
- 全量冒烟说明：[../integration/API_SMOKE.md](../integration/API_SMOKE.md)  
