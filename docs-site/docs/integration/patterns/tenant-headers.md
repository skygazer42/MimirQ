---
sidebar_label: "租户 / 可见性"
sidebar_position: 3
---

# 多租户 Header 与可见性

MimirQ 支持多租户隔离，通过 JWT claims 或 Header 传递租户上下文，资源可见性受租户边界与 ACL 双重约束。

## 租户上下文传递

### 方式一：JWT Claims（推荐）

生产环境中，租户 ID 从 JWT Token 的 claims 中自动提取，无需额外 Header。

```json
{
  "sub": "user-123",
  "tenant_id": "tenant-abc",
  "roles": ["admin"],
  "exp": 1700000000
}
```

### 方式二：Header 注入（仅开发）

```bash
# 仅限开发/联调环境
curl "$BASE_URL/api/v1/datasets/" \
  -H "X-User-ID: demo-user" \
  -H "X-Tenant-ID: dev-tenant"
```

:::danger
Header 注入方式**仅用于开发环境**，生产部署必须通过网关入口强制 Bearer Token 认证，禁止 Header 伪造。
:::

## 可见性规则

资源列表与详情接口均受**租户 + ACL**双重约束：

| 场景 | 列表 API | 详情 API | 说明 |
|------|----------|----------|------|
| 本租户资源 | 可见 | 可访问 | 正常 |
| 其他租户资源 | 不可见 | 404 | 隔离生效 |
| 本租户无权资源 | 可能不可见 | 403 或 404 | 取决于产品策略 |

:::note 404 vs 403
不可见资源返回 404 而非 403，这是防止资源枚举攻击的安全设计。不要将此类 404 误判为"系统故障"。
:::

## 联调验证

### 验证租户隔离

```bash
# 使用租户 A 的 Token 创建数据集
curl -X POST "$BASE_URL/api/v1/datasets/" \
  -H "Authorization: Bearer $TOKEN_A" \
  -H "Content-Type: application/json" \
  -d '{"name": "tenant-a-dataset"}'

# 使用租户 B 的 Token 尝试访问（应返回 404）
curl "$BASE_URL/api/v1/datasets/$DATASET_ID" \
  -H "Authorization: Bearer $TOKEN_B"
```

### 验证一致性

用同一 Token 分别请求列表与详情，确认：
- 列表中出现的 `dataset_id` / `document_id` 均可通过详情接口访问
- 管理员与普通用户看到的列表范围符合 RBAC 预期

## 常见问题

| 现象 | 可能原因 | 解决方案 |
|------|----------|----------|
| 列表可见但详情 404 | 租户上下文不一致或竞态删除 | 核对 Token 中的 `tenant_id` |
| 管理端与用户端列表不一致 | 角色权限差异（符合预期） | 对照 OpenAPI scope 说明 |
| 跨租户数据泄露 | 租户隔离配置错误 | 紧急排查中间件与 ACL 逻辑 |

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [认证模式](./auth-modes.md) | [错误码](./errors-4xx-5xx.md)
- [场景: 多租户隔离](../scenarios/s14-multi-tenant.md)
