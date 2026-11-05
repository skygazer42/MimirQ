# Ragvia 依赖与安装配置

默认 API 环境使用 Milvus 客户端和远程模型接口。主依赖不安装 Torch、torchvision、sentence-transformers、HanLP、Accelerate、Chroma 或 FAISS；需要这些功能时，显式选择对应的安装配置。

基础环境仍包含现有文档处理、ONNX OCR、评测和监控依赖。这里的拆分解决本地 Torch 推理与可替代向量后端的默认安装问题，不代表 API 已经只剩 Web 框架和数据库驱动。

## 安装配置

| 文件                            | 安装内容                                                                | 使用场景                                            |
| ------------------------------- | ----------------------------------------------------------------------- | --------------------------------------------------- |
| `requirements.txt`              | 默认后端依赖、Milvus 客户端、BM25、常规解析                             | API 与远程 Embedding/Rerank                         |
| `requirements-dev.txt`          | 基础环境和 pytest、Ruff、pip-audit 等工具                               | 日常开发、基础验证                                  |
| `requirements-local-models.txt` | 基础环境和 Torch、torchvision、sentence-transformers、Accelerate、HanLP | 进程内 Embedding、CrossEncoder、HanLP 关键词        |
| `requirements-chroma.txt`       | 基础环境和 Chroma、LangChain Chroma 适配器                              | 显式选择 Chroma 的本地知识库                        |
| `requirements-faiss.txt`        | 基础环境和 FAISS                                                        | FAISS 后端或 ColBERT ANN 加速；无官方 Windows wheel |
| `requirements-ci.txt`           | 开发工具和上述所有可选依赖                                              | 现有完整后端回归；不用于默认 API 镜像               |

所有可选配置都引用基础文件，可以独立安装。依赖版本沿用项目原有固定版本。

## 默认 API 与开发安装

在仓库根目录运行：

```bash
python -m pip install -r requirements.txt

# 需要测试、格式检查和依赖审计工具时：
python -m pip install -r requirements-dev.txt
```

默认安装不需要 PyTorch 专用下载源。`make install-host` 也安装基础后端依赖，再安装前端依赖。

Embedding 配置应与实际模型服务一致。例如调用提供 BGE-M3 的 OpenAI-compatible 服务：

```dotenv
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_MODEL=BAAI/bge-m3
```

同时按 `.env.example` 配置实际的 `EMBEDDING_API_BASE` 和 `EMBEDDING_API_KEY`。官方 OpenAI 服务应使用其提供的模型名，例如 `text-embedding-3-small`。Embedding 与 Rerank 服务可以部署在内网，API 调用方式不要求使用外部公有云。

## 本地模型按需安装

```bash
python -m pip install -r requirements-local-models.txt
```

安装后才能选择 `EMBEDDING_PROVIDER=local` 或本地 CrossEncoder/HanLP 功能。模型权重另行准备，首次模型加载仍可能下载权重；仅安装 Python 包不等于模型已经就绪。

Linux 配置明确固定 `torch==2.13.0+cpu`、`torchvision==0.28.0+cpu`，并提供官方 CPU 源，防止默认拉入 CUDA 运行库。需要 GPU 推理时，优先使用独立模型服务及其专用 CUDA 环境。HanLP、Accelerate 都依赖 Torch，因此随本地模型一起安装。

## Chroma 与 FAISS 按需安装

```bash
# VECTOR_BACKEND=chroma
python -m pip install -r requirements-chroma.txt

# VECTOR_BACKEND=faiss，仅适用于有对应 FAISS wheel 的平台
python -m pip install -r requirements-faiss.txt
```

项目生产默认仍为 Milvus。切换后端不会迁移已有向量索引；已有 Chroma/FAISS 数据应继续使用原后端，直到单独完成迁移。

`rank-bm25` 保留在基础环境：知识库混合检索和聊天记忆均通过 LangChain 的 BM25Retriever 使用它。它不需要 Torch 或模型权重；其进程内索引占用取决于实际文档数量。迁移到服务端 BM25 属于后续检索设计工作，不能用删除依赖替代。

## Docker 与 Compose

主 Dockerfile 默认安装 `requirements.txt`，不预下载 Torch。显式构建可选镜像时选择相应配置：

```bash
docker build -f docker/Dockerfile -t ragvia-api .
docker build -f docker/Dockerfile --build-arg REQUIREMENTS_FILE=requirements-chroma.txt -t ragvia-api-chroma .
```

Compose 的 `BACKEND_REQUIREMENTS_FILE` 映射到该构建参数。主 Compose 默认使用基础配置；已有 lite 和 retrieval-dev 环境默认使用 `requirements-chroma.txt`，与其既有 Chroma 后端保持一致。

如将 lite 环境显式改为 FAISS，在 `.env` 中同时配置：

```dotenv
BACKEND_REQUIREMENTS_FILE=requirements-faiss.txt
VECTOR_BACKEND_LITE=faiss
```

配置变化后需要重新构建 API 和 worker 镜像。组合多个可选能力时，可以安装多份 requirements；自定义镜像应提供引用所需配置的 requirements 文件，并通过构建参数显式选择。

## 现有环境与验证边界

修改 requirements 不会自动卸载当前环境已经安装的包。建议在新的虚拟环境或重新构建的镜像中验证依赖和占用，保留原环境用于回退；不要把声明减少直接等同于已释放磁盘空间。

本地界面开发继续只运行前端、API 和必要的 PostgreSQL，不因本次拆分启动模型、解析服务或完整容器栈。需要验证所有可选实现的 CI 使用 `requirements-ci.txt`；依赖审计覆盖基础与可选配置。

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
