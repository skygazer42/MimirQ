---
sidebar_label: "排障"
sidebar_position: 6
---

# 数据集 — 排障

## 症状 → 优先排查

| 症状 | 排查 |
| --- | --- |
| `GET /datasets/` 始终为空 | 租户上下文、Token、数据集 ACL；用同一 Token 调 `GET /datasets/{id}` 对比 |
| `PATCH /datasets/{id}` 409 | 并发修改或业务冲突；看响应体 `detail`；必要时先 GET 再带版本字段重试（若 API 支持） |
| `DELETE` 失败 | 是否仍有文档或未完成的子资源绑定；先查 ingestion/文档列表 |
| 预检/画像接口 404 | `dataset_id` 是否属于当前租户；扫描 run id 是否过期 |
| 导入配置 422 | `config/import` 的 JSON 与 **DatasetConfigImportRequest** 是否一致 |

## 工具

- 浏览器：Network 面板保留失败请求的 **path、status、响应 JSON**。
- 后端：结构化日志中的 `request_id`、租户 ID。
- 集成清单：[FE_BE_DEBUG.md](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/FE_BE_DEBUG.md)

## 相关链接

- [OpenAPI / Redoc](https://skygazer42.github.io/MimirQ/)
- [API 契约说明](https://github.com/skygazer42/MimirQ/blob/main/docs/integration/API_CONTRACT.md)
