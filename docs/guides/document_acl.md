# 文档级访问控制（Security Trimming）

本功能用于在“数据集权限”基础上，进一步对 **单个文档** 做访问限制（企业检索/企业 RAG 常见能力：security trimming）。

核心原则：**文档级 ACL 只做“收紧”，不做“放宽”**。也就是说，用户必须先满足数据集的可读权限，然后再通过文档级 ACL 的校验，才能看到该文档与其切块/引用。

## 访问模式

文档表字段：

- `documents.owner_id`：文档 owner（通常是上传者 / connector run 发起者）
- `documents.access_mode`：访问模式（为空/NULL 等同于 `inherit`）

支持的 `access_mode`：

- `inherit`（默认）：仅依赖数据集权限（`access_mode = NULL`）
- `only_me`：仅 owner 可见
- `partial_members`：owner + allowlist 可见（allowlist 在 `document_permissions` 表）
- `all_team_members`：租户内成员可见（但仍受数据集权限限制）

额外规则：

- **数据集 owner 旁路（bypass）**：数据集 owner 始终可以访问其数据集下的文档（便于管理/运维）

## API

获取文档 ACL：

- `GET /api/v1/documents/{document_id}/access`

更新文档 ACL（需要数据集写权限；若文档无 dataset 绑定，则要求租户 edit 角色）：

- `PUT /api/v1/documents/{document_id}/access`

请求体示例：

```json
{
  "mode": "partial_members",
  "partial_member_list": ["alice", "bob"]
}
```

注意：

- `mode != partial_members` 时，后端会自动清空 `partial_member_list`
- `partial_member_list` 会校验“成员必须存在于当前租户 tenant_members”

## 对检索与引用的影响

MimirQ 的 RAG/Chat 检索侧会在“默认文档范围”与“显式 document_ids”两种场景下做权限裁剪：

- 先做数据集权限过滤
- 再做文档级 ACL 过滤（fail-closed）

这确保了：

- 文档列表不会“泄漏”不可见文档
- 引用/切块不会跨权限返回

