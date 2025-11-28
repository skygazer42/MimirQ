# MimirQ - AI 知识库助手

基于 RAG (Retrieval-Augmented Generation) 的智能知识库问答系统。

## 功能特性

✨ **核心功能**

- 📁 **知识库管理**: 上传 PDF、Markdown、TXT 文档
- 🔍 **智能检索**: 基于向量相似度的语义检索
- 💬 **流式对话**: 实时打字机效果的 AI 回答
- 📚 **引用展示**: 自动标注答案来源和相关文档片段
- ⚡ **实时处理**: 后台异步处理文档，实时更新状态

🎨 **技术亮点**

- **前端**: Next.js 14 (App Router) + TypeScript + Tailwind CSS + Shadcn/ui
- **后端**: FastAPI + LangChain + Milvus + PostgreSQL
- **AI**: OpenAI GPT-4 + BGE 中文 Embedding 模型
- **向量库**: Milvus 2.3 (支持十亿级向量检索)
- **架构**: 前后端分离 + Docker 容器化部署

## 快速开始

### 1. 环境要求

- Docker & Docker Compose
- Node.js 20+ (本地开发)
- Python 3.11+ (本地开发)

### 2. 克隆项目

```bash
git clone https://github.com/your-repo/MimirQ.git
cd MimirQ
```

### 3. 配置环境变量

**后端配置** (`backend/.env`):

```bash
cp backend/.env.example backend/.env
```

编辑 `backend/.env`，配置 OpenAI 兼容接口:

```env
LLM_API_KEY=sk-your-api-key
LLM_API_BASE=https://api.openai.com/v1  # 可替换为自建/其他 OpenAI 兼容地址
LLM_MODEL=gpt-4-turbo-preview
EMBEDDING_PROVIDER=local  # local 或 openai_compatible
EMBEDDING_API_BASE=       # 与上面的 base_url 相同时可留空
EMBEDDING_API_KEY=        # 不填写则复用 LLM_API_KEY
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/mimirq
```

**前端配置** (`frontend/.env.local`):

```bash
cp frontend/.env.local.example frontend/.env.local
```

### 4. 启动服务 (Docker)

```bash
# 启动所有服务
docker-compose up -d

# 查看日志
docker-compose logs -f
```

服务地址：
- 🌐 前端: http://localhost:3000
- 🔌 后端 API: http://localhost:8000
- 📖 API 文档: http://localhost:8000/docs
- 💾 Milvus: http://localhost:19530
- 📊 Milvus UI: http://localhost:9091
- 🗄️ MinIO: http://localhost:9001

### 5. 本地开发

**后端开发**:

```bash
cd backend

# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt

# 启动服务
uvicorn app.main:app --reload
```

**前端开发**:

```bash
cd frontend

# 安装依赖
npm install

# 启动开发服务器
npm run dev
```

## 项目结构

```
MimirQ/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── api/v1/            # API 路由
│   │   ├── models/            # 数据库模型
│   │   ├── schemas/           # Pydantic Schema
│   │   ├── services/          # 核心服务
│   │   │   ├── parsers/       # 文档解析器
│   │   │   ├── vectorstore.py # 向量存储
│   │   │   ├── rag_engine.py  # RAG 引擎
│   │   │   └── document_processor.py
│   │   ├── config.py          # 配置管理
│   │   ├── database.py        # 数据库连接
│   │   └── main.py            # 应用入口
│   ├── requirements.txt
│   └── Dockerfile
│
├── frontend/                   # Next.js 前端
│   ├── app/                   # App Router
│   ├── components/            # React 组件
│   │   ├── sidebar.tsx        # 文档列表侧边栏
│   │   ├── chat-area.tsx      # 对话界面
│   │   └── ui/                # UI 基础组件
│   ├── hooks/                 # 自定义 Hooks
│   │   ├── use-chat.ts        # 对话逻辑
│   │   └── use-documents.ts   # 文档管理
│   ├── lib/                   # 工具函数
│   │   ├── api-client.ts      # API 客户端
│   │   └── utils.ts
│   ├── types/                 # TypeScript 类型
│   ├── package.json
│   └── Dockerfile
│
├── docker-compose.yml
└── README.md
```

