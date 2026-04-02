---
sidebar_label: "运维 / SRE"
sidebar_position: 3
---

# 运维 / SRE — 从哪开始

## 本页回答的业务问题

你要保证 **服务可用、可恢复、可观测**：故障时要知道先查哪一层（网关 / 应用 / 依赖 / 数据面），以及 **业务上** 何时算恢复（能登录、能上传、能问答）。

## 建议阅读路径

1. **手册内 Ops 分区**：[运维总览](../../ops/welcome) · [健康探针](../../ops/health-probes) · [可观测性](../../ops/observability) · [部署与 Runbook](../../ops/deployment)。
2. **集成向健康与日志**：[请求关联与排障](../patterns/observability-requests.md)。
3. **业务止损剧本**（用户侧可见故障）：[文档卡在解析或索引](../tasks/document-stuck)。

## 快速检查（与 OpenAPI 对齐）

| 检查 | Path（前缀 `/api/v1`） |
| --- | --- |
| 存活 | `GET /health` |
| 就绪 | `GET /health/ready` |

具体以当前 OpenAPI **health** 分组为准。

## 仓库 Runbook

- [docs/deployment/runbook.md](https://github.com/skygazer42/MimirQ/blob/main/docs/deployment/runbook.md)

## 与开发协作

- 变更网关、超时、body 限制时，同步通知集成方（上传与 SSE 最易受影响）。
