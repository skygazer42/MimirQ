# RAG 对话中的图片显示

## 概述

当文档解析（MarkItDown/MinerU/DeepDoc 等）提取图片并上传到 MinIO 后，这些图片会与文本块关联。在 RAG 对话中，如果检索到包含图片的文本块，图片信息会随 citation 一起返回，前端展示这些图片。

## 图片展示策略（当前实现）

为避免"无关图片刷屏"，当前策略是 **只展示检索命中的 citations 里的图片**：

- **命中判定**：`citation.has_image=true` 才视为"可展示图片"。
  - `has_image` 的来源是 chunk 的 `metadata.img_id`（优先），或从 chunk 内容里反向提取 `/api/v1/documents/image-url/{img_id}`（兼容已替换 URL 的 Markdown/HTML）。
- **展示位置 1（引用卡片）**：引用卡片里显示缩略图（点击可打开原图/文档定位）。
- **展示位置 2（回答正文，可选）**：非结构化输出时，后端会把 citations 里的图片 URL 去重后追加到回答末尾（默认最多 3 张）。
  - 开关：`SHOW_IMAGE_IN_ANSWER=true/false`（默认 `true`）
  - 上限：`IMAGE_APPEND_MAX=3`

> 如果你需要"命中段落附近的图片也一起展示"，建议把它做成可选策略（例如基于 header_path/邻居 chunk 额外回查），默认仍保持 citations-only，以保证相关性与可控的响应体积。

## 后端实现

### 1. 图片绑定到 Chunk

在文档处理过程中：

- 解析器提取图片（base64 或 ZIP 中的图片文件）
- 上传到 MinIO，生成 `img_id = "{tenant_id}:{dataset_id}:{document_id}:{chunk_index}"`
- `img_id` 存储在 chunk metadata 中
- 图片信息随 chunk metadata 一起存入数据库，并在检索 citations 中返回

### 2. RAG 检索返回图片信息

在 `app/rag/engine.py` 与 `app/rag/graph.py` 中，构建 citations 时会检查 chunk metadata 的 `img_id`：

```python
# 提取图片信息（如果有）
img_id = meta.get("img_id")
if img_id:
    img_url = f"/api/v1/documents/image-url/{img_id}"
    citation["img_id"] = img_id
    citation["img_url"] = img_url
    citation["has_image"] = True
```

### 3. Citation Schema

Citation（`app/api/schemas/chat.py`）包含图片相关字段：

```python
class Citation(BaseModel):
    document_id: UUID
    document_name: str
    chunk_id: UUID
    chunk_content: str
    ...
    # 图片相关字段
    has_image: bool = False
    img_id: Optional[str] = None  # 例如："tenant123:dataset123:doc456:0"
    img_url: Optional[str] = None  # 例如："/api/v1/documents/image-url/tenant123:dataset123:doc456:0"
```

流式对话响应中的 citations 事件示例：

```json
{
  "type": "citations",
  "data": [
    {
      "chunk_id": "...",
      "document_id": "...",
      "chunk_content": "这是关于产品架构的说明...",
      "has_image": true,
      "img_id": "tenant123:dataset123:doc456:0",
      "img_url": "/api/v1/documents/image-url/tenant123:dataset123:doc456:0",
      "relevance_score": 0.95
    }
  ]
}
```

## API 端点

### 获取图片（鉴权字节流）

```
GET /api/v1/documents/image-url/{img_id}
```

端点会校验租户/数据集/文档可读权限，然后代理返回图片字节（200，Range 请求为 206）。响应统一使用 `Cache-Control: private, no-store`，支持 `ETag`；客户端显式发送匹配的 `If-None-Match` 时可返回 304（见 `app/api/v1/document_assets.py`）。

### 向后兼容（本地存储）

如果 MinIO 未启用，旧的图片路径仍然有效：

```
GET /api/v1/documents/image/{image_id}
```

### ZIP 上传（Markdown + images）

通过 `POST /api/v1/pipeline/upload-zip-with-images` 上传 ZIP 时，所有图片自动上传到 MinIO，Markdown 中的引用替换为图片 URL。

## 前端实现（当前）

图片端点需要认证，**裸 `<img src>` 无法携带凭证（会 401）**。前端统一使用 `AuthImage` 组件族（`web/components/auth-image.tsx`）：

- `AuthImage` / `AuthImageLink` / `useResolvedAuthAssetUrl`：经 `lib/image-auth-proxy` 判断是否需要鉴权代理（`needsAuthAssetProxy`），需要时以带凭证请求取回图片并转为对象 URL 后再渲染；加载失败时不渲染（返回 `null`）。
- **引用卡片缩略图**与 **Markdown 正文图片**走同一鉴权链路；Markdown 渲染（`markdown-renderer.tsx`）已将 `img` 节点交给 `AuthImage` 处理。
- 生产启用前端容器时应设置非空 `MARKDOWN_IMAGE_PROXY_SECRET`（见 `web/lib/markdown-image-proxy-token.ts` 与 `web/app/api/markdown-image` 路由），保证代理 URL 端到端不透明。

新增前端展示位时，直接复用 `AuthImage`，不要自行拼 `<img>` 或在 URL query 里传凭证。

## 示例场景

1. **包含图表的 PDF**：MinerU 解析提取架构图 → 上传 MinIO → 文本块绑定 `img_id` → 提问命中该块 → 引用卡片展示架构图。
2. **嵌入图片的 Word**：MarkItDown 转 Markdown 并提取图片 → Markdown 引用替换为图片 URL → 回答正文经 Markdown 渲染显示图片。
3. **ZIP（Markdown + images）**：`/pipeline/upload-zip-with-images` 上传 → 图片自动入 MinIO → 对话时相关图片随 citations 返回。

## 故障处理

- **图片加载失败**：`AuthImage` 拿不到有效对象 URL 时不渲染该图片，不影响文本内容展示。
- **MinIO 不可用**：图片端点返回 503；已有 citation 的文本内容仍可正常展示。
- **图片返回 404**：检查 `img_id` 对应的租户、数据集、文档和 MinIO 对象是否仍然存在。

## 总结

- **后端**：自动提取图片、上传 MinIO、绑定到 chunk、在 citations 中返回
- **前端**：检查 `has_image` 标志，统一用 `AuthImage` 加载受保护图片
- 启用 `MINIO_ENABLED=true` 后，文档解析自动支持图片；细节配置见 [minio_integration.md](./minio_integration.md)
