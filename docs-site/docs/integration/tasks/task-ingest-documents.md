---
sidebar_label: "文档入库与可检索"
sidebar_position: 4
---

# 任务：文档入库与可检索

**本文适用于**：**数据 Owner、集成工程师、内容运营**；目标是把文件变成 **可被检索、可参与对话** 的知识，而不是只躺在对象存储里。

## 业务目标

- 文档进入 **正确数据集** 与 **正确流水线**（解析、分块、索引）。  
- **处理状态** 对业务可见：何时可问、何时失败、失败是否可重试。  
- 大文件与批量场景下 **可预期耗时**，避免业务方误以为「系统坏了」。

## 前置条件

- [数据集](./task-dataset-go-live.md) 已存在且当前用户有 **上传/管理** 权限。  
- 明确 **允许的文件类型与大小**（产品策略 + 网关限制 + OpenAPI 约定）。  
- 若走 **预签名/批量上传**：确认对象存储回调与 `batch-upload/status` 轮询方案（见 OpenAPI **documents**）。

## 推荐步骤（概要）

1. **单文件**：`POST /api/v1/documents/upload`（multipart），字段名与 Redoc 一致；记录返回的 `document_id`（见 Backend [文档 — 请求要点](../../backend/documents/schemas.md)）。  
2. **状态**：轮询 `GET /api/v1/documents/{id}/status` 至完成或失败终态；Web 侧对应 **入库/解析** 界面（见 Frontend [文档 — 用户路径](../../frontend/documents/overview.md)）。  
3. **可检索验证**：用 **检索调试/对话** 产品路径做一次「命中该文档」的抽查（与贵司 RAG 流程一致）。  
4. **批量**：使用 batch、upload-url 等路径时，维护 **batch_id** 与失败清单，避免静默丢文。

## 验收标准（业务）

- [ ] 抽样文档在 **承诺时间内** 达到「可问答」状态，或明确展示 **失败原因与重试入口**。  
- [ ] 同一数据集下文档 **归属正确**，不会出现「用户看得见列表但问答永远引不到」的配置错误。  
- [ ] 运营侧有一份 **上传规范**（命名、元数据、敏感分级）。

## 失败时的业务影响与止损

| 现象 | 业务影响 | 止损动作 |
| --- | --- | --- |
| 长期 processing | 知识库空洞、客服无法引用 | 走 [解析失败止损](./task-parse-failure-triage.md) |
| 上传 400/415 | 内容进不来 | 查 MIME/字段名/大小；[multipart 模式](../patterns/multipart-upload.md) |
| 可检索但答案差 | 业务认为「AI 不行」 | 走 [检索效果变差](./task-retrieval-quality.md)，区分数据与配置 |

## 相关手册链接

- Backend：[文档 API 索引](../../backend/documents/api-index.md) · [排障](../../backend/documents/troubleshooting.md)  
- 场景：[上传后对话](../scenarios/s01-upload-chat.md) · E2E：[文档序列](../documents/e2e.md)  
- [SSE / 流式](../patterns/sse-streaming.md)（若上传后立刻走流式预览）
