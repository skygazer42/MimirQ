---
sidebar_label: "web/lib/api 模块"
sidebar_position: 2
---

# 数据集（前端）— web/lib/api 模块

## 模块位置

- [`web/lib/api/datasets.ts`](https://github.com/skygazer42/MimirQ/blob/main/web/lib/api/datasets.ts) — 导出 **`datasetApi`**，内部通过 `openapiRequest` / `apiClient` 调用 `/api/v1/datasets/...`。

## 方法分组（与 UI 大致对应）

| 区域 | `datasetApi` 方法（节选） |
| --- | --- |
| CRUD / 列表 | `create`, `list`, `get`, `update`, `delete`, `purge`, `clone` |
| 分类 | `listTree`, `create`, `update`, `move`, `delete`（分类树）, `getCategories`, `setCategories` |
| 入库策略 | `getIngestionPolicy`, `updateIngestionPolicy`, `importIngestionPolicy`, `exportIngestionPolicy`, `listIngestionPolicyVersions`, `rollbackIngestionPolicy` |
| 配置导入导出 | `exportConfig`, `importConfig`, `exportBundleZip`, `exportDocumentsNdjson` |
| 画像 | `getProfileSummary`, `listProfileFinding`, `listProfileBucketDocuments`, `startProfileScan`, `listProfileScanRuns`, `getProfileScanRun`, `exportProfileSummary`, `exportProfileHtml` |
| 预检 | `startPrecheckScan`, `listPrecheckScanRuns`, `getPrecheckScanRun`, `getPrecheckSummary`, `listPrecheckFiles`, `listPrecheckFinding`, `exportPrecheckSummary`, `exportPrecheckHtml`, `cancelPrecheckScan`, `getPrecheckSamples`, `getPrecheckNearDups`, `diffPrecheckScanRuns`, `suggestPrecheckIngestionPolicy`, `applyPrecheckIngestionPolicy` |
| 表 / TAG | `listTables`, `getTable`, `previewTable`, `queryTable`, `askTable`, `lotusSemFilter` |
| DB Catalog | `listDbCatalogTables`, `getDbCatalogTable`, `listDbCatalogProfiles` |
| 健康 / 统计 | `getHealth`, `getIngestionStats` |

类型定义来自生成的 `@/types`（与 OpenAPI 同步）；改后端后需重新导出 OpenAPI 并生成前端类型。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
