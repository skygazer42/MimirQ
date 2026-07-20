# SCIM v2（Enterprise，可选）

本指南说明如何在 MimirQ 中启用 **SCIM v2** 端点，用于企业 IdP 的目录对接与（可选）组成员变更。

> 设计原则：**默认关闭、fail-closed、tenant-safe**。只在显式开启 `SCIM_ENABLED=true` 时暴露端点。

---

## 1) 启用开关与鉴权方式

SCIM 端点默认关闭。启用后使用 **静态 Bearer Token** 鉴权（便于 Okta/AzureAD/Keycloak 等对接）。

```bash
SCIM_ENABLED=true
#
# Bearer Token（支持轮换）：
# - 允许逗号/空格分隔多个 token（active set），用于平滑轮换
# - 每个 token 既可以是 raw，也可以是 `sha256:<hex>`（推荐：避免把明文 secret 放进配置/日志系统）
#
# 例：两个 token 同时生效（轮换窗口）
SCIM_BEARER_TOKEN="sha256:<hex_v1>,sha256:<hex_v2>"

# 必填：该 SCIM 凭据唯一绑定的租户，防止令牌跨租户使用
SCIM_TENANT_ID="<tenant_uuid>"

# 可选：限制单次分页大小（默认 200）
SCIM_PAGE_SIZE_MAX=200

# 可选：SCIM 端点 IP allowlist（defense-in-depth；不配则不限制）
# - 逗号/空格分隔 CIDR
# - 一旦设置则 fail-closed（无法解析/不在范围内 => 403）
SCIM_IP_ALLOWLIST_CIDRS="203.0.113.0/24,198.51.100.10/32"

# 可选：允许 PATCH 组成员（默认 false）
SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED=false

# 可选：开启写入能力（默认全部关闭）
SCIM_USERS_CREATE_ENABLED=false
SCIM_USERS_PATCH_ACTIVE_ENABLED=false
SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED=false
SCIM_GROUPS_MUTATION_ENABLED=false
```

请求时带上：

- `Authorization: Bearer <SCIM_BEARER_TOKEN>`
- `X-Tenant-ID: <tenant_uuid>`（必须与 `SCIM_TENANT_ID` 一致）

> 生产环境建议配合：Ingress/网关 allowlist、IP 限制、以及 token 轮换流程。

### 1.1) 如何生成 `sha256:<hex>`（推荐）

用你自己的长随机 token（不要用短 token），然后生成 SHA256：

```bash
python - <<'PY'
import hashlib
token = "paste-your-long-random-token-here"
print("sha256:" + hashlib.sha256(token.encode("utf-8")).hexdigest())
PY
```

轮换建议：

1. 在 `SCIM_BEARER_TOKEN` 里同时保留 old + new（active set）
2. 确认 IdP 已切换到 new
3. 移除 old

---

## 2) 端点一览

SCIM base path：

```
/api/v1/scim/v2
```

### 2.1 Discovery（发现端点）

- `GET /ServiceProviderConfig`
- `GET /Schemas`
- `GET /ResourceTypes`

### 2.2 Users（读为主；写需显式开启）

- `GET /Users`（分页：`startIndex`/`count`）
- `GET /Users/{id}`
- `POST /Users`（可选，需 `SCIM_USERS_CREATE_ENABLED=true`）
- `PATCH /Users/{id}`（可选，仅支持 `active`；需 `SCIM_USERS_PATCH_ACTIVE_ENABLED=true`）

映射关系：
- `id`/`userName` → `tenant_members.user_id`
- `active` → `tenant_members.is_active`

默认策略：
- 新建用户默认 `role=viewer`，`is_current=false`
- `active` 未提供时默认 `true`

审计（audit actions）：
- `scim.user.create`
- `scim.user.patch`（active）

### 2.3 Groups（读为主；写需显式开启；membership PATCH 可选）

- `GET /Groups`（分页：`startIndex`/`count`）
- `GET /Groups/{id}`
- `POST /Groups`（可选，需 `SCIM_GROUPS_MUTATION_ENABLED=true`）
- `PUT /Groups/{id}`（可选，需 `SCIM_GROUPS_MUTATION_ENABLED=true`）
- `DELETE /Groups/{id}`（可选，需 `SCIM_GROUPS_MUTATION_ENABLED=true`）
- `PATCH /Groups/{id}`（可选，需 `SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED=true`）

映射关系：
- Group `id` → `tenant_groups.id`（UUID）
- `displayName` → `tenant_groups.name`
- `externalId` → `tenant_groups.external_id`
- `members[].value` → `tenant_group_members.user_id`

`externalId` 规则（推荐）：
- `externalId` 是可选字段；当提供时，要求 **tenant 内唯一**（冲突返回 409 / scimType=uniqueness）
- `POST/PUT` 目前只处理 `displayName`/`externalId`；成员变更请使用 `PATCH /Groups/{id}`

审计（audit actions）：
- `scim.group.create`
- `scim.group.put`
- `scim.group.delete`
- `scim.group.members.patch`

---

## 3) PATCH 组成员（可选）

启用：

```bash
SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED=true
```

示例：给组添加成员 / 移除成员（幂等；重复 add/remove 不会报错）。

```bash
curl -fsS \
  -H "Authorization: Bearer $SCIM_BEARER_TOKEN" \
  -H "X-Tenant-ID: $TENANT_ID" \
  -H "Content-Type: application/scim+json" \
  -X PATCH \
  "$BASE_URL/api/v1/scim/v2/Groups/$GROUP_ID" \
  -d '{
    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
    "Operations": [
      { "op": "Add", "path": "members", "value": [{"value": "alice"}, {"value": "bob"}] },
      { "op": "Remove", "path": "members[value eq \"charlie\"]" }
    ]
  }' | jq .
```

审计：
- action：`scim.group.members.patch`
- resource_type：`tenant_group`
- resource_id：`<group_id>`

---

## 4) 当前限制（重要）

- 默认仍然是 **读为主**：写入能力需要显式开启（见第 1 节 flags）。
- `PATCH /Users/{id}` 当前只支持 `active`（用于启用/停用）。
  - 可选：启用 `SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED=true` 时，停用会撤销该用户的 tenant group memberships（幂等）。
- `PATCH /Groups/{id}` 当前专注于成员增删；组属性更新走 `PUT /Groups/{id}`。
- `Users` 仅暴露 `tenant_members.user_id` 非空的成员；若你的租户成员尚未落库，请先通过现有登录/成员引导流程建立 `tenant_members`。
