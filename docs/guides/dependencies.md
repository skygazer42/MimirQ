# 依赖说明

MimirQ 支持两种 Embedding 模式，对应不同的依赖需求。

本仓库提供三组依赖文件：
- `requirements.txt`：统一依赖（包含 API 模式 / 本地 Embedding / 开发工具）

---

## 🌐 API 模式（推荐，默认）

**适用场景**：生产环境、需要快速部署

**优势**：
- ✅ 无需下载模型
- ✅ 安装快速（依赖包小）
- ✅ 无需 GPU
- ✅ 支持多种 API 服务（OpenAI、通义千问、DeepSeek 等）

**安装**：
```bash
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

**配置**：
```bash
# .env（OpenAI API 示例，不是仓库默认部署值）
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your-api-key
EMBEDDING_API_BASE=https://api.openai.com/v1
```

**说明**：如需启用更多可选能力（本地 Embedding / OCR / 高级解析等），参考下方条目安装额外依赖。

**对齐说明**：仓库随 `.env.example` 发布的默认 `EMBEDDING_MODEL` 是 `BAAI/bge-m3`，需要指向实际提供该模型的 OpenAI-compatible 服务；上面的官方 OpenAI 示例则使用 `text-embedding-3-small`。如果没有显式设置 `EMBEDDING_MODEL`，后端代码也以 `text-embedding-3-small` 作为回退值。生产和团队环境应以 `.env.example` / 部署配置为准，不要依赖进程内默认值。

---

## 💻 本地模式（可选）

**适用场景**：离线环境、高隐私需求、无 API 费用预算

**优势**：
- ✅ 完全离线运行
- ✅ 数据隐私
- ✅ 无 API 调用费用

**劣势**：
- ❌ 需下载模型（约 1.5GB）
- ❌ 需要较大内存（建议 8GB+）
- ❌ 首次启动较慢

**安装**：
```bash
pip install --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
```

**配置**：
```bash
# .env
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
```

**依赖大小**：约 2-3GB（包含 PyTorch）

---

## 📦 依赖对比

| 依赖包 | API 模式 | 本地模式 | 大小 | 用途 |
|-------|---------|---------|------|------|
| fastapi | ✅ | ✅ | ~50MB | Web 框架 |
| langchain | ✅ | ✅ | ~100MB | AI 应用框架 |
| pymilvus | ✅ | ✅ | ~20MB | 向量数据库 |
| **torch** | ❌ | ✅ | ~2GB | 深度学习框架 |
| **sentence-transformers** | ❌ | ✅ | ~100MB | 本地 Embedding |

---

## 🔄 切换模式

### 从本地模式切换到 API 模式

1. 修改 `.env`：
```bash
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=your-api-key
EMBEDDING_API_BASE=https://api.openai.com/v1
```

2. 重启服务即可（无需卸载依赖）

### 从 API 模式切换到本地模式

1. 修改 `.env`：
```bash
EMBEDDING_PROVIDER=local
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
```

2. 重启服务

---

## 💡 推荐配置

### 开发环境
```bash
# 推荐使用 API 模式，快速启动
EMBEDDING_PROVIDER=openai_compatible
```

### 生产环境
```bash
# 根据需求选择
# - 有 API 预算 → openai_compatible
# - 高隐私需求 → local
```

### 离线环境
```bash
# 必须使用本地模式
EMBEDDING_PROVIDER=local
```

---

## ❓ 常见问题

### Q1: 为什么要分离依赖？

**A**: 为了减少文件数量与部署复杂度，本仓库已合并为单一 `requirements.txt`。如需减小体积，可在自建镜像/环境中自行裁剪 `torch` 等重依赖。

### Q3: 本地模式支持 GPU 吗？

**A**: 支持！系统会自动检测 GPU：
- 有 CUDA GPU → 自动使用 GPU 加速
- 无 GPU → 自动使用 CPU

无需手动配置。

### Q4: 可以混用吗？

**A**: 不建议。请选择一种模式：
- 要么全部用 API（LLM + Embedding 都用 API）
- 要么全部用本地（需要更多配置）

---

## 📊 性能对比

| 指标 | API 模式 | 本地模式（CPU） | 本地模式（GPU） |
|------|---------|----------------|----------------|
| 启动时间 | ~3秒 | ~30秒 | ~10秒 |
| 内存占用 | ~500MB | ~2GB | ~3GB |
| Embedding 速度 | 中等（受网络影响） | 慢 | 快 |
| 成本 | API 费用 | 硬件成本 | 硬件成本 |

---

## 🔐 JWT 组同步（Enterprise，可选）

当 `AUTH_MODE=jwt` 时，可以选择从 **已验证的 JWT** 中读取 groups claim，并将其同步为：
- `tenant_groups`（租户组）
- `tenant_group_members`（组成员关系）

用途：支持 dataset/doc 的 group allowlist（`partial_members`）并与企业 IdP（OIDC）组声明对齐。

**默认关闭（安全）**。建议同时配置 `JWT_TENANT_CLAIM`，避免在无法验证 tenant 归属时进行跨租户写入。

配置示例：

```bash
AUTH_MODE=jwt
JWT_TENANT_CLAIM=tenant_id

JWT_GROUPS_SYNC_ENABLED=true
JWT_GROUPS_CLAIM=groups
JWT_GROUPS_MAX_GROUPS=200
JWT_GROUPS_SYNC_TTL_SEC=60
```

说明：
- best-effort：同步失败不会阻塞请求（不会影响鉴权结果）。
- 有节流：`JWT_GROUPS_SYNC_TTL_SEC` 用于降低写放大（单进程内 best-effort TTL）。
- 当前实现为 add-only（仅补齐缺失的组/成员，不做删除）。

---

## 🔗 相关文档

- [OIDC / JWT Groups Claim 同步（Enterprise）](./oidc_groups_claim.md)
- [OpenAI Embeddings API](https://platform.openai.com/docs/guides/embeddings)
- [通义千问 Embeddings](https://help.aliyun.com/zh/dashscope/developer-reference/text-embedding-api-details)
- [BGE Embedding Models](https://huggingface.co/BAAI/bge-large-zh-v1.5)
