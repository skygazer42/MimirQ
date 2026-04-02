---
sidebar_label: "排障"
sidebar_position: 6
---

# 文档 — 排障

## 症状 → 优先排查

| 症状 | 排查 |
| --- | --- |
| 上传立即 400/415 | `multipart` 字段名、MIME、文件大小；反向代理 `client_max_body_size` |
| 长期 `processing` | 解析器后端、任务队列、对象存储可用性；看文档 `timeline` 或后端日志 |
| `parsed-content` 空或 404 | 流水线是否完成、权限、是否已清理 |
| 分块列表与检索不一致 | `chunks/reembed`、索引延迟；核对 `pipeline` / 版本激活接口 |
| 批量接口部分失败 | 响应体中的逐项错误；避免对非幂等 POST 无界重试 |

## 工具

- `GET .../status`、`GET .../timeline`、`GET .../health`（见 OpenAPI）。
- [FE_BE_DEBUG.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
