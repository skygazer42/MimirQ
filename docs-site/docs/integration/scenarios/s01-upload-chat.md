---
sidebar_label: "上传后对话"
sidebar_position: 1
---

# 场景 — 上传后对话

## 概述

本页属于 **集成** 域的 **E2E** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

最小路径：注册/登录 → 上传 → 等状态 → chat stream。

## 推荐步骤（可勾选）

1. **身份**：完成注册/登录，确认 `Authorization: Bearer` 随请求发送（[认证](../patterns/auth-modes.md)）。  
2. **数据集**：选用已有 `dataset_id`，或先走 [数据集上线任务](../tasks/task-dataset-go-live.md)。  
3. **上传**：`POST /api/v1/documents/upload`（multipart），字段名以 Redoc 为准（[multipart](../patterns/multipart-upload.md)）。  
4. **等待**：轮询 `GET .../documents/{id}/status` 至完成或失败终态。  
5. **对话**：调用流式 chat 接口，确认代理 **未缓冲 SSE**（[SSE](../patterns/sse-streaming.md)）。

## 业务验收

- [ ] 同一会话内可 **稳定复现**：上传 → 完成 → 命中该文档的回答（或明确未命中原因）。  
- [ ] 失败路径有 **可解释错误**（4xx/5xx + 业务码），便于开单。

## 典型失败与影响

| 现象 | 用户体感 | 下一步 |
| --- | --- | --- |
| 长期 processing | 「传了没用」 | [解析止损](../tasks/task-parse-failure-triage.md) |
| 对话首字极慢 | 「AI 卡死」 | 查 SSE 缓冲与网关超时 |
| 401 中途出现 | 突然不能用 | Token 过期与刷新 |

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
