# OIDC / JWT Groups Claim 同步（Enterprise）

本指南说明如何在 **企业 IdP（OIDC / JWT）** 中配置 `groups`（或 roles）声明，并在 MimirQ 中启用 “JWT groups claim → tenant groups/memberships” 的 **可选同步**。

适用场景：
- 你希望用 IdP 的目录（组/角色）来驱动 MimirQ 的 **组权限 allowlist**（dataset/document）
- 你希望减少“手工维护成员白名单”的成本，并为后续 SCIM / access review 打地基

> 核心原则：**默认 fail-closed + PII-safe**。MimirQ 只在 `JWT_GROUPS_SYNC_ENABLED=true` 且能确认 tenant 绑定时才会写入本地 groups/memberships。

---

## 1) 前提条件（强烈建议）

### 1.1 启用 JWT 鉴权（生产必须）

```bash
AUTH_MODE=jwt
```

### 1.2 确保 Token 是“可信的”（信任边界）

MimirQ 的 groups 同步只应在 **JWT 已被验证** 的前提下启用。建议至少满足：

- 使用 **JWKS** 校验签名（推荐用于外部 IdP 的 RS256/ES256）：
  - `JWT_JWKS_URLS=https://<issuer>/.well-known/jwks.json`
  - 或开启 OIDC discovery：`JWT_JWKS_DISCOVERY_ENABLED=true` + `JWT_ISSUER=...`
- 约束信任域（防止错误 issuer 的 token 被接受）：
  - `JWT_ISSUER=https://<issuer>`
- 约束受众（防止其他系统的 token 被复用）：
  - `JWT_AUDIENCE=<your-aud>`（若你的 IdP 配置了 aud）

> 如果你允许任意 issuer/aud 的 token 通过，再开启 groups 同步，相当于允许攻击者通过伪造 claims 写入本地 groups/memberships（风险极高）。

### 1.3 配置 tenant 绑定（建议必须）

groups 同步只有在解析到 tenant id 时才会执行（防跨租户写入）：

```bash
JWT_TENANT_CLAIM=tenant_id
```

- 你的 IdP 需要在 Access Token 中包含 `tenant_id`（UUID 字符串）这一 claim
- 建议同时启用 header 与 JWT claim 一致性校验（防 header spoofing）：

```bash
JWT_ENFORCE_TENANT_HEADER_MATCH=true
```

---

## 2) 启用 MimirQ groups claim 同步

### 2.1 基础配置

```bash
JWT_GROUPS_SYNC_ENABLED=true

# groups claim 名称（支持 dotted path，例如 "realm_access.roles"）
JWT_GROUPS_CLAIM=groups

# 每次请求最多处理多少个 group（best-effort 截断）
JWT_GROUPS_MAX_GROUPS=200

# 节流：同一 (tenant_id, user_id) 在单进程内最短同步间隔（秒）
JWT_GROUPS_SYNC_TTL_SEC=60
```

### 2.2 claim 格式与解析规则

MimirQ 期望 `JWT_GROUPS_CLAIM` 指向的值为：

- `["group-a", "group-b", ...]`（推荐）
- 或单个字符串（会被当作单元素列表）

解析规则（安全/可控）：
- 去空格、去重、跳过空项
- 单项长度 > 255 会被丢弃
- 最多处理 `JWT_GROUPS_MAX_GROUPS` 个（多余截断）
- 支持 **dotted path**（例如 `realm_access.roles`）

> 注意：dotted path 用于读取“嵌套 JSON”。如果你的 claim key 本身包含 `.`，会被当作路径分隔符；请尽量使用不含 `.` 的 claim 名（例如 `groups` / `roles` / `urn:mimirq:groups`）。

---

## 3) IdP Groups → MimirQ Groups 的映射方式

同步逻辑（当前 wave 的安全实现）：

