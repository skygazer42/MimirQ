---
sidebar_label: "新租户首日上线"
sidebar_position: 1
---

# 新租户首日上线

在第一个工作日内达成可演示状态：**有人能登录、至少一个数据集、能上传并看到文档处理进度**。

## 前置条件

- MimirQ 实例已部署且可访问，Base URL 已知
- 具备管理员权限的账号
- 准备一份小体积、无敏感信息的测试文件（PDF / Office / 纯文本）

## 步骤详解

### Step 1 — 登录并验证会话

```bash
# 登录获取 Token
curl -X POST "$BASE_URL/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"username": "admin@example.com", "password": "your-password"}'

# 验证 Token 有效
curl -s "$BASE_URL/api/v1/auth/me" \
  -H "Authorization: Bearer $TOKEN" | jq .
```

:::info
Token 格式与刷新策略以 [Redoc auth 分组](https://skygazer42.github.io/MimirQ/) 为准。开发环境可能支持 Header 调试模式，但**生产环境必须使用正式认证**。
:::

### Step 2 — 创建数据集

```bash
curl -X POST "$BASE_URL/api/v1/datasets/" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "onboarding-test",
    "description": "首日上线测试数据集"
  }'
# 记录返回的 dataset_id
```

### Step 3 — 上传测试文档

```bash
curl -X POST "$BASE_URL/api/v1/documents/upload" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@test-document.pdf" \
  -F "dataset_id=$DATASET_ID"
# 记录返回的 document_id
```

### Step 4 — 确认处理进度

```bash
# 轮询文档状态，直到进入终态
curl -s "$BASE_URL/api/v1/documents/$DOCUMENT_ID/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.status'
```

状态流转：`pending` → `processing` → `completed`（或 `failed`）。

### Step 5 — Web 验收（可选）

在浏览器打开数据集与文档页面，确认列表与状态与 API 一致。

## 验收标准

| 项目 | 标准 |
|------|------|
| 登录与会话 | Token 有效，`/auth/me` 返回预期用户 |
| 数据集 | 至少一个 `dataset_id` 可用于上传 |
| 文档 | 上传成功返回 `document_id`，状态可查询 |
| 可追溯 | 团队内能复述使用的环境、数据集、文件信息 |

## 排障速查

| 现象 | 可能原因 | 建议动作 |
|------|----------|----------|
| 401 / 403 | Token 过期、权限不足、租户头缺失 | 参见 [认证模式](../patterns/auth-modes.md) |
| 上传 400/415 | 格式不支持、体积超限、multipart 字段错误 | 参见 [文件上传](../patterns/multipart-upload.md) |
| 文档长期 `processing` | 解析器未就绪、队列积压 | 转 [文档卡住排障](./document-stuck.md) |
| 422 | 请求体字段不匹配 | 对照 [Redoc](https://skygazer42.github.io/MimirQ/) 必填字段 |

:::warning
如果多个文档同时卡住，优先排查 Worker 队列与解析器依赖，而非逐个文档排障。
:::

## 相关链接

- [知识库问答](./knowledge-base-qa.md) — 从"能传"到"能答"
- [文档卡住排障](./document-stuck.md) — 处理进度异常时的诊断路径
- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
