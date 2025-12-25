# MimirQ Backend 快速参考

## 目录结构速查

```
parsing/     📄 文档解析 - 解析、评估、切块
storage/     💾 存储 - 向量库、对象存储、检索
rag/         🤖 RAG 引擎 - 检索生成、重排序
evaluation/  📊 评估 - RAGAS 评估
services/    🔧 业务服务 - 数据集、权限、日志
```

## 常用导入

### 文档解析

```python
# PDF 质量评估
from app.parsing.quality.scorer import score_pdf_quality
quality = score_pdf_quality(pdf_path, sample_pages=3, use_ocr_validation=True)

# 解析文档
from app.parsing.factory import parser_factory
documents, backend = parser_factory.parse(file_path, parser_backend="auto")

# 文本切块
from app.parsing.chunking.factory import chunker_factory
chunker = chunker_factory.get_chunker("langchain_recursive", chunk_size=1000)
chunks = chunker.split_documents(documents)

# 完整处理流程
from app.parsing.processors.document_processor import document_processor
await document_processor.process_document(file_path, doc_id, tenant_id)
```

### 存储操作

```python
# 向量存储
from app.storage.vector.router import get_vector_store
vector_store = get_vector_store()
vector_ids = vector_store.add_documents(docs, doc_id, tenant_id)

# MinIO 图片上传
from app.storage.object.minio import minio_service
img_id = minio_service.upload_image(image_data, tenant_id, dataset_id, document_id, chunk_key)
url = minio_service.get_image_url(img_id)

# 混合检索
from app.storage.search.hybrid_retriever import hybrid_retriever
docs = hybrid_retriever.retrieve(query, doc_ids, tenant_id, top_k=5, mode="hybrid")
```

### RAG 对话

```python
# RAG 引擎
from app.rag.engine import get_rag_engine
rag_engine = get_rag_engine()

async for event in rag_engine.stream_chat(
    question=query,
    history=history,
    document_ids=doc_ids,
    tenant_id=tenant_id
):
    if event["type"] == "citations":
        print(f"引用: {event['data']}")
    elif event["type"] == "token":
        print(event["data"]["content"], end="")

# LangGraph 编排（非流式）
from app.rag.graph import run_rag_graph
result = run_rag_graph(question, history, document_ids, tenant_id)
```

### 评估

```python
from app.evaluation.ragas import evaluate_rag_with_ragas

result = await evaluate_rag_with_ragas(
    questions=questions,
    answers=answers,
    contexts=contexts,
    ground_truths=ground_truths
)
```

## 配置关键路径

### parsing 模块配置

```python
# app.core.config.Settings

# 解析器
DEFAULT_PARSER_BACKEND = "auto"  # auto | basic | markitdown | mineru | deepdoc
MARKITDOWN_ENABLED = True
MINERU_ENABLED = False
DEEPDOC_ENABLED = False
RAPIDOCR_ENABLED = False  # PDF 质量 OCR 验证

# 切块
DEFAULT_CHUNK_STRATEGY = "langchain_recursive"
CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

# MinerU
MINERU_API_TOKEN = ""
MINERU_LOCAL_SERVER_URL = ""  # 本地服务（ZIP 模式）
MINERU_VL_SERVER = ""
```

### storage 模块配置

```python
# 向量数据库
VECTOR_BACKEND = "milvus"  # milvus | faiss | chroma
MILVUS_HOST = "localhost"
MILVUS_PORT = 19530

# MinIO 对象存储
MINIO_ENABLED = False
MINIO_ENDPOINT = "localhost:9000"
MINIO_ACCESS_KEY = "minioadmin"
MINIO_SECRET_KEY = "minioadmin"
MINIO_BUCKET_NAME = "mimirq"
```

### rag 模块配置

```python
# 检索
RETRIEVAL_TOP_K = 5
SIMILARITY_THRESHOLD = 0.7
RETRIEVAL_MMR_LAMBDA = 0.7

# 重排序
ENABLE_RERANKER = False
RERANKER_PROVIDER = "llm"
RERANKER_TOP_N = 20

# LLM
LLM_API_KEY = ""
LLM_API_BASE = "https://api.openai.com/v1"
LLM_MODEL = "gpt-4-turbo-preview"
```

## API 端点映射

### 文档解析 API

```
POST /api/v1/documents/upload              # 上传并处理文档
POST /api/v1/pipeline/parse-preview        # 解析预览（不入库）
POST /api/v1/pipeline/chunk-preview        # 切块预览
POST /api/v1/pipeline/upload-zip-with-images  # 上传 ZIP（Markdown + images）
```

### 对话 API

```
POST /api/v1/chat/stream                   # 流式对话
GET  /api/v1/chat/conversations            # 对话列表
```

### 图片 API

```
GET /api/v1/documents/image/{image_id}     # 本地图片（向后兼容）
GET /api/v1/documents/image-url/{img_id}   # MinIO 图片（302 重定向）
```

## 故障排查

### 导入错误

如果遇到 `ModuleNotFoundError`：

1. 检查新的导入路径（参考 `app/README.md`）
2. 确认文件已正确移动
3. 清理 Python 缓存：`find . -name "__pycache__" -exec rm -rf {} +`

### 功能异常

1. 检查配置是否正确（`.env` 文件）
2. 确认依赖已安装（`pip install -r requirements.txt`）
3. 查看日志输出

### LangGraph 版本问题

```bash
pip install --upgrade langgraph langchain langchain-core
```

## 开发工作流

### 添加新功能

1. **新解析器**：`parsing/parsers/my_parser.py`
2. **新向量库**：`storage/vector/my_db.py`
3. **新 RAG 策略**：`rag/my_strategy.py`
4. 在对应的 `__init__.py` 或 `factory.py` 中注册

### 运行后端

```bash
cd /data/temp34/MimirQ/backend
python -m app.main

# 或使用 uvicorn
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 测试

```bash
# 单元测试
pytest tests/

# 按模块测试
pytest tests/parsing/
pytest tests/storage/
pytest tests/rag/

# 代码覆盖率
pytest --cov=app --cov-report=html
```

## 迁移检查清单

- [x] 创建新目录结构
- [x] 移动所有文件（使用 git mv）
- [x] 更新导入路径（自动化脚本）
- [x] 创建模块接口（__init__.py）
- [x] 验证语法（py_compile）
- [x] 检查 linter（无错误）
- [x] 清理临时文件
- [x] 编写文档

## 重构完成 ✅

新的目录结构更清晰、更易维护，功能完全保持不变！

