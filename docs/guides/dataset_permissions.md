# 数据集权限（Dataset Permissions）

本指南说明 MimirQ 的 **数据集级权限模型**，以及如何在 `partial_members` 模式下同时使用：
- 成员 allowlist（`partial_member_list`）
- 组 allowlist（`partial_group_list`）

> 原则：**默认 fail-closed**。当权限为 `partial_members` 时，只有命中 allowlist 的账号/组才能访问。

---

## 1) 权限枚举与语义

数据集权限由 `datasets.permission` 控制：

- `all_team_members`（默认）：租户内成员可读；写权限仍需 edit 角色/owner
- `only_me`：仅 dataset owner 可读（更严格）
- `partial_members`：owner + allowlist 可读

### 1.1 allowlist（仅在 `partial_members` 生效）

当 `permission=partial_members` 时，访问被允许当且仅当：

- `account_id == dataset.owner_id`（owner 永远允许）
- 或 `account_id ∈ partial_member_list`
- 或 `account_id` 属于任意 `partial_group_list` 中的 tenant group（组成员命中）

其中：
- `partial_member_list`：账号列表（字符串，通常为 JWT `sub`）
- `partial_group_list`：组 id 列表（UUID；tenant-scoped）

> 组 id 可通过 `GET /api/v1/groups` 获取（返回 `id` + `name`）。

---

## 2) API 使用方式

### 2.1 创建数据集（带 partial group allowlist）

`POST /api/v1/datasets`

```json
{
  "name": "Finance KB",
  "description": "Finance-only documents",
  "permission": "partial_members",
  "partial_member_list": ["alice", "bob"],
  "partial_group_list": [
    "11111111-1111-1111-1111-111111111111",
    "22222222-2222-2222-2222-222222222222"
  ]
}
```

### 2.2 更新数据集权限 / allowlist

`PATCH /api/v1/datasets/{dataset_id}`

```json
{
  "permission": "partial_members",
  "partial_member_list": ["alice"],
  "partial_group_list": ["11111111-1111-1111-1111-111111111111"]
}
```

注意：
- 当 `permission != partial_members` 时，后端会清空 allowlist（成员/组）
- allowlist 会做校验：
  - `partial_member_list`：成员必须存在于当前租户 `tenant_members`（防拼写错误导致“以为限制了但实际没生效”）
  - `partial_group_list`：组必须存在于当前租户 `tenant_groups`
- allowlist size 有上限（默认 200，best-effort 截断/拒绝）

---

## 3) 常见排障

### 3.1 访问被拒绝（403）

优先检查：
1. 当前账号是否为 dataset owner
2. dataset.permission 是否为 `partial_members`（或其他更严格模式）
3. `partial_member_list` 是否包含当前账号
4. `partial_group_list` 是否包含当前账号所在组的 `group_id`

### 3.2 组 allowlist 配置了但不生效

常见原因：
- 组未同步/未添加成员（可用 `GET /api/v1/groups/{group_id}/members` 验证）
- JWT groups claim 同步未开启或 claim 名不匹配（见：`docs/guides/oidc_groups_claim.md`）

