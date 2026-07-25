# MinIO 对象存储集成

## 概述

MimirQ 支持将文档解析过程中提取的图片存储到 MinIO 对象存储中，以实现：

- 图片与文本块的关联管理（通过 `img_id`）
- 节省内存（图片上传后删除内存中的 base64 数据）
- 分布式存储和访问
- 预签名 URL 安全访问

## 配置

### 1. 环境变量

在 `.env` 文件中添加以下配置：

```bash
# MinIO 对象存储
MINIO_ENABLED=true
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET_NAME=mimirq
MINIO_USE_SSL=false
MINIO_DOCUMENTS_ENABLED=true
```

### 2. 启动 MinIO

推荐：使用项目自带 Docker Compose（已包含 `mimirq-minio` 服务）。

从仓库根目录运行：

```bash
# 生成本地 env（非破坏性；已存在则跳过）
make init

# 仅启动依赖（Postgres/Redis/Milvus/MinIO）
make infra-up

# 或：启动完整后端（API + worker + 依赖）
# make up

# MinIO 健康检查
curl -fsS http://localhost:9000/minio/health/live

# 后端 ready 里会包含 minio 状态（MINIO_ENABLED=true 时）
curl -fsS http://localhost:8000/api/v1/health/ready
```

如果你需要单独启动 MinIO（不用项目 compose），也可以直接运行：

```bash
docker run -d \
  --name mimirq-minio \
  -p 9000:9000 \
  -p 9001:9001 \
  -e "MINIO_ROOT_USER=minioadmin" \
  -e "MINIO_ROOT_PASSWORD=minioadmin" \
  minio/minio server /data --console-address ":9001"
```

### 3. 安装依赖

`minio` 客户端已固定在 `requirements.txt`（当前 `minio==7.2.20`），随后端依赖一起安装；如需单独安装：

```bash
pip install minio==7.2.20
```

## 工作流程

### 1. 文档解析

当文档被上传和解析时：

1. 解析器（DeepDoc/MinerU/MarkItDown）提取文本和图片
2. 图片以 base64 格式存储在 chunk metadata 中（字段：`image_base64`、`image`、`img_base64` 等）

### 2. 图片上传

在切块阶段：

1. 检测 chunk metadata 中的图片数据
2. 生成 `img_id = "{tenant_id}:{dataset_id}:{document_id}:{chunk_index}"`
3. 上传图片到 MinIO：`images/{tenant_id}/{dataset_id}/{document_id}/{chunk_index}.jpg`
4. 删除内存中的原始 base64 数据（节省资源）
5. 在 metadata 中保留 `img_id`

### 3. 图片访问

通过 API 获取图片：

```bash
# 获取预签名 URL（302 重定向）
GET /api/v1/documents/image-url/{img_id}

# 示例
GET /api/v1/documents/image-url/tenant123:dataset123:doc789:0
```

返回 MinIO 预签名 URL（有效期 7 天）。

### 4. 图片删除

删除文档时，自动删除关联的所有图片：

```python
# 自动处理
DELETE /api/v1/documents/{document_id}
```

## 历史文档回填（img_id）

如果你在已有数据集上 **后续开启** `MINIO_ENABLED=true`，历史 chunks 可能没有 `metadata.img_id`（也就无法在 citations/正文里展示图片）。

推荐做一次批量重处理（reprocess）来回填图片：

```bash
# 先确保 MinIO 已启用并可连接（/health/ready 里会包含 minio 状态）
curl -fsS http://localhost:8000/api/v1/health/ready

# Header 模式（本地默认）：用 X-User-ID/X-Tenant-ID
python scripts/backfill_minio_images.py \
  --base-url http://localhost:8000 \
  --auth-mode header \
  --tenant-id 00000000-0000-0000-0000-000000000000 \
  --user-id demo \
  --dataset-id <YOUR_DATASET_UUID> \
  --force

# 只看候选列表（不提交重处理）
python scripts/backfill_minio_images.py ... --dry-run
```

说明：
- 默认只重试“缺少 `documents.metadata.img_ids` 的文档”；如需全量重处理，加 `--all`。
- 可选加 `--require-image-count`：只重试 `document_analytics_raw.image_count > 0` 的文档（更保守）。

## 数据结构

### img_id 格式

```
{tenant_id}:{dataset_id}:{document_id}:{chunk_index}
```

示例：`00000000-0000-0000-0000-000000000000:00000000-0000-0000-0000-000000000001:00000000-0000-0000-0000-0000000000ab:12`

