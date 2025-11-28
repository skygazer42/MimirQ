# Milvus 向量数据库使用指南

## 🎯 为什么选择 Milvus？

相比 ChromaDB，Milvus 具有以下优势：

| 特性 | ChromaDB | Milvus |
|------|----------|--------|
| **性能** | 适合小规模 (<10万) | 支持**十亿级**向量 |
| **索引** | 基础索引 | 10+ 种高级索引算法 |
| **分布式** | ❌ | ✅ 支持分布式部署 |
| **企业级** | 基础功能 | 生产级特性（高可用、备份） |
| **社区** | 新兴项目 | **LF AI** 基金会顶级项目 |
| **GPU 加速** | ❌ | ✅ 支持 GPU 索引 |

---

## 📦 架构说明

Milvus 采用云原生架构，包含 3 个组件：

```
┌─────────────┐
│   Milvus    │  ← 向量数据库核心服务
└──────┬──────┘
       │
       ├──────▶ Etcd      (元数据存储)
       └──────▶ MinIO     (对象存储)
```

### 组件说明

1. **Milvus Standalone** (端口 19530)
   - 向量数据库核心服务
   - 提供 gRPC API 接口
   - 健康检查: http://localhost:9091/healthz

2. **Etcd** (端口 2379)
   - 存储集合 Schema、索引信息
   - 提供服务发现和元数据管理

3. **MinIO** (端口 9000/9001)
   - 对象存储，保存向量数据和日志
   - Web UI: http://localhost:9001
   - 默认账号: `minioadmin / minioadmin`

---

## 🚀 快速开始

### 1. 启动服务

```bash
docker-compose up -d
```

等待 Milvus 启动完成（约 1-2 分钟）：

```bash
# 查看 Milvus 状态
docker-compose logs -f milvus

# 健康检查
curl http://localhost:9091/healthz
```

### 2. 验证连接

访问后端 API 健康检查：

```bash
curl http://localhost:8000/health
```

应返回：

```json
{
  "status": "healthy",
  "database": "connected",
  "milvus": {
    "status": "connected",
    "count": 0
  }
}
```

---

## 📊 Milvus Collection 设计

### Schema 定义

MimirQ 使用的 Collection Schema：

```python
fields = [
    FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
    FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=100),
    FieldSchema(name="chunk_index", dtype=DataType.INT64),
    FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
    FieldSchema(name="page_number", dtype=DataType.INT64),
    FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=500),
    FieldSchema(name="file_type", dtype=DataType.VARCHAR, max_length=20),
    FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=1024)  # BGE-large
]
```

### 索引配置

使用 **IVF_FLAT** 索引：

```python
index_params = {
    "metric_type": "COSINE",      # 余弦相似度
    "index_type": "IVF_FLAT",     # 倒排文件索引
    "params": {"nlist": 1024}     # 聚类中心数量
}
```

**性能说明**：
- `COSINE`: 适合归一化向量，范围 0-1
- `IVF_FLAT`: 平衡精度和速度
- `nlist=1024`: 适合 10万-100万 向量

---

## 🔧 高级配置

### 1. 切换索引类型

编辑 `backend/app/services/milvus_store.py`:

#### HNSW 索引（高精度，慢速）

```python
index_params = {
    "metric_type": "COSINE",
    "index_type": "HNSW",
    "params": {
        "M": 16,           # 每层连接数
        "efConstruction": 200
    }
}
```

#### IVF_SQ8 索引（压缩存储，节省内存）

```python
index_params = {
    "metric_type": "COSINE",
    "index_type": "IVF_SQ8",
    "params": {"nlist": 1024}
}
```

### 2. 调整搜索参数

```python
search_params = {
    "metric_type": "COSINE",
    "params": {
        "nprobe": 10    # 搜索的聚类数量（增大提高精度，降低速度）
    }
}
```

### 3. GPU 加速（可选）

如果有 NVIDIA GPU：

```python
index_params = {
    "metric_type": "COSINE",
    "index_type": "GPU_IVF_FLAT",  # GPU 加速索引
    "params": {"nlist": 1024}
}
```

---

## 📈 性能优化

### 1. 批量插入优化

当前实现已优化批量插入：

```python
# ✅ 好的做法：批量插入
milvus_store.add_documents(documents, document_id)

# ❌ 避免：单条插入
for doc in documents:
    milvus_store.add_documents([doc], document_id)
```

