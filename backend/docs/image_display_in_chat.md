# RAG 对话中的图片显示

## 概述

当文档解析（MarkItDown/MinerU/DeepDoc）提取图片并上传到 MinIO 后，这些图片会与文本块关联。在 RAG 对话中，如果检索到包含图片的文本块，图片信息会随 citation 一起返回，前端可以显示这些图片。

## 后端实现

### 1. 图片绑定到 Chunk

在文档处理过程中：
- 解析器提取图片（base64 或 ZIP 中的图片文件）
- 上传到 MinIO，生成 `img_id = "{tenant_id}:{dataset_id}:{document_id}:{chunk_index}"`
- `img_id` 存储在 chunk metadata 中
- 图片信息随 chunk metadata 一起存入数据库，并在检索 citations 中返回

### 2. RAG 检索返回图片信息

在 `rag_engine.py` 和 `rag_graph.py` 中，构建 citations 时会检查 chunk metadata 的 `img_id`：

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

## 前端集成

### 1. 接收 Citations

流式对话响应中的 citations 事件：

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
    },
    {
      "chunk_id": "...",
      "document_id": "...",
      "chunk_content": "这是纯文本块...",
      "has_image": false
    }
  ]
}
```

### 2. 显示图片

**方式 1：直接嵌入 img 标签**

```tsx
{citation.has_image && citation.img_url && (
  <div className="citation-image">
    <img 
      src={citation.img_url} 
      alt="Referenced image"
      loading="lazy"
      onError={(e) => {
        e.currentTarget.src = '/placeholder-image.png';
      }}
    />
  </div>
)}
```

**方式 2：点击查看大图**

```tsx
{citation.has_image && (
  <button onClick={() => openImageModal(citation.img_url)}>
    <ImageIcon /> 查看图片
  </button>
)}
```

**方式 3：缩略图 + 预览**

```tsx
{citation.has_image && (
  <div 
    className="citation-thumbnail"
    onClick={() => setPreviewImage(citation.img_url)}
  >
    <img src={citation.img_url} alt="thumbnail" />
  </div>
)}
```

### 3. Markdown 渲染

如果 chunk_content 或 LLM 回答中包含 Markdown 图片语法：

```markdown
![产品架构图](/api/v1/documents/image-url/dataset123-doc456-img0)
```

使用 `react-markdown` 渲染时会自动显示图片：

```tsx
import ReactMarkdown from 'react-markdown';

<ReactMarkdown>{response}</ReactMarkdown>
```

### 4. 图片懒加载

对于包含多个图片的回答，使用懒加载优化性能：

```tsx
<img 
  src={citation.img_url}
  loading="lazy"
  decoding="async"
/>
```

## 示例场景

### 场景 1：用户上传包含图表的 PDF

1. 用户上传产品手册 PDF（包含架构图）
2. MinerU 解析，提取图片并上传到 MinIO
3. 文本块 "产品架构说明" 绑定 `img_id`
4. 用户提问："产品架构是什么？"
5. RAG 检索到该文本块
6. 前端收到 citation，包含 `has_image: true` 和 `img_url`
7. 前端在引用卡片中显示架构图

### 场景 2：用户上传 Word 文档

1. 用户上传包含嵌入图片的 Word 文档
2. MarkItDown 转换为 Markdown，提取图片
3. 图片上传到 MinIO，Markdown 中引用替换为 MinIO URL
4. 用户提问相关内容
5. LLM 回答中可能包含图片链接（Markdown 格式）
6. 前端用 ReactMarkdown 渲染，自动显示图片

### 场景 3：用户上传 ZIP（Markdown + images）

1. 用户通过 `/pipeline/upload-zip-with-images` 上传 ZIP
2. 所有图片自动上传到 MinIO
3. Markdown 引用替换为 MinIO URL
4. 对话时，相关图片随 citations 返回

## API 端点

### 获取图片（302 重定向）

```
GET /api/v1/documents/image-url/{img_id}
```

返回：302 重定向到 MinIO 预签名 URL（有效期 7 天）

**示例：**

```bash
curl -L http://localhost:8000/api/v1/documents/image-url/dataset123-doc456-img0
```

### 向后兼容（本地存储）

如果 MinIO 未启用，旧的图片路径仍然有效：

```
GET /api/v1/documents/image/{image_id}
```

## 前端显示建议

### 1. Citations 卡片

```tsx
<div className="citation-card">
  <div className="citation-header">
    <span>{citation.document_name}</span>
    {citation.has_image && <ImageBadge />}
  </div>
  
  <div className="citation-content">
    {citation.chunk_content}
  </div>
  
  {citation.has_image && (
    <div className="citation-image">
      <img src={citation.img_url} alt="引用图片" />
    </div>
  )}
</div>
```

### 2. 回答中的图片

如果 LLM 在回答中引用了图片链接，使用 Markdown 渲染器自动显示：

```tsx
import ReactMarkdown from 'react-markdown';

<ReactMarkdown
  components={{
    img: ({src, alt}) => (
      <img 
        src={src}
        alt={alt}
        className="response-image"
        loading="lazy"
      />
    )
  }}
>
  {assistantResponse}
</ReactMarkdown>
```

### 3. 图片预览模态框

```tsx
const [previewImage, setPreviewImage] = useState<string | null>(null);

<Dialog open={!!previewImage} onOpenChange={() => setPreviewImage(null)}>
  <DialogContent>
    <img src={previewImage} alt="预览" style={{maxWidth: '100%'}} />
  </DialogContent>
</Dialog>
```

## 性能优化

### 1. 缓存预签名 URL

MinIO 预签名 URL 有效期 7 天，可在前端缓存：

```typescript
const imageCache = new Map<string, string>();

async function getCachedImageUrl(imgUrl: string): Promise<string> {
  if (imageCache.has(imgUrl)) {
    return imageCache.get(imgUrl)!;
  }
  
  const response = await fetch(imgUrl);
  const actualUrl = response.url; // 302 后的真实 URL
  imageCache.set(imgUrl, actualUrl);
  return actualUrl;
}
```

### 2. 图片懒加载

```tsx
import { useInView } from 'react-intersection-observer';

function CitationImage({ imgUrl }: { imgUrl: string }) {
  const { ref, inView } = useInView({
    triggerOnce: true,
    threshold: 0.1
  });
  
  return (
    <div ref={ref}>
      {inView && <img src={imgUrl} loading="lazy" />}
    </div>
  );
}
```

### 3. 响应式图片

```tsx
<img
  src={imgUrl}
  srcSet={`${imgUrl} 1x, ${imgUrl} 2x`}
  sizes="(max-width: 768px) 100vw, 50vw"
  alt="引用图片"
/>
```

## 故障处理

### 1. 图片加载失败

```tsx
<img
  src={citation.img_url}
  onError={(e) => {
    e.currentTarget.src = '/placeholder-error.png';
    e.currentTarget.alt = '图片加载失败';
  }}
/>
```

### 2. MinIO 不可用

如果 MinIO 未启用或不可用，`has_image` 为 `false`，图片字段为空，不影响文本回答。

### 3. 预签名 URL 过期

MinIO 预签名 URL 有效期 7 天。如果过期：
- 重新调用 `/api/v1/documents/image-url/{img_id}` 获取新 URL
- 或实现自动刷新机制

## 总结

- **后端**：自动提取图片、上传 MinIO、绑定到 chunk、在 citations 中返回
- **前端**：检查 `has_image` 标志，使用 `img_url` 显示图片
- **用户体验**：在对话中看到相关图片，增强理解

启用 `MINIO_ENABLED=true` 后，所有文档解析自动支持图片！














