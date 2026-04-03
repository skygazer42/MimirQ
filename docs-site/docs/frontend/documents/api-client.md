---
sidebar_label: "web/lib/api 模块"
sidebar_position: 2
---

# 文档管理 — web/lib/api 模块

## 模块位置

`web/lib/api/documents.ts` 导出 `documentApi` 对象，覆盖文档全生命周期操作。

## 方法索引

| 分组 | 方法 | HTTP | 说明 |
|------|------|------|------|
| **上传** | `upload` | POST `/documents/upload` | 单文件 multipart 上传 |
| | `uploadFromUrl` | POST `/documents/upload-url` | URL 上传 |
| | `uploadBatch` | POST `/documents/upload-batch` | 批量上传 |
| **列表/详情** | `list` | GET `/documents/` | 分页列表，支持多维筛选 |
| | `get` | GET `/documents/{id}` | 单文档详情 |
| | `stats` | GET `/documents/stats` | 文档统计 |
| | `folders` | GET `/documents/folders` | 文件夹树 |
| **生命周期** | `health` | GET `/documents/{id}/health` | 文档健康卡片 |
| | `getTimeline` | GET `/documents/{id}/timeline` | 事件时间线 |
| | `getAccess / updateAccess` | GET/PUT | 文档访问控制 |
| **解析** | `getParsedContent` | GET `/documents/{id}/parsed-content` | 解析后 Markdown |
| | `chunkPreview` | POST `/documents/chunk-preview` | Chunk 预览 |
| **分块** | `listChunks` | GET `/documents/{id}/chunks` | Chunk 列表 |
| | `createChunk / patchChunk` | POST/PATCH | Chunk CRUD |
| | `reembed` | POST | 重新嵌入 |
| **版本** | `listVersions` | GET | 版本列表 |
| | `diffVersions` | GET | 版本差异 |
| **批量** | `batchDelete / batchRetry` | POST | 批量操作 |
| | `batchMove / batchAccess` | POST | 批量移动/权限 |

## 辅助模块

| 文件 | 导出 | 说明 |
|------|------|------|
| `document-helpers.ts` | `appendChunkPreviewFormFields` | Chunk 预览参数构建 |
| `connectors.ts` | `connectorApi` | 连接器配置与运行 |
| `pipeline.ts` | `pipelineApi` | 入库管线配置 |

:::info
文件上传会自动选择解析器：`resolveParserBackendForFilename()` 根据文件扩展名决定 `parser_backend` 参数。
:::

## 上传调用示例

```typescript
// 单文件上传
const formData = new FormData();
formData.append('file', file);
formData.append('dataset_id', datasetId);
const doc = await documentApi.upload(formData);
```

:::tip
批量上传使用 `uploadBatch` 而非循环调用 `upload`，可减少请求数并支持后端原子性处理。
:::

## 相关链接

- [用户路径与入口](./overview) — 页面与路由
- [后端 · 文档管线](../../backend/documents/pipeline.md) — 后端入库流程
