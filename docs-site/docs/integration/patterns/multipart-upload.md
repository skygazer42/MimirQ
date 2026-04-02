---
sidebar_label: "上传"
sidebar_position: 5
---

# 上传：multipart 与预签名

## 概述

本页属于 **集成** 域的 **联调模式** 视角。权威契约以 OpenAPI（Redoc）为准；前端路由以 `web/app/**/page.tsx` 为准。

## 何时查阅

对接 `documents/upload`、批量/预签名路径或调试 **415/400** 时；对应 [文档入库任务](../tasks/task-ingest-documents.md)。

## 业务影响与验收要点

- 运营知悉 **单文件大小与 MIME 白名单**，避免「能选不能传」。  
- 批量任务有 **batch_id** 与失败清单，可二次投递。

## 典型失败与对策

| 症状 | 业务影响 | 优先动作 |
| --- | --- | --- |
| 415 Unsupported Media | 内容进不来 | 查 Content-Type 与文件头 |
| 网关 413 | 大文件全失败 | 调 client_max_body_size / 走预签名 |

## multipart

- 文档上传常用 `multipart/form-data`；字段名须与 OpenAPI **documents** 一致（如 `file`）。
- 体积限制受反向代理与后端配置双重约束。

## 预签名 / 批量

- 若使用 `upload-url`、`batch-upload` 等路径，按 OpenAPI 顺序：申请 URL → 直传对象存储 → 回调/确认（见具体 operation）。

## 排障

- 415 / 400：MIME 与字段名；参见 [FE_BE_DEBUG](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)。

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- 仓库内：[API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md) · [前后端排障](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)
