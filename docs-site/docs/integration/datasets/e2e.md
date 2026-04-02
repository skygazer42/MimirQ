---
sidebar_label: "数据集 E2E"
sidebar_position: 2
---

# 数据集 — 典型 E2E 序列

```mermaid
sequenceDiagram
  participant U as 用户/客户端
  participant FE as Next.js
  participant API as FastAPI /api/v1
  participant DB as PostgreSQL
  U->>FE: 打开数据集列表
  FE->>API: GET /datasets/
  API->>DB: 查询可见数据集
  DB-->>API: rows
  API-->>FE: JSON
  FE-->>U: 渲染列表
```

## 环境变量

对齐后端 `.env` 与前端 `NEXT_PUBLIC_*`（参见仓库 `docs/deployment` 与 Settings 页说明）。

## 排障入口

- [FE_BE_DEBUG.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
- [API_CONTRACT.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
