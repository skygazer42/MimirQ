---
sidebar_label: "知识库可对用户问答"
sidebar_position: 2
---

# 知识库问答验收

用户提问时能命中已入库内容，回答有据可查，满足"知识库可用"的验收口径。

## 前置条件

- 已完成 [新租户首日上线](./go-live-tenant.md)：有效会话、`dataset_id`、至少一份处理完成的文档
- 明确当前环境的检索 / RAG 配置（以 OpenAPI 与部署配置为准）

## 步骤详解

### Step 1 — 确认文档可检索

```bash
# 确认文档状态为 completed
curl -s "$BASE_URL/api/v1/documents/$DOCUMENT_ID/status" \
  -H "Authorization: Bearer $TOKEN" | jq '.status'
# 预期: "completed"
```

:::tip
文档需经过解析 → 切块 → embedding → 索引全流程后才可被检索。如果状态为 `completed` 但仍无法检索，检查切块是否生成。
:::

### Step 2 — 验证检索命中

```bash
# 用文档中可唯一命中的短语进行检索
curl -X POST "$BASE_URL/api/v1/retrieval/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "query": "文档中的关键短语",
    "dataset_ids": ["'"$DATASET_ID"'"],
    "top_k": 5
  }'
```

确认返回的片段中包含预期文档的内容。

### Step 3 — 发起 RAG 对话

```bash
# 非流式请求
curl -X POST "$BASE_URL/api/v1/chat/completions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "messages": [{"role": "user", "content": "你的测试问题"}],
    "dataset_ids": ["'"$DATASET_ID"'"],
    "stream": false
  }'
```

### Step 4 — 验证答案质量

检查返回结果中：
- 回答内容与文档相关
- 引用（citation / source）指向正确的文档或片段
- `request_id` 或 trace 可用于后续调试

## 验收标准

| 项目 | 标准 |
|------|------|
| 内容可检索 | 针对已知片段的提问返回相关结果 |
| 配置可重复 | 同一数据集上可复现相同检索行为 |
| 可解释未命中 | 能区分：内容未索引 / 过滤过严 / 模型策略问题 |

## 排障速查

| 现象 | 可能原因 | 建议动作 |
|------|----------|----------|
| 回答与文档无关 | 数据集/会话错配、检索上下文不正确 | 核对 `dataset_ids` 参数 |
| 始终空结果 | 切块未生成、索引延迟、权限过滤 | 查文档状态与切块列表 |
| 延迟极高 | embedding 服务慢、向量库负载高 | 参见 [可观测性](../patterns/observability-requests.md) |
| 流式无响应 | 代理缓冲未关闭 | 参见 [SSE 流式](../patterns/sse-streaming.md) |

## 相关链接

- [新租户首日上线](./go-live-tenant.md) — 前置步骤
- [场景: 上传后对话](../scenarios/s01-upload-chat.md) — 完整 E2E 场景
- [场景: 检索调试](../scenarios/s04-retrieval-debug.md) — 检索未命中时的深入调试
- [Redoc — API 完整参考](https://skygazer42.github.io/MimirQ/)
