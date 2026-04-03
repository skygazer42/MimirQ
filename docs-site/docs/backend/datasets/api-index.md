---
sidebar_label: "API 参考索引"
sidebar_position: 2
---

# 数据集 API 参考索引

所有数据集 API 挂载在 `/api/v1/datasets` 路由下。请求需携带 `X-Tenant-ID` 和认证 Header。

## 路径总览

### CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/datasets/` | 创建数据集 |
| `GET` | `/datasets/` | 分页查询列表 |
| `GET` | `/datasets/{dataset_id}` | 获取详情 |
| `PATCH` | `/datasets/{dataset_id}` | 更新名称/描述/权限/配置 |
| `DELETE` | `/datasets/{dataset_id}` | 删除（级联删除文档） |
| `POST` | `/datasets/{dataset_id}/clone` | 克隆配置到新数据集 |
| `POST` | `/datasets/{dataset_id}/purge` | 清除所有文档保留壳 |

### 配置导入导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{dataset_id}/config/export` | 导出完整配置 JSON |
| `POST` | `/{dataset_id}/config/import` | 导入 pipeline/retention/ingestion 配置 |

### 分类管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{dataset_id}/categories` | 获取数据集所属分类 |
| `PUT` | `/{dataset_id}/categories` | 设置分类（覆盖） |

### Ingestion Policy

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{dataset_id}/ingestion-policy` | 获取当前策略（含审计） |
| `PUT` | `/{dataset_id}/ingestion-policy` | 更新策略 |
| `GET` | `/{dataset_id}/ingestion-policy/versions` | 版本历史 |
| `POST` | `/{dataset_id}/ingestion-policy/rollback` | 回滚到指定版本 |
| `POST` | `/{dataset_id}/ingestion-policy/import` | 从 JSON 导入策略 |
| `GET` | `/{dataset_id}/ingestion-policy/export` | 导出策略 JSON |

### 画像与健康度

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{dataset_id}/health` | 健康度仪表盘 |
| `GET` | `/{dataset_id}/profile/summary` | 实时画像摘要 |
| `GET` | `/{dataset_id}/profile/findings/{key}` | 画像发现明细 |
| `GET` | `/{dataset_id}/profile/buckets/documents` | 按桶分组文档 |
| `POST` | `/{dataset_id}/profile/scan-runs` | 发起深度扫描 |
| `GET` | `/{dataset_id}/profile/scan-runs` | 扫描历史列表 |
| `GET` | `/{dataset_id}/profile/scan-runs/{id}` | 单次扫描详情 |
| `GET` | `/{dataset_id}/profile/export` | 导出画像 JSON |
| `GET` | `/{dataset_id}/profile/export-html` | 导出画像 HTML 报告 |

### 统计与导出

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{dataset_id}/ingestion/stats` | 入库统计 |
| `GET` | `/{dataset_id}/documents/export` | 导出文档列表 |
| `GET` | `/{dataset_id}/export` | 导出整个数据集（含文件） |

## curl 示例

### 创建数据集

```bash
curl -X POST http://localhost:8000/api/v1/datasets/ \
  -H "Content-Type: application/json" \
  -H "X-Tenant-ID: $TENANT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "产品文档库",
    "description": "存放产品手册与FAQ",
    "permission": "all_team_members"
  }'
```

### 查询列表（带分类过滤）

```bash
curl "http://localhost:8000/api/v1/datasets/?page=1&page_size=20&category_id=$CAT_ID" \
  -H "X-Tenant-ID: $TENANT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

:::tip 响应分页
列表接口返回 `DatasetListResponse`，包含 `items`（数据集数组）和 `total`（总数），支持 `page`、`page_size`、`category_id`（含 `include_descendants`）等参数。
:::

## 通用错误码

| 状态码 | 场景 |
|--------|------|
| 400 | 参数校验失败、名称不合法 |
| 403 | 无数据集访问权限 |
| 404 | 数据集不存在或已删除 |
| 409 | 名称冲突（租户内唯一） |
| 416 | Range 不满足（导出场景） |

## 相关链接

- [Schema 详解](./schemas.md)
- [权限与安全](./permissions.md)
- [Redoc API 文档](https://skygazer42.github.io/MimirQ/)
