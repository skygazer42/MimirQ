---
sidebar_label: "设置 / Meta"
sidebar_position: 5
---

# 运行时配置

MimirQ 采用分层配置架构，支持环境变量、配置文件、数据库存储三级管理。部分配置支持运行时热更新，无需重启服务。

## 配置优先级

```mermaid
graph TD
    ENV["环境变量<br/>(最高优先级)"] --> FILE["配置文件<br/>(.env / config.yaml)"]
    FILE --> DB["数据库存储<br/>(Settings API)"]
    DB --> DEFAULT["代码默认值<br/>(最低优先级)"]
```

:::info
环境变量始终覆盖其他来源的同名配置。数据库存储的配置可通过 Settings API 动态修改，适用于不便重启的生产场景。
:::

## Settings API

### 获取当前配置

```bash
GET /api/v1/settings

# 响应示例
{
  "rag": {
    "top_k": 10,
    "rerank_enabled": true,
    "rerank_model": "bge-reranker-v2-m3"
  },
  "embedding": {
    "model": "BAAI/bge-m3",
    "batch_size": 64
  },
  "security": {
    "max_upload_size_mb": 100
  }
}
```

### 更新配置

```bash
PUT /api/v1/settings
Content-Type: application/json

{
  "rag.top_k": 15,
  "rag.rerank_enabled": false
}
```

:::warning
Settings API 修改立即生效，但仅影响通过数据库读取的配置项。由环境变量覆盖的配置无法通过 API 修改。
:::

## 环境变量总表

### 数据库 (PostgreSQL)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | — | PostgreSQL 连接字符串 |
| `DB_POOL_SIZE` | `10` | 连接池大小 |
| `DB_MAX_OVERFLOW` | `20` | 连接池最大溢出数 |
| `DB_POOL_TIMEOUT` | `30` | 获取连接超时（秒） |

### 向量数据库 (Milvus)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MILVUS_URI` | `localhost:19530` | Milvus gRPC 地址 |
| `MILVUS_TOKEN` | — | 认证 Token（可选） |
| `MILVUS_DATABASE` | `default` | 数据库名 |

### 缓存 (Redis)

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_URL` | `redis://localhost:6379/0` | Redis 连接字符串 |
| `REDIS_MAX_CONNECTIONS` | `20` | 最大连接数 |
| `CACHE_TTL` | `3600` | 默认缓存 TTL（秒） |

### LLM 服务

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `LLM_PROVIDER` | `openai` | LLM 提供商 |
| `OPENAI_API_KEY` | — | OpenAI API 密钥 |
| `OPENAI_BASE_URL` | — | 自定义 API 端点 |
| `LLM_MODEL` | `gpt-4o` | 默认模型 |
| `LLM_TEMPERATURE` | `0.1` | 生成温度 |
| `LLM_MAX_TOKENS` | `4096` | 最大输出 token |

### Embedding

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_MODEL` | `BAAI/bge-m3` | Embedding 模型 |
| `EMBEDDING_DEVICE` | `cpu` | 推理设备（`cpu` / `cuda`） |
| `EMBEDDING_BATCH_SIZE` | `64` | 批量推理大小 |

### 文档解析

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `PARSER_CHUNK_SIZE` | `512` | 分块大小（token） |
| `PARSER_CHUNK_OVERLAP` | `50` | 分块重叠（token） |
| `MAX_UPLOAD_SIZE_MB` | `100` | 文件上传大小限制 |

### 安全

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JWT_SECRET` | — | JWT 签名密钥（**必填**） |
| `JWT_ALGORITHM` | `HS256` | JWT 签名算法 |
| `JWT_EXPIRY_HOURS` | `24` | Token 有效期 |
| `CORS_ORIGINS` | `*` | 允许的 CORS 源 |

## 热更新 vs 需重启

| 类别 | 热更新 | 需重启 |
|------|--------|--------|
| RAG 参数（top_k, rerank 等） | Yes | — |
| LLM 模型 / Temperature | Yes | — |
| Embedding 模型 | — | Yes |
| 数据库连接池 | — | Yes |
| Redis / Milvus 连接 | — | Yes |
| JWT 密钥 | — | Yes |
| 日志级别 | Yes | — |

:::danger
修改 `JWT_SECRET` 后需重启服务，且所有已签发的 Token 将失效。建议在维护窗口操作。
:::

## 常用配置示例

```bash
# .env 文件示例（最小化生产配置）
DATABASE_URL=postgresql://mimirq:password@postgres:5432/mimirq
MILVUS_URI=milvus:19530
REDIS_URL=redis://redis:6379/0
JWT_SECRET=your-secure-random-secret-key
LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
EMBEDDING_MODEL=BAAI/bge-m3
LOG_LEVEL=INFO
```

---

**相关链接**

- [部署指南](./deployment.md) — 环境变量在各部署方式中的配置方法
- [可观测性](./observability.md) — 日志级别与追踪相关配置
- [健康探针](./health-probes.md) — 依赖服务连接配置验证
