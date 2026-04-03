---
sidebar_label: "租户与系统管理员"
sidebar_position: 1
---

# 租户与系统管理员

管理员负责 MimirQ 平台的租户管理、权限配置与数据集治理，确保团队成员能安全、高效地使用知识库。

## 职责概览

| 职责 | 说明 |
|------|------|
| 租户管理 | 创建与配置租户，管理租户级别的功能开关与配额 |
| 用户与权限 | 导入用户、分配角色（RBAC）、管理 API Key |
| 数据集治理 | 创建数据集、配置预检规则、监控数据集健康度 |
| 安全合规 | 审计日志查阅、隔离区审批、敏感内容治理 |

## 推荐阅读路径

| 阶段 | 目标 | 推荐页面 |
|------|------|----------|
| 1. 环境就绪 | 理解认证与租户模型 | [认证模式](../patterns/auth-modes.md) / [租户 Header](../patterns/tenant-headers.md) |
| 2. 首日上线 | 创建租户、导入用户、建库 | [新租户首日上线](../tasks/go-live-tenant.md) |
| 3. 知识可用 | 文档入库、验证问答 | [知识库问答](../tasks/knowledge-base-qa.md) |
| 4. 运营排障 | 文档卡住、健康监控 | [文档卡住排障](../tasks/document-stuck.md) |
| 5. 持续治理 | 错误码、审计、环境管理 | [错误码](../patterns/errors-4xx-5xx.md) / [环境矩阵](../patterns/env-matrix.md) |

## 首日清单

完成以下步骤即可达到"有人能登录、有数据集、能试传文档"的最小验收状态。

- [ ] **获取管理员凭证** — 登录或注册，确认 `access_token` 有效
- [ ] **创建租户**（如为多租户部署）— 调用租户管理 API 或在 Web 控制台操作

```bash
curl -X POST "$BASE_URL/api/v1/tenants" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "engineering-team"}'
```

- [ ] **配置 RBAC** — 为团队成员分配 admin / editor / viewer 等角色
- [ ] **导入用户** — 手动添加或通过 SCIM 同步（参见[场景: SCIM 同步](../scenarios/s10-scim-sync.md)）
- [ ] **创建首个数据集** — 作为文档上传的挂载点

```bash
curl -X POST "$BASE_URL/api/v1/datasets/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "product-docs", "description": "产品文档知识库"}'
```

- [ ] **上传测试文档** — 验证入库链路畅通

:::tip 验收标准
首日结束时，团队中至少一名非管理员用户能登录、看到数据集列表、并确认测试文档处理完成。
:::

## 关键 API 端点

| 操作 | 方法 & 路径 | 说明 |
|------|-------------|------|
| 创建租户 | `POST /api/v1/tenants` | 多租户部署必需 |
| 用户管理 | `GET/POST /api/v1/users` | 列表与创建用户 |
| 创建数据集 | `POST /api/v1/datasets/` | 返回 `dataset_id` |
| 数据集健康 | `GET /api/v1/datasets/{id}/health` | 检查数据集状态 |
| 审计日志 | `GET /api/v1/audit/logs` | 查阅操作记录 |
| 系统健康 | `GET /api/v1/health` | 存活探针 |

:::info 以 OpenAPI 为准
具体字段名、参数与响应结构以 [Redoc](https://skygazer42.github.io/MimirQ/) 中最新定义为权威依据。
:::

## 与其他角色的协作

- **集成工程师** — 管理员提供 API Key 与租户上下文，集成工程师负责对接外部系统
- **SRE/运维** — 管理员关注业务层面的数据集健康，运维关注基础设施与探针

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [认证模式](../patterns/auth-modes.md) | [错误码](../patterns/errors-4xx-5xx.md)
- [FE/BE 对照矩阵](../generated/fe-be-matrix.mdx)
