# SCIM v2（Enterprise，可选）

本指南说明如何在 MimirQ 中启用 **SCIM v2** 端点，用于企业 IdP 的目录对接与（可选）组成员变更。

> 设计原则：**默认关闭、fail-closed、tenant-safe**。只在显式开启 `SCIM_ENABLED=true` 时暴露端点。

---

## 1) 启用开关与鉴权方式

SCIM 端点默认关闭。启用后使用 **静态 Bearer Token** 鉴权（便于 Okta/AzureAD/Keycloak 等对接）。

```bash
SCIM_ENABLED=true
SCIM_BEARER_TOKEN="<a long random secret>"

# 可选：限制单次分页大小（默认 200）
SCIM_PAGE_SIZE_MAX=200

# 可选：允许 PATCH 组成员（默认 false）
SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED=false
```

请求时带上：

- `Authorization: Bearer <SCIM_BEARER_TOKEN>`
- `X-Tenant-ID: <tenant_uuid>`（与现有多租户 header 机制一致）

> 生产环境建议配合：Ingress/网关 allowlist、IP 限制、以及 token 轮换流程。

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

### 2.2 Users（只读）

- `GET /Users`（分页：`startIndex`/`count`）
- `GET /Users/{id}`

映射关系：
- `id`/`userName` → `tenant_members.user_id`

### 2.3 Groups（只读，membership PATCH 可选）

- `GET /Groups`（分页：`startIndex`/`count`）
- `GET /Groups/{id}`
- `PATCH /Groups/{id}`（可选，需 `SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED=true`）

映射关系：
- Group `id` → `tenant_groups.id`（UUID）
- `displayName` → `tenant_groups.name`
- `externalId` → `tenant_groups.external_id`
- `members[].value` → `tenant_group_members.user_id`

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

- 目前 **Users/Groups 为只读**（不支持 SCIM Create/Update/Delete）。
- 组成员 PATCH 默认关闭，需要显式开启。
- `Users` 仅暴露 `tenant_members.user_id` 非空的成员；若你的租户成员尚未落库，请先通过现有登录/成员引导流程建立 `tenant_members`。

