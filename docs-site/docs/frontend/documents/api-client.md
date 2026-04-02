---
sidebar_label: "web/lib/api 模块"
sidebar_position: 2
---

# 文档与入库（前端）— web/lib/api 模块

## 模块位置

- [`web/lib/api/documents.ts`](https://github.com/skygazer42/MimirQ/blob/main/web/lib/api/documents.ts) — 文档 CRUD、上传、批量、分块、版本、解析内容等。

## 能力分组（节选）

| 能力 | 说明 |
| --- | --- |
| 列表 / 详情 / 删除 | `list`, `get`, `delete` 及批量 `batchDelete` 等 |
| 上传 | `upload`（multipart）、`uploadUrl`、`uploadBatch`、`applyBatchUploadUrls`、`getBatchUploadStatus` |
| 状态与生命周期 | `getStatus`, `cancel`, `retry`, `getTimeline`, `getLifecycleMetadata`, `patchLifecycleMetadata` |
| 分块 | `listChunks`, `getChunk`, `createChunk`, `patchChunk`, `deleteChunk`, `matches`, `reembed`, `enableChunk`, `disableChunk` |
| 解析与预览 | `getParsedContent`, `preview`, `chunkPreview`, `chunkPreviewBySha`, `manual` 等（以源码与 OpenAPI 为准） |
| 版本 / 管道 | `listVersions`, `activateVersion`, `deleteVersion`, `diffVersions`, `getPipeline`, `patchPipeline` |
| 元数据 / 访问 | `patchMetadata`, `getAccess`, `putAccess`, 批量 `batchAccess` / `batchMetadata` / `batchMove` 等 |

完整 path 与 method 以 OpenAPI **Documents** 标签为准；本文件仅便于从前端定位入口。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
