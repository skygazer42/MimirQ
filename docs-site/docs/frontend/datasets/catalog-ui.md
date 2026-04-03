---
sidebar_label: "DB Catalog 界面"
sidebar_position: 11
---

# 数据集 — DB Catalog 界面

## 功能概述

DB Catalog 页面展示数据集中的结构化表资产，支持浏览表结构、列信息和数据画像快照。

## 组件结构

```mermaid
graph TD
  A[DatasetsPage db-catalog Tab] --> B[表列表 DbCatalogTablesList]
  A --> C[表详情 DbCatalogTableDetail]
  B --> D[搜索与筛选]
  C --> E[列定义]
  C --> F[画像快照]
  C --> G[索引信息]
```

## 关键交互

| 操作 | API 调用 | 说明 |
|------|----------|------|
| 浏览表列表 | `datasetApi.listDbCatalogTables()` | 分页表资产列表 |
| 查看表详情 | `datasetApi.getDbCatalogTable()` | 列定义、索引等 |
| 画像快照 | `datasetApi.listDbCatalogProfiles()` | 历史画像快照 |

## 表信息展示

表详情页以表格形式展示：
- **列定义**: 列名、类型、是否可空、默认值
- **索引**: 索引名称、列组合、唯一性
- **画像统计**: 空值率、基数、最大/最小值等

## 数据流

```mermaid
sequenceDiagram
  participant U as 用户
  participant C as CatalogUI
  participant API as datasetApi
  U->>C: 选择数据集 db-catalog Tab
  C->>API: listDbCatalogTables()
  API-->>C: 表列表
  U->>C: 点击表名
  C->>API: getDbCatalogTable(tableId)
  API-->>C: 列定义 + 索引
  C->>API: listDbCatalogProfiles(tableId)
  API-->>C: 画像快照
```

:::info
DB Catalog 功能依赖后端连接器采集元数据。如果数据集未配置数据库连接器，该 Tab 不显示内容。
:::

:::tip
表列表支持按表名搜索，输入关键词后实时过滤。列定义表格支持按列名排序。
:::

## 相关链接

- [web/lib/api 模块](./api-client) — Catalog API 方法
- [表 / TAG 界面](./tables-ui) — SQL 查询界面
