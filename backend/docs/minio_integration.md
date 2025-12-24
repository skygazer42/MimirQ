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
MINIO_BUCKET_NAME=mimirq-images
MINIO_USE_SSL=false
```

### 2. 启动 MinIO

使用 Docker Compose：

```yaml
services:
  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    ports:
      - "9000:9000"
      - "9001:9001"
    environment:
      MINIO_ROOT_USER: minioadmin
      MINIO_ROOT_PASSWORD: minioadmin
    volumes:
      - minio_data:/data
    networks:
      - mimirq-network

volumes:
  minio_data:
```

或直接运行：

```bash
docker run -d \
  --name minio \
  -p 9000:9000 \
  -p 9001:9001 \
  -e "MINIO_ROOT_USER=minioadmin" \
  -e "MINIO_ROOT_PASSWORD=minioadmin" \
  minio/minio server /data --console-address ":9001"
```

### 3. 安装依赖

```bash
pip install minio==7.2.10
```

## 工作流程

### 1. 文档解析

当文档被上传和解析时：

1. 解析器（DeepDoc/MinerU/MarkItDown）提取文本和图片
2. 图片以 base64 格式存储在 chunk metadata 中（字段：`image_base64`、`image`、`img_base64` 等）

### 2. 图片上传

在切块阶段：

1. 检测 chunk metadata 中的图片数据
2. 生成 `img_id = "{dataset_id}-{chunk_id}"`
3. 上传图片到 MinIO：`images/{dataset_id}/{chunk_id}.png`
4. 删除内存中的原始 base64 数据（节省资源）
5. 在 metadata 中保留 `img_id`

### 3. 图片访问

通过 API 获取图片：

```bash
# 获取预签名 URL（302 重定向）
GET /api/v1/documents/image-url/{img_id}

# 示例
GET /api/v1/documents/image-url/dataset123-chunk456
```

返回 MinIO 预签名 URL（有效期 7 天）。

### 4. 图片删除

删除文档时，自动删除关联的所有图片：

```python
# 自动处理
DELETE /api/v1/documents/{document_id}
```

## 数据结构

### img_id 格式

```
{dataset_id}-{chunk_id}
```

示例：`00000000-0000-0000-0000-000000000001-12345`

### MinIO 对象路径

```
images/{dataset_id}/{chunk_id}.png
```

示例：`images/00000000-0000-0000-0000-000000000001/12345.png`

### Chunk Metadata

```json
{
  "img_id": "dataset123-chunk456",
  "document_id": "doc789",
  "chunk_index": 0,
  "parser_backend": "deepdoc",
  ...
}
```

**注意**：`image_base64` 等原始图片数据在上传后会被删除。

## 向量数据库集成

图片的 `img_id` 会随 chunk metadata 一起存入向量数据库（Milvus）：

```python
{
    "content": "文本内容...",
    "metadata": {
        "img_id": "dataset123-chunk456",
        "document_id": "...",
        ...
    }
}
```

检索时可以通过 `img_id` 获取关联图片。

## 性能优化

### 1. 图片格式

- 默认使用 PNG 格式
- 可根据需要修改 `minio_service.upload_image()` 的 `extension` 参数

### 2. 预签名 URL 缓存

- 当前有效期：7 天
- 可在前端缓存 URL 以减少请求

### 3. 批量删除

删除整个知识库的图片：

```python
from app.services.minio_service import minio_service

minio_service.delete_dataset_images(dataset_id)
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
from app.services.minio_service import minio_service

# 上传
img_id = minio_service.upload_image(
    image_data=b"...",
    dataset_id="dataset123",
    chunk_id="chunk456",
    extension="png"
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

## 监控

查看 MinIO 存储状态：

```bash
# MinIO 控制台
http://localhost:9001

# 登录凭据
用户名：minioadmin
密码：minioadmin
```

## 迁移

### 从本地存储迁移到 MinIO

1. 启用 `MINIO_ENABLED=true`
2. 重新处理文档（新文档自动使用 MinIO）
3. 历史文档需手动迁移（可选）

### 禁用 MinIO

设置 `MINIO_ENABLED=false`，系统会回退到本地存储（向后兼容）。



