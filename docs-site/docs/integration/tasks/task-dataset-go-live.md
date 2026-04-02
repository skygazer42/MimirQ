---
sidebar_label: "数据集上线与可问答"
sidebar_position: 3
---

# 任务：数据集上线与可问答

**本文适用于**：**租户管理员、数据 Owner、集成工程师**；要把「空数据集」变成 **可绑定文档、可参与检索与问答** 的生产单元。

## 业务目标

- 在正确 **租户与权限模型** 下创建数据集，**成员/组可见性** 符合数据分级要求。  
- **默认解析/分块/RAG 策略**（或模板引用）与组织规范一致，避免上线后批量返工。  
- 业务方可明确回答：**哪些用户能在哪个界面看到该数据集、文档会进哪个数据集**。

## 前置条件

- 已完成 [环境首配](./task-new-tenant-setup.md) 或等价验证。  
- 已明确 **数据集分类**（若使用分类树）与 **命名规范**。  
- 若需预检/画像门禁：确认组织流程中 **「未通过则不允许入库」** 是否启用（与 OpenAPI 中 datasets 子资源一致）。

## 推荐步骤（概要）

1. **创建**：`POST /api/v1/datasets/`（或 Web 等价流程），body 满足 **DatasetCreate** 必填项（见 Backend [数据集 — 请求要点](../../backend/datasets/schemas.md)）。  
2. **权限**：设置 `permission`、`partial_member_list` / `partial_group_list` 等，与 Owner 预期一致。  
3. **策略**：配置 `default_parser_backend`、`default_chunk_strategy`、`rag_defaults` 或模板 ID；记录变更原因便于审计。  
4. **验证**：`GET /api/v1/datasets/{id}` 与列表接口交叉核对；在 Web **数据集详情** 与 **预检/画像/健康** 子页走通只读路径（见 Frontend [数据集 — 用户路径](../../frontend/datasets/overview.md)）。  
5. **与文档挂钩**：明确后续入库时 **dataset_id** 的传递方式（上传表单或 API 字段，见 [文档入库](./task-ingest-documents.md)）。

## 验收标准（业务）

- [ ] 目标用户组在 UI 中 **可见** 该数据集，非授权用户 **不可见或 404**（符合产品设计）。  
- [ ] 数据集元数据与 **组织命名规范** 一致，可被客服/运营读懂。  
- [ ] 已有一份 **简短运行说明**（内部 KB）：默认策略 + 变更联系人。

## 失败时的业务影响与止损

| 现象 | 业务影响 | 止损动作 |
| --- | --- | --- |
| 列表可见但详情 404 | 用户以为系统坏；实为 ACL | 查租户与 partial 列表；对照 [租户与可见性](../patterns/tenant-headers.md) |
| 409 冲突 | 并发编辑或非法迁移 | 先 GET 再 PATCH；避免脚本重试风暴 |
| 预检/画像红线 | 低质量数据批量进入 | 启用或强化门禁；隔离问题批次（链 [治理任务](./task-governance-quarantine.md)） |

## 相关手册链接

- Backend：[数据集 API 索引](../../backend/datasets/api-index.md) · [排障](../../backend/datasets/troubleshooting.md)  
- Frontend：[数据集 API 客户端](../../frontend/datasets/api-client.md)  
- 场景：[数据集绑定 RAG](../scenarios/s02-dataset-rag.md) · E2E：[数据集序列](../datasets/e2e.md)