### 2. 搜索性能调优

| 参数 | 值 | 影响 |
|------|------|------|
| `nprobe` | 10 (默认) | 平衡精度和速度 |
| `nprobe` | 50 | 高精度，速度慢 50% |
| `nprobe` | 5 | 快速，精度下降 10% |

### 3. 内存优化

使用 `IVF_SQ8` 索引可节省 **75%** 内存：

```python
# 1024 维向量，100万条
# IVF_FLAT:  ~4GB
# IVF_SQ8:   ~1GB
```

---

## 🛠️ 运维管理

### 1. 查看 Collection 信息

```python
from pymilvus import connections, Collection

connections.connect(host="localhost", port="19530")
collection = Collection("documents")

print(f"总向量数: {collection.num_entities}")
print(f"索引信息: {collection.index().params}")
```

### 2. 备份与恢复

**备份 MinIO 数据**：

```bash
# 导出 MinIO 数据
docker cp milvus-minio:/minio_data ./milvus_backup

# 恢复
docker cp ./milvus_backup/. milvus-minio:/minio_data
```

### 3. 清空 Collection

```python
collection.drop()  # 删除整个 Collection
```

或通过 API：

```bash
# 删除所有文档（会级联删除向量）
curl -X DELETE http://localhost:8000/api/v1/documents/{document_id}
```

---

## 🔍 监控与调试

### 1. Milvus 健康检查

```bash
curl http://localhost:9091/healthz
```

### 2. 查看日志

```bash
# Milvus 日志
docker-compose logs -f milvus

# 全部服务日志
docker-compose logs -f
```

### 3. 性能指标

访问 Milvus Metrics：

```bash
curl http://localhost:9091/metrics
```

---

## 📚 常见问题

### Q1: Milvus 启动失败？

**检查端口占用**：

```bash
netstat -tulnp | grep 19530
```

**查看详细日志**：

```bash
docker-compose logs milvus
```

### Q2: 搜索结果不准确？

**解决方案**：

1. 降低 `score_threshold` (从 0.7 → 0.5)
2. 增加 `top_k` (从 5 → 10)
3. 增加 `nprobe` (从 10 → 20)

### Q3: 内存占用过高？

**优化策略**：

1. 使用 `IVF_SQ8` 压缩索引
2. 减小 `CHUNK_SIZE` (减少向量数量)
3. 定期清理无用文档

### Q4: 如何迁移 ChromaDB 数据到 Milvus？

**迁移脚本** (`scripts/migrate_chroma_to_milvus.py`):

```python
# TODO: 如需迁移，请联系技术支持
```

---

## 🎓 最佳实践

### 1. Collection 设计

- ✅ 单个 Collection 存储所有文档（使用 `document_id` 过滤）
- ❌ 为每个文档创建独立 Collection

### 2. 索引选择

| 数据量 | 推荐索引 | 说明 |
|--------|----------|------|
| < 100万 | IVF_FLAT | 最佳精度 |
| 100万 - 1000万 | IVF_SQ8 | 节省内存 |
| > 1000万 | HNSW | 高性能 |

### 3. 批量操作

- 批量插入: 每批 1000-5000 条
- 批量删除: 使用 `document_id in [...]` 表达式

---

## 🔗 参考资源

- [Milvus 官方文档](https://milvus.io/docs)
- [PyMilvus SDK](https://milvus.io/docs/install-pymilvus.md)
- [索引类型对比](https://milvus.io/docs/index.md)
- [性能调优指南](https://milvus.io/docs/performance_faq.md)

---

## 🆚 Milvus vs 其他向量数据库

| 特性 | Milvus | Qdrant | Pinecone | Weaviate |
|------|--------|--------|----------|----------|
| **开源** | ✅ | ✅ | ❌ | ✅ |
| **云原生** | ✅ | ✅ | ✅ | ✅ |
| **十亿级** | ✅ | ✅ | ✅ | ✅ |
| **GPU 加速** | ✅ | ❌ | ✅ | ❌ |
| **中文社区** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐ | ⭐⭐ |
| **免费部署** | ✅ | ✅ | 限额 | ✅ |

**推荐理由**：
- Milvus 是 **LF AI 基金会**顶级项目
- 国内**Zilliz**公司开发，中文文档完善
- 支持**最多的索引类型**（10+）
- 生产环境验证（Shopee、Walmart、NVIDIA）

---

**享受 Milvus 的强大性能！🚀**
