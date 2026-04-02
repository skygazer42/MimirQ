---
sidebar_label: "用户路径与入口"
sidebar_position: 1
---

# 文档与入库（前端）— 用户路径与入口

## 说明

文档列表、上传、解析预览、批量入库等 **分散在多个产品模块**，并非单一 `/documents` 路由。常见入口如下（路径相对 `web/app`，不含可选 `[locale]`）。

| 路由 | 文件 | 说明 |
| --- | --- | --- |
| `/knowledge/ingestion` | `knowledge/ingestion/page.tsx` | 知识入库、上传与运行态 |
| `/parsing` | `parsing/page.tsx` | 解析工作台 / 预览 |
| `/datasets/[id]/ingestion` | `datasets/[id]/ingestion/page.tsx` | 按数据集的入库与文档统计 |
| `/knowledge/quarantine` | `knowledge/quarantine/page.tsx` | 隔离区与审核（与文档列表强相关） |

若新增页面，请在本表与 [FE/BE 对照矩阵](../../integration/generated/fe-be-matrix.mdx) 所依据的路由列表中保持一致性。

## API 封装

- 核心：[`web/lib/api/documents.ts`](https://github.com/skygazer42/MimirQ/blob/main/web/lib/api/documents.ts)
- 连接器 / 管道等：[`connectors.ts`](https://github.com/skygazer42/MimirQ/blob/main/web/lib/api/connectors.ts)、[`pipeline.ts`](https://github.com/skygazer42/MimirQ/blob/main/web/lib/api/pipeline.ts)（按功能选用）

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
