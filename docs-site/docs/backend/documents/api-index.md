---
sidebar_label: "API 参考索引"
sidebar_position: 2
---

# 文档 API 参考索引

所有文档 API 挂载在 `/api/v1/documents` 路由下（需在 query 或 body 中指定 `dataset_id`）。请求需携带 `X-Tenant-ID` 和认证 Header。

## 路径总览

### 上传与创建

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/upload` | 单文件上传（multipart） |
| `POST` | `/upload-url` | 从 URL 导入 |
| `POST` | `/upload-batch` | 批量上传 |
| `POST` | `/manual` | 手动创建文档（纯文本） |
| `POST` | `/batch-upload/apply-urls` | 批量 URL 导入 |
| `GET` | `/batch-upload/status/{batch_id}` | 批量任务状态 |

### 查询与详情

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/` | 文档列表（分页） |
| `GET` | `/{document_id}` | 文档详情 |
| `GET` | `/{document_id}/status` | 处理状态 |
| `GET` | `/{document_id}/health` | 文档健康卡片 |
| `GET` | `/{document_id}/timeline` | 处理时间线 |
| `GET` | `/{document_id}/parsed-content` | 解析后文本 |
| `GET` | `/{document_id}/download` | 下载原始文件 |
| `GET` | `/stats` | 文档统计 |
| `GET` | `/folders` | 文件夹树 |
| `GET` | `/duplicates` | 重复文档检测 |

### 版本管理

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{document_id}/versions` | 版本列表 |
| `GET` | `/{document_id}/versions/diff` | 版本差异对比 |
| `POST` | `/{document_id}/versions/{hash}/activate` | 激活指定版本 |
| `DELETE` | `/{document_id}/versions/{hash}` | 删除版本 |

### Chunk 操作

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/{document_id}/chunks` | chunk 列表 |
| `GET` | `/{document_id}/chunks/matches` | chunk 匹配搜索 |
| `GET` | `/{document_id}/chunks/{chunk_id}` | chunk 详情 |
| `POST` | `/{document_id}/chunks` | 手动创建 chunk |
| `PATCH` | `/{document_id}/chunks/{chunk_id}` | 更新 chunk |
| `DELETE` | `/{document_id}/chunks/{chunk_id}` | 删除 chunk |
| `POST` | `/{document_id}/chunks/{chunk_id}/disable` | 禁用 chunk |
| `POST` | `/{document_id}/chunks/{chunk_id}/enable` | 启用 chunk |
| `POST` | `/{document_id}/chunks/reembed` | 重新向量化 |

### 元数据与生命周期

| 方法 | 路径 | 说明 |
|------|------|------|
| `PATCH` | `/{document_id}/pipeline` | 更新 pipeline 配置 |
| `PATCH` | `/{document_id}/metadata` | 更新用户元数据 |
| `GET` | `/{document_id}/lifecycle-metadata` | 获取生命周期元数据 |
| `PATCH` | `/{document_id}/lifecycle-metadata` | 更新生命周期元数据 |
| `GET` | `/{document_id}/access` | 获取访问权限 |
| `PUT` | `/{document_id}/access` | 设置访问权限 |

### 批量操作

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/batch-delete` | 批量删除 |
| `POST` | `/batch/retry` | 批量重试失败文档 |
| `POST` | `/batch/reingest` | 批量重新入库 |
| `POST` | `/batch/disable` | 批量禁用 |
| `POST` | `/batch/enable` | 批量启用 |
| `POST` | `/batch/archive` | 批量归档 |
| `POST` | `/batch/unarchive` | 批量取消归档 |
| `POST` | `/batch/access` | 批量设置权限 |
| `POST` | `/batch/move` | 批量移动到其他数据集 |
| `POST` | `/batch/metadata` | 批量更新元数据 |

### 预览与 QA

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/preview` | 解析预览（不入库） |
| `POST` | `/chunk-preview` | 分块预览 |
| `POST` | `/chunk-preview/by-sha` | 基于缓存 SHA 的分块预览 |
| `POST` | `/{document_id}/qa/generate` | 自动生成 QA 对 |
| `POST` | `/{document_id}/cancel` | 取消处理 |
| `POST` | `/{document_id}/retry` | 重试处理 |

### 图片

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/image/{image_id}` | 获取文档图片 |
| `GET` | `/image-url/{img_id}` | 获取图片 URL |

## curl 示例

### 上传文档

```bash
curl -X POST http://localhost:8000/api/v1/documents/upload \
  -H "X-Tenant-ID: $TENANT_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@/path/to/document.pdf" \
  -F "dataset_id=$DATASET_ID"
```

### 查询文档状态

```bash
curl "http://localhost:8000/api/v1/documents/$DOC_ID/status" \
  -H "X-Tenant-ID: $TENANT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

:::tip 批量操作
批量接口接受 `document_ids` 数组，响应中包含每个文档的处理结果（成功/失败/跳过），方便前端逐项展示。
:::

## 通用错误码

| 状态码 | 场景 |
|--------|------|
| 400 | 参数错误、文件类型不支持 |
| 403 | 无数据集/文档访问权限 |
| 404 | 文档不存在 |
| 415 | 不支持的 MIME 类型 |

## 相关链接

- [Schema 详解](./schemas.md)
- [流水线阶段](./pipeline.md)
- [Redoc API 文档](https://skygazer42.github.io/MimirQ/)
