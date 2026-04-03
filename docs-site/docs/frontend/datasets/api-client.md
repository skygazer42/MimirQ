---
sidebar_label: "web/lib/api 模块"
sidebar_position: 2
---

# 数据集 — web/lib/api 模块

## 模块位置

`web/lib/api/datasets.ts` 导出 `datasetApi` 对象，通过 `openapiRequest` / `apiClient` 调用后端 REST API。

## 方法索引

| 分组 | 方法 | HTTP | 说明 |
|------|------|------|------|
| **CRUD** | `create` | POST `/datasets/` | 新建数据集 |
| | `list` | GET `/datasets/` | 分页列表，支持 `category_id` 过滤 |
| | `get` | GET `/datasets/{id}` | 单条详情 |
| | `update` | PATCH `/datasets/{id}` | 更新元数据 |
| | `delete` | DELETE `/datasets/{id}` | 删除 |
| | `purge` | POST `/datasets/{id}/purge` | 清理已删除文档 |
| | `clone` | POST `/datasets/{id}/clone` | 克隆数据集 |
| **分类树** | `listTree` | GET `/datasets/categories/tree` | 完整分类树 |
| | `getCategories / setCategories` | GET/PUT | 数据集所属分类 |
| **入库策略** | `getIngestionPolicy` | GET | 获取策略 |
| | `updateIngestionPolicy` | PUT | 更新策略 |
| | `importIngestionPolicy` | POST (FormData) | 导入策略文件 |
| | `exportIngestionPolicy` | GET → Blob | 导出策略 |
| | `rollbackIngestionPolicy` | POST | 回滚到历史版本 |
| **画像** | `getProfileSummary` | GET | 画像摘要 |
| | `startProfileScan` | POST | 启动画像扫描 |
| | `listProfileScanRuns` | GET | 扫描历史 |
| **预检** | `startPrecheckScan` | POST | 启动预检扫描 |
| | `getPrecheckSummary` | GET | 预检摘要 |
| | `suggestPrecheckIngestionPolicy` | GET | 根据预检结果建议策略 |
| **表 / TAG** | `queryTable` | POST | SQL 查询 |
| | `askTable` | POST | 自然语言查询 |
| | `lotusSemFilter` | POST | 语义过滤 |
| **健康** | `getHealth` | GET | 数据集健康度 |
| | `getIngestionStats` | GET | 入库统计 |

:::info
所有类型定义来自 `@/types`（由 openapi-typescript 生成）。后端 OpenAPI 变更后需重新生成前端类型。
:::

## 调用示例

```typescript
// 获取数据集列表（带分类过滤）
const result = await datasetApi.list({
  category_id: selectedCategoryId,
  skip: page * pageSize,
  limit: pageSize,
});

// 启动预检扫描
const run = await datasetApi.startPrecheckScan(datasetId);
```

## SSE 流式接口

`web/lib/api/streaming.ts` 提供 `sseApi.streamPrecheckScanEvents()`，用于预检扫描实时事件推送。

:::tip
SSE 连接断开时前端会自动降级为轮询模式，无需手动处理重连。
:::

## 请求取消

所有 API 方法支持传入 `AbortSignal` 参数。页面卸载或切换数据集时，前端通过 `AbortController` 取消进行中的请求，避免状态竞争。

## 相关链接

- [用户路径与入口](./overview) — 页面与路由
- [后端 · 数据集 API](../../backend/datasets/overview.md) — 后端实现
