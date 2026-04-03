---
sidebar_label: "状态与任务"
sidebar_position: 4
---

# 文档处理状态与异步任务

文档从上传到可检索，需经过异步处理流水线。本页详解状态机、webhook 通知和监控策略。

## 文档处理状态机

```mermaid
stateDiagram-v2
    [*] --> pending : 上传成功
    pending --> processing : enqueue_document_processing

    state processing {
        [*] --> parsing
        parsing --> chunking
        chunking --> embedding
        embedding --> vector_write
        vector_write --> stage_completed
    }

    processing --> completed : 全阶段完成
    processing --> failed : 异常
    processing --> quarantined : 治理拦截
    processing --> cancelled : 用户取消

    failed --> pending : retry
    completed --> pending : reingest
```

## 状态字段

| 字段 | 值域 | 说明 |
|------|------|------|
| `status` | pending/processing/completed/failed/quarantined/cancelled | 主状态 |
| `current_stage` | parsing/chunking/embedding/vector_write/completed | 处理子阶段 |
| `processing_progress` | 0-100 | 百分比进度 |
| `error_message` | text | 失败时的错误详情 |

## 状态查询接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{document_id}/status` | 返回 `DocumentStatus`（轻量） |
| `GET` | `/{document_id}` | 返回 `DocumentDetail`（完整） |
| `GET` | `/{document_id}/timeline` | 处理时间线事件列表 |

## 前端轮询策略

```mermaid
sequenceDiagram
    participant FE as 前端
    participant API as Backend
    participant Worker as 处理 Worker

    FE->>API: POST /upload (文件)
    API-->>FE: 201 {id, status: "pending"}
    API->>Worker: enqueue task
    loop 轮询（2-5s 间隔）
        FE->>API: GET /{id}/status
        API-->>FE: {status, current_stage, progress}
    end
    Worker->>API: 更新 status=completed
    FE->>API: GET /{id}/status
    API-->>FE: {status: "completed", chunk_count: 42}
```

:::tip 轮询建议
- 初始间隔 2 秒，逐步退避到 5 秒
- `processing_progress` 可驱动进度条
- 到达终态（completed/failed/quarantined/cancelled）后停止轮询
- 批量上传场景建议用 `GET /documents/?dataset_id=X&status=processing` 统一查询
:::

## 操作控制

| 操作 | 路径 | 前置条件 |
|------|------|----------|
| 取消 | `POST /{id}/cancel` | status 为 pending 或 processing |
| 重试 | `POST /{id}/retry` | status 为 failed |
| 重新入库 | `POST /batch/reingest` | status 为 completed |
| 批量重试 | `POST /batch/retry` | 批量操作失败文档 |

## Timeline 事件

`GET /{document_id}/timeline` 返回按时间排序的处理事件列表（`DocumentTimelineResponse`），每个事件包含：

| 字段 | 说明 |
|------|------|
| `event` | 事件类型 |
| `stage` | 关联阶段 |
| `timestamp` | 事件时间 |
| `details` | 事件详情（JSON） |

## 相关链接

- [流水线阶段](./pipeline.md)
- [概述](./overview.md)
- [排障](./troubleshooting.md)
- [Redoc API 文档](https://skygazer42.github.io/MimirQ/)
