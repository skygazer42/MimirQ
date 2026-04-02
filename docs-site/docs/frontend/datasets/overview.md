---
sidebar_label: "用户路径与入口"
sidebar_position: 1
---

# 数据集（前端）— 用户路径与入口

## 路由与页面（`web/app/datasets`）

Next.js App Router；下列为常见 `page.tsx` 路径（不含可选 `[locale]` 前缀）。`[id]` 为数据集 ID。

| 路由 | 文件 | 说明 |
| --- | --- | --- |
| `/datasets` | `datasets/page.tsx` | 数据集列表与入口 |
| `/datasets/[id]/precheck` | `datasets/[id]/precheck/page.tsx` | 预检 |
| `/datasets/[id]/profile` | `datasets/[id]/profile/page.tsx` | 画像 |
| `/datasets/[id]/health` | `datasets/[id]/health/page.tsx` | 健康度 |
| `/datasets/[id]/db-catalog` | `datasets/[id]/db-catalog/page.tsx` | DB Catalog |
| `/datasets/[id]/tables` | `datasets/[id]/tables/page.tsx` | 表 / 查询 |
| `/datasets/[id]/workflow` | `datasets/[id]/workflow/page.tsx` | 工作流 |
| `/datasets/[id]/ingestion` | `datasets/[id]/ingestion/page.tsx` | 入库与统计 |
| `/datasets/[id]/evidence` | `datasets/[id]/evidence/page.tsx` | 证据相关入口 |
| `/datasets/[id]/kg` | `datasets/[id]/kg/page.tsx` | 知识图谱 |

权限与菜单可见性受 RBAC / feature flag 影响；以实际 UI 为准。

## API 封装

- 主要使用 [`web/lib/api/datasets.ts`](https://github.com/skygazer42/MimirQ/blob/main/web/lib/api/datasets.ts) 中 `datasetApi` 对象（详见本站「web/lib/api 模块」页）。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