## API 文档

### 文档管理 API

#### 上传文档
```http
POST /api/v1/documents/upload
Content-Type: multipart/form-data

file: <binary>
```

#### 获取文档列表
```http
GET /api/v1/documents/?skip=0&limit=20&status=all
```

#### 删除文档
```http
DELETE /api/v1/documents/{document_id}
```

### 对话 API

#### 流式对话
```http
POST /api/v1/chat/stream
Content-Type: application/json

{
  "message": "你的问题",
  "conversation_id": "uuid (可选)",
  "document_ids": ["uuid1", "uuid2"],
  "stream": true,
  "rag_config": {
    "top_k": 5,
    "score_threshold": 0.7
  }
}
```

完整 API 文档: http://localhost:8000/docs

## 核心技术说明

### 1. 文档处理流程

```mermaid
graph LR
    A[上传文档] --> B[解析 PDF/MD/TXT]
    B --> C[文本切片 LangChain]
    C --> D[生成 Embedding BGE]
    D --> E[存入 Milvus]
    E --> F[保存到 PostgreSQL]
```

**关键参数**:
- `CHUNK_SIZE`: 1000 字符
- `CHUNK_OVERLAP`: 200 字符
- `EMBEDDING_MODEL`: BAAI/bge-large-zh-v1.5

### 2. RAG 对话流程

```mermaid
graph LR
    A[用户提问] --> B[向量检索 Top-5]
    B --> C[组装 Prompt]
    C --> D[LLM 流式生成]
    D --> E[返回答案 + 引用]
```

**检索策略**:
- 相似度算法: Cosine Similarity
- Top-K: 5 个最相关片段
- 相似度阈值: 0.7

### 3. 流式响应实现

后端使用 FastAPI `StreamingResponse` + Server-Sent Events (SSE):

```python
async def event_stream():
    yield f"data: {json.dumps({'type': 'citations', 'data': [...]})}\n\n"
    yield f"data: {json.dumps({'type': 'token', 'data': {'content': '你'}})}\n\n"
    yield f"data: {json.dumps({'type': 'token', 'data': {'content': '好'}})}\n\n"
    yield f"data: {json.dumps({'type': 'done', 'data': {...}})}\n\n"
```

前端使用 `fetch` + `ReadableStream` 解析:

```typescript
const reader = response.body?.getReader()
while (true) {
  const { done, value } = await reader.read()
  if (done) break
  // 解析 SSE 数据...
}
```

## 优化建议

### 生产环境部署

1. **文档解析优化**:
   - 集成 **MinerU 2.5** 处理复杂 PDF（表格、公式、双栏）
   - 使用 **Unstructured** 库处理更多文档格式

2. **向量数据库扩展**:
   - ✅ **Milvus** 已集成（支持十亿级向量）
   - 分布式部署: Milvus Cluster 模式
   - GPU 加速: 使用 GPU_IVF_FLAT 索引

3. **认证系统**:
   - 集成 **NextAuth.js** 或 **Clerk**
   - 支持 Google / GitHub OAuth

4. **性能优化**:
   - Redis 缓存热门查询
   - Celery 异步任务队列
   - Nginx 反向代理 + 负载均衡

## 常见问题

**Q: 文档处理失败怎么办？**
A: 检查文档是否为扫描件或包含复杂表格，建议升级到 MinerU 解析器。

**Q: 向量库占用空间太大？**
A: 可以调整 `CHUNK_SIZE` 减少切片数量，或使用 Milvus 的 `IVF_SQ8` 压缩索引（节省 75% 内存）。

**Q: Milvus 相关问题？**
A: 查看详细文档: [MILVUS_GUIDE.md](backend/MILVUS_GUIDE.md)

**Q: 如何支持更多语言模型？**
A: 修改 `backend/app/services/rag_engine.py`，替换为 Anthropic Claude 或本地 Ollama 模型。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License

---

**技术栈版本**:
- Next.js: 14.1.0
- FastAPI: 0.109.0
- LangChain: 0.1.10
- Python: 3.11
- Node.js: 20
