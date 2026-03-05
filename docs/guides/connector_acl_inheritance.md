# Connector ACL 继承（Source ACL → Document ACL）运维指南

本指南面向运维/管理员，说明如何让连接器在导入时**继承源系统权限**（GitHub/Confluence/Drive 等），并将其映射到 MimirQ 的**文档级 ACL（Security Trimming）**。

> 前置知识：文档级 ACL 本质上只会“收紧权限”，不会“放宽权限”。详情见：[docs/guides/document_acl.md](./document_acl.md)。

---

## 1) 目标与边界

**目标**
- 当源系统对象（仓库/页面/文件）在源侧发生权限变化时，导入到 MimirQ 的文档能体现同等“可见范围”（以 tenant groups/doc ACL 的形式）。

**边界**
- 当前实现优先覆盖“常见企业权限模式”：**按 group/team 的可见性**。
- 对于仅按“单个用户”授权的场景（例如 Drive 仅分享给某些个人），系统会倾向于 **fail-closed**（默认 owner-only），避免误放宽权限。
- 数据集权限仍然是第一道门槛：用户必须先能读数据集，再通过文档级 ACL 才能看到文档。

---

## 2) 核心概念：Source Principal Key 与 tenant_groups.external_id

连接器在继承源权限时，会把源系统中的“可读主体”（team/group 等）转换成**稳定、可比较的字符串 key**（source principal key）。

然后通过 `tenant_groups.external_id` 把这些 key 映射到租户内组（tenant group）：

- 你可以通过 **SCIM**（推荐）或 **Groups API** 创建组，并设置 `external_id`
- 连接器会用这些 `external_id` 来找对应的 `tenant_groups.id`，最后写入文档 ACL 的 `partial_group_list`

> 这意味着：你不需要把“源系统 group/team 成员”同步到 MimirQ；你只要保证 **MimirQ tenant group 的成员**与源系统的授权主体在语义上对应即可（通常由 IdP/SCIM/OIDC groups 完成）。

---

## 3) 准备工作：创建 tenant groups（SCIM/Groups API）

### 3.1 通过 Groups API（手动）

创建组并写入 `external_id`：

```bash
curl -X POST "http://localhost:8000/api/v1/groups" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Engineering",
    "external_id": "github:team:acme/dev"
  }'
```

### 3.2 通过 SCIM（推荐）

如果你已启用 SCIM v2（企业目录），推荐由 IdP/目录系统自动下发组与成员关系。

关键点：
- SCIM group 的 `externalId` 将落到 `tenant_groups.external_id`
- 你需要保证 `externalId` 使用下文约定的格式（或至少与连接器生成的 key 一致）

---

## 4) 连接器配置：启用 source_acl

连接器的 `config` 中新增 `source_acl` 字段（可选）：

```json
{
  "source_acl": {
    "mode": "inherit",
    "fallback_mode": "partial_members",
    "allow_anyone": false
  }
}
```

字段含义：
- `mode`
  - `disabled`（默认）：不继承源权限
  - `inherit`：开启继承（源权限 → 文档 ACL）
- `fallback_mode`：当无法映射到任何 tenant group 时的兜底策略（默认 `partial_members`，即 owner-only，fail-closed）
- `allow_anyone`：仅对“源侧公开（anyone）”有意义的连接器有效；默认关闭。开启后可能会将文档设为 `all_team_members`（仍受数据集权限约束）

**优先级说明**
- 若你在 `access` 中显式设置了 `mode != inherit`（例如强制 `only_me`/`partial_members`），系统会认为你在做“手工覆盖”，并跳过 `source_acl` 的继承逻辑。

---

## 5) 各连接器 Source Principal Key 约定与示例

### 5.1 GitHub Repo（`github_repo`）

**Key 格式**
- GitHub 团队（org/team）→ `github:team:<org>/<team_slug>`

示例：
- `github:team:acme/dev`
- `github:team:acme/security`

**连接器配置示例**

```json
{
  "connector_id": "github_repo",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "repo": "acme/demo",
    "branch": "main",
    "include_extensions": [".md", ".txt"],
    "auth": { "type": "bearer", "token": "ghp_xxx" },
    "source_acl": { "mode": "inherit", "fallback_mode": "partial_members" }
  }
}
```

**常见坑**
- 需要 GitHub token 具备列出 repo team 的权限（通常需要 `read:org`），否则团队列表可能为空，最终触发 fail-closed（owner-only）。

### 5.2 Confluence Space（`confluence_space`）

**Key 格式**
- Confluence group → `confluence:group:<group_name>`

示例：
- `confluence:group:confluence-users`
- `confluence:group:space-docs-admins`

**权限继承范围**
- 当前实现聚焦 **页面 read restrictions**（页面限制可见范围）
  - 页面未设置 restrictions：不额外收紧（保持 `access=inherit` 的语义）
  - 页面设置了 restrictions 但无法映射：按 `fallback_mode` fail-closed

**连接器配置示例**

```json
{
  "connector_id": "confluence_space",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "base_url": "https://example.atlassian.net/wiki",
    "space_key": "DOCS",
    "auth": { "type": "bearer", "token": "confluence_api_token_or_oauth" },
    "ingest_method": "api_view",
    "source_acl": { "mode": "inherit", "fallback_mode": "partial_members" }
  }
}
```

### 5.3 Google Drive 文件（`drive_files`）

**Key 格式**
- Drive group → `drive:group:<email>`

示例：
- `drive:group:eng@acme.com`
- `drive:group:all@acme.com`

**连接器配置示例（需 OAuth Bearer token）**

```json
{
  "connector_id": "drive_files",
  "dataset_id": "00000000-0000-0000-0000-000000000000",
  "config": {
    "urls": ["https://drive.google.com/file/d/<file_id>/view?usp=sharing"],
    "auth": { "type": "bearer", "token": "ya29.xxx" },
    "source_acl": { "mode": "inherit", "fallback_mode": "partial_members" }
  }
}
```

**常见坑**
- Drive 权限需要通过 Google Drive API 拉取，通常需要 token 具备 `drive.readonly` 类 scope；没有 token 或 scope 不足时，会触发 fail-closed（owner-only）。

---

## 6) 观测与排障

### 6.1 Prometheus 指标（PII-safe、低基数）

当 `PROMETHEUS_ENABLED=true` 时，会暴露以下指标（示例）：

- `connector_acl_apply_total{connector_id="github_repo",mode="partial_members",shape="groups_only"}`
- `connector_acl_apply_errors_total{connector_id="confluence_space",mode="partial_members"}`

`shape` 用于粗粒度观察 allowlist 形态：
- `inherit` / `only_me` / `all_team_members`
- `partial_empty`（owner-only）
- `groups_only` / `members_only` / `members_and_groups`

### 6.2 典型现象与处理

**现象：导入后的文档“只有我能看到”**
- 可能原因：源 ACL 继承启用后，没有映射到任何 tenant group（或源侧权限拉取失败）
- 处理：
  1) 检查该 connector 的 `auth` 是否有权限访问源侧 ACL API
  2) 检查 `tenant_groups.external_id` 是否与 source principal key 一致
  3) 检查 `fallback_mode` 是否被设置为 `partial_members`（默认）

**现象：文档可见范围过大**
- 检查是否在 `access` 中误设了 `all_team_members` 或 `inherit`
- 强烈建议：在启用 `source_acl` 时，保持数据集权限为最小集合，并让 doc ACL 只做收紧

