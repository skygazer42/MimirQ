---
sidebar_label: "认证"
sidebar_position: 2
---

# 认证模式

MimirQ 支持多种认证方式，生产环境推荐 JWT Bearer Token，开发环境可使用 Header 调试模式。

## 认证方式对比

| 方式 | 适用场景 | Header 格式 | 安全等级 |
|------|----------|-------------|----------|
| JWT Bearer | 生产环境、正式集成 | `Authorization: Bearer <token>` | 高 |
| API Key | 服务间调用、CI/CD | `X-API-Key: <key>` | 中 |
| Header 调试 | 本地开发、联调 | `X-User-ID: <id>` | 低（仅限开发） |

## JWT Bearer（推荐）

### 获取 Token

```bash
curl -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "user@example.com", "password": "password"}'
```

返回 `access_token` 与 `refresh_token`（字段名以 [Redoc](https://skygazer42.github.io/MimirQ/) 为准）。

### 请求携带 Token

```bash
curl "$BASE_URL/api/v1/datasets/" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

:::warning 常见错误
- `Bearer` 与 Token 之间**必须有一个空格**
- Token 区分大小写，复制时注意不要包含换行符
- Token 过期时返回 401，需用 refresh_token 刷新
:::

### Token 刷新

```bash
curl -X POST "$BASE_URL/api/v1/auth/refresh" \
  -H "Content-Type: application/json" \
  -d '{"refresh_token": "'"$REFRESH_TOKEN"'"}'
```

Token 刷新策略建议：
- 在 Token 过期前主动刷新（如剩余有效期 < 5 分钟）
- 收到 401 时尝试一次刷新，失败则重新登录
- UI 端刷新失败应引导用户重新登录，而非静默重试

## API Key

适用于后台服务、脚本、CI/CD 等无交互场景。

```bash
curl "$BASE_URL/api/v1/datasets/" \
  -H "X-API-Key: $API_KEY"
```

:::info
API Key 的创建与管理通过管理后台操作，具体接口见 [Redoc](https://skygazer42.github.io/MimirQ/) 中 **auth** 分组。
:::

## Header 调试模式（仅开发）

部分部署允许通过 Header 直接注入用户身份，绕过正式认证流程。

```bash
# 仅限开发/联调环境
curl "$BASE_URL/api/v1/datasets/" \
  -H "X-User-ID: demo-user" \
  -H "X-Tenant-ID: dev-tenant"
```

:::danger 生产禁用
Header 调试模式**严禁在生产环境使用**。生产部署必须关闭此功能，否则存在租户伪造风险。
:::

## 联调检查清单

- [ ] `Content-Type: application/json`（JSON 接口）或 `multipart/form-data`（上传接口）
- [ ] `Authorization: Bearer` 前缀与空格正确
- [ ] Token 未过期，时钟与服务端同步（NTP）
- [ ] 多租户场景下租户上下文正确（JWT claims 或 Header）

## 常见错误

| 状态码 | 原因 | 解决方案 |
|--------|------|----------|
| 401 | Token 缺失、过期或格式错误 | 检查 Header 格式，尝试刷新 Token |
| 403 | 权限不足、功能未授权 | 确认角色与权限配置 |
| 间歇 401 | 时钟漂移导致 Token 校验失败 | 同步 NTP 时间 |

## 相关链接

- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
- [租户 Header](./tenant-headers.md) | [错误码](./errors-4xx-5xx.md)
- [新租户首日上线](../tasks/go-live-tenant.md)