1. 从 JWT payload 读取 groups 列表（字符串集合）
2. 在本地 `tenant_groups` 中按 **name** 做 upsert（tenant-scoped）
3. 在 `tenant_group_members` 中补齐 `(tenant_id, group_id, user_id)` 关系

关键点：
- **按 name 对齐**：JWT 中的每个 group 字符串会成为 `TenantGroup.name`
- **add-only**：当前实现只做“补齐”，不做成员/组的删除（离职/撤权建议走 SCIM 或定期 access review）
- **不记录 group 列表到公共日志**：同步失败也不会阻塞鉴权

### 3.1 如何拿到 group_id（用于 ACL allowlist）

Dataset/Document 的 group allowlist 需要 **UUID**（`group_id`），不是 group name。

可通过以下方式查询：
- `GET /api/v1/groups`：列出组（包含 `id` 与 `name`）
- `GET /api/v1/groups/{group_id}`：查看单个组

拿到 group_id 后即可配置：
- Dataset：`partial_group_list`
- Document ACL：`partial_group_list`

---

## 4) 常见 IdP 配置示例（思路）

不同 IdP 的 UI/字段命名会不同，本节给出 **claim 形态与推荐策略**，避免绑死某个控制台截图。

### 4.1 Okta（典型：`groups` claim）

目标：让 Access Token 中出现：

```json
{
  "sub": "alice",
  "tenant_id": "11111111-1111-1111-1111-111111111111",
  "groups": ["finance", "eng-platform"]
}
```

MimirQ 配置：

```bash
JWT_GROUPS_CLAIM=groups
```

### 4.2 Keycloak（典型：`groups` 或 `realm_access.roles`）

常见两种：

- groups：
  - `groups: ["/eng", "/finance"]`（也可能是扁平化 name）
- realm roles：
  - `realm_access: { "roles": ["eng-platform", "auditor"] }`

MimirQ 配置示例：

```bash
# 如果你把 roles 放在 realm_access.roles
JWT_GROUPS_CLAIM=realm_access.roles
```

### 4.3 Azure AD / Entra ID（典型：`groups` 为 object id）

Azure 常见把 `groups` 放进 token，但值可能是 **GUID（组对象 ID）**：

```json
{ "groups": ["a1b2c3d4-....", "e5f6g7h8-...."] }
```

这在 MimirQ 中也能工作（会以 GUID 字符串作为 group name），但可读性较差；更推荐使用：
- 应用角色（App Roles）/ roles（如果你的企业策略允许）
- 或者把“人类可读的组标识”写入一个自定义 claim（并确保 claim name 不含 `.`）

> 重要：当用户属于太多组时，Azure 可能返回 “overage” 指示而不直接下发完整 groups 列表。MimirQ 当前不会跟随 overage 去拉取 Graph；此时建议改用 roles 或缩小 groups 范围。

### 4.4 Auth0 / 其他 IdP（自定义 claim）

推荐把 groups 写入一个 **不含 `.` 的 claim key**，例如：

```json
{ "urn:mimirq:groups": ["eng-platform", "auditor"] }
```

对应：

```bash
JWT_GROUPS_CLAIM=urn:mimirq:groups
```

---

## 5) 验证与排障

1. 先确保鉴权与 tenant 绑定生效：
   - Token 能通过校验（签名/issuer/aud）
   - `JWT_TENANT_CLAIM` 能解析到 UUID
2. 发起一次带 JWT 的请求（任意 API），触发 best-effort 同步
3. 查看 groups 是否落库：
   - `GET /api/v1/groups`
   - `GET /api/v1/groups/{group_id}/members`
4. 若出现访问被拒绝：
   - 优先确认组是否同步（`deny_no_groups` 常见于 groups claim 缺失/不匹配）
   - 确认资源 allowlist 是否包含目标 group_id（`deny_no_match`）

相关指标（当 `PROMETHEUS_ENABLED=true`）：
- `authz_group_permission_total{resource,action,result}`