### MinIO 对象路径

```
images/{tenant_id}/{dataset_id}/{document_id}/{chunk_index}.jpg
```

示例：`images/00000000-0000-0000-0000-000000000000/00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-0000000000ab/12.jpg`

### Chunk Metadata

```json
{
  "img_id": "tenant123:dataset123:doc789:0",
  "document_id": "doc789",
  "chunk_index": 0,
  "parser_backend": "deepdoc",
  ...
}
```

**注意**：`image_base64` 等原始图片数据在上传后会被删除。

## 检索集成

图片的 `img_id` 会随 chunk metadata 一起保存（数据库 / BM25 索引），并在混合检索的 citations 中返回：

```python
{
    "content": "文本内容...",
    "metadata": {
        "img_id": "tenant123:dataset123:doc789:0",
        "document_id": "...",
        ...
    }
}
```

检索时可以通过 `img_id` 获取关联图片。

## 性能优化

### 1. 图片格式

- 默认统一转换为 JPEG 格式（节省存储、简化读取）
- 如需保留原格式，可扩展 `img_id` 携带扩展名或在 metadata 里记录 `img_ext`

### 2. 预签名 URL 缓存

- 当前有效期：7 天
- 可在前端缓存 URL 以减少请求

### 3. 批量删除

删除整个知识库的图片：

```python
from app.storage.object.minio import minio_service

minio_service.delete_dataset_images(tenant_id, dataset_id)
```

## 故障处理

### MinIO 未启用

如果 `MINIO_ENABLED=false`，图片处理会被跳过，不影响文档解析和切块流程。

### 上传失败

图片上传失败时：
- 记录警告日志
- 继续处理其他 chunks
- `img_id` 字段不会出现在 metadata 中

### 访问失败

图片访问失败时返回 404：

```json
{
  "detail": "图片不存在或获取失败: ..."
}
```

## 示例代码

### 手动上传图片

```python
from app.storage.object.minio import minio_service

# 上传
img_id = minio_service.upload_image(
    image_data=b"...",
    tenant_id="tenant123",
    dataset_id="dataset123",
    document_id="doc789",
    chunk_key="0",
    extension="jpg"
)

# 获取 URL
url = minio_service.get_image_url(img_id)

# 删除
minio_service.delete_image(img_id)
```

## 安全建议

1. **生产环境**：使用强密码替换默认的 `minioadmin`
2. **SSL/TLS**：启用 `MINIO_USE_SSL=true` 并配置证书
3. **访问控制**：配置 MinIO bucket 策略限制访问
4. **预签名 URL**：合理设置有效期（当前 7 天）
5. **图片访问鉴权**：生产环境建议使用 `AUTH_MODE=jwt`；`GET /api/v1/documents/image-url/{img_id}` 会校验租户/数据集/文档可读权限。前端 `<img>` 无法携带自定义 Header，本项目前端统一通过 `AuthImage` 组件（`web/components/auth-image.tsx`，经 `lib/image-auth-proxy` 以带凭证请求取回图片并转为对象 URL）加载此类受保护图片，不使用 URL query 传递凭证。

## 监控

查看 MinIO 存储状态：

```bash
# MinIO 控制台
http://localhost:9001

# 登录凭据
用户名：minioadmin
密码：minioadmin
```

后端侧也会输出一份 **轻量 JSONL 指标日志**（用于统计 put/presign/delete 失败率与延迟）：

- 路径：`MINIO_METRICS_LOG_PATH`（默认 `./logs/minio_metrics.jsonl`）
- 记录字段：`op/success/elapsed_ms/object/bucket/ts/error?`

快速汇总（最近 10 分钟）：

```bash
python scripts/minio_metrics_report.py --since-sec 600 --show-errors
```

对象数量/体积增长（可选，需要设置 `MINIO_ENDPOINT/MINIO_ACCESS_KEY/MINIO_SECRET_KEY/MINIO_BUCKET_NAME`）：

```bash
python scripts/minio_metrics_report.py --bucket-stats --prefix images/
```

## 迁移

### 从本地存储迁移到 MinIO

1. 启用 `MINIO_ENABLED=true`
2. 重新处理文档（新文档自动使用 MinIO）
3. 历史文档需手动迁移（可选）

### 禁用 MinIO

设置 `MINIO_ENABLED=false`，系统会回退到本地存储（向后兼容）。









