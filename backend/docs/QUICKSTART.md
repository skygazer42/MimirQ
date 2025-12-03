# MimirQ 快速入门指南

## 🚀 5 分钟快速启动

### 1. 克隆项目
```bash
cd /data/temp34/MimirQ
```

### 2. 配置 OpenAI API Key

编辑 `backend/.env` 文件，填入你的 API Key：

```env
OPENAI_API_KEY=sk-your-openai-api-key-here
```

### 3. 启动服务

**Linux/Mac**:
```bash
./start.sh
```

**Windows**:
```bash
start.bat
```

### 4. 访问应用

打开浏览器访问: http://localhost:3000

---

## 📖 使用流程

### Step 1: 上传文档
1. 点击左侧 "上传文档" 按钮
2. 选择 PDF、Markdown 或 TXT 文件
3. 等待文档处理完成（进度条会实时显示）

### Step 2: 开始对话
1. 在右侧输入框输入问题
2. 按 Enter 发送（Shift + Enter 换行）
3. AI 会基于你上传的文档内容回答

### Step 3: 查看引用
- AI 回答下方会显示参考的文档片段
- 包含文件名、页码和相似度分数

---

## 🎯 功能示例

### 示例 1: 法律文档问答
```
上传: 《劳动合同法》PDF
提问: "试用期最长可以是多久？"
AI 回答: 基于《劳动合同法》第19条，试用期最长不得超过...
```

### 示例 2: 技术文档查询
```
上传: React 官方文档 Markdown
提问: "如何使用 useEffect Hook？"
AI 回答: 根据文档，useEffect 是一个用于处理副作用的 Hook...
```

### 示例 3: 公司内部知识库
```
上传: 公司规章制度.pdf、员工手册.pdf
提问: "年假申请流程是什么？"
AI 回答: 根据员工手册第3章...
```

---

## ⚙️ 高级配置

### 修改 RAG 参数

编辑 `backend/app/config.py`:

```python
# 文本切片大小
CHUNK_SIZE: int = 1000  # 增大可减少切片数量

# 检索相关片段数量
RETRIEVAL_TOP_K: int = 5  # 增加可获得更多上下文

# 相似度阈值
SIMILARITY_THRESHOLD: float = 0.7  # 提高可过滤低质量结果
```

### 切换 LLM 模型

编辑 `backend/app/config.py`:

```python
# 使用 GPT-3.5 (更便宜)
OPENAI_MODEL: str = "gpt-3.5-turbo"

# 使用 GPT-4 (更强大)
OPENAI_MODEL: str = "gpt-4-turbo-preview"
```

### 使用 Claude 替代 OpenAI

编辑 `backend/app/services/rag_engine.py`:

```python
from langchain_anthropic import ChatAnthropic

self.llm = ChatAnthropic(
    model="claude-3-sonnet-20240229",
    api_key=settings.ANTHROPIC_API_KEY,
    streaming=True
)
```

---

## 🐛 常见问题

### Q1: 文档上传后一直显示 "处理中"？

**原因**:
1. Embedding 模型首次加载较慢（需下载 1.5GB）
2. Milvus 初次启动需要创建 Collection

**解决**:
- 等待 2-5 分钟
- 查看后端日志: `docker-compose logs -f backend`
- 查看 Milvus 状态: `curl http://localhost:9091/healthz`

### Q2: AI 回答"没有找到相关资料"？

**原因**:
1. 文档还在处理中
2. 问题与文档内容不相关
3. 相似度阈值过高

**解决**:
- 确认文档状态为 "已完成"
- 降低 `SIMILARITY_THRESHOLD` 到 0.5
- 重新表述问题

### Q3: Docker 启动失败？

**检查**:
```bash
# 查看服务状态
docker-compose ps

# 查看错误日志
docker-compose logs

# 重启服务
docker-compose restart
```

### Q4: 前端无法连接后端？

**检查 CORS 配置**:

编辑 `backend/app/config.py`:
```python
CORS_ORIGINS: str = "http://localhost:3000,http://localhost:3001"
```

---

## 📊 性能优化

### 1. 生产环境部署

**使用 Gunicorn** (backend):
```bash
gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker
```

**Next.js 生产构建** (frontend):
```bash
npm run build
npm start
```

### 2. Milvus 性能优化

**使用 HNSW 索引（更高精度）**:

编辑 `backend/app/services/milvus_store.py`:

```python
index_params = {
    "metric_type": "COSINE",
    "index_type": "HNSW",
    "params": {"M": 16, "efConstruction": 200}
}
```

**详细指南**: [MILVUS_GUIDE.md](./MILVUS_GUIDE.md)

### 3. 文档解析升级

集成 MinerU 2.5:

```yaml
# docker-compose.yml
mineru:
  image: opendatalab/mineru:2.5
  ports:
    - "8080:8080"
```

---

## 📚 参考资源

- [FastAPI 文档](https://fastapi.tiangolo.com/)
- [LangChain 文档](https://python.langchain.com/)
- [Next.js 文档](https://nextjs.org/docs)
- [ChromaDB 文档](https://docs.trychroma.com/)

---

## 💡 技术支持

遇到问题？

1. 查看 [README.md](./README.md) 完整文档
2. 查看后端日志: `docker-compose logs -f backend`
3. 访问 API 文档: http://localhost:8000/docs
4. 提交 Issue: [GitHub Issues](https://github.com/your-repo/issues)

---

**Enjoy MimirQ! 🎉**
