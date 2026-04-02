---
sidebar_label: "SSE / 流式"
sidebar_position: 6
---

# SSE 与流式对话

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

实现对话流式、长连接、或「首字延迟」排障时；与 [上传后对话场景](../scenarios/s01-upload-chat.md) 联读。

## 业务影响与验收要点

- 用户切换路由或取消发送时 **释放连接**，避免幽灵流式占用。  
- 代理层 **禁用缓冲**，否则表现为「半天不出字」。

## 典型失败与对策

| 症状 | 业务影响 | 优先动作 |
| --- | --- | --- |
| 长时间无 chunk | 以为卡死 | 查 nginx buffering；对比 curl |
| 断线后重复整段 | 体验乱 | 产品定义重连策略；服务端事件 id |

## 约定

- 流式对话多为 **SSE**（`text/event-stream`）；浏览器用 `EventSource` 或 fetch 流式读取。
- 代理层需 **禁用缓冲**（如 nginx `proxy_buffering off`），否则客户端迟迟收不到分片。

## 客户端

- 实现 **AbortController** 或等价取消，避免页面切换后仍占用连接。
- 断线重连：记录 last event id（若服务端支持）或幂等地新建会话（产品策略为准）。

## 相关

- 仓库 `docs/API.md` 拆分文中「SSE」章节；OpenAPI **chat** 分组。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
