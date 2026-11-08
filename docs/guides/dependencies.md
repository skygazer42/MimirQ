# Ragvia 依赖与安装配置

API 使用 Milvus 客户端和模型服务接口。本地 Torch、sentence-transformers、HanLP、GLiNER、CLIP、SPLADE、HF ColBERT 推理以及 FAISS、Chroma 后端已退出。

基础环境仍包含现有文档处理、ONNX OCR、评测和监控依赖。模型权重和 GPU 运行环境由独立模型服务管理，服务可以部署在本机或内网。普通解析、jieba、图片上传、预览、OCR 与模型看图对话继续保留；知识库 BM25 由 Milvus 原生全文索引提供。

## 安装配置

| 文件                      | 安装内容                                    | 使用场景                                            |
| ------------------------- | ------------------------------------------- | --------------------------------------------------- |
| `requirements.txt`        | 默认后端依赖、Milvus 客户端、常规解析 | API 与远程 Embedding/Rerank                         |
| `requirements-dev.txt`    | 基础环境和 pytest、Ruff、pip-audit 等工具   | 日常开发、静态检查与 CI 后端回归；不用于运行镜像      |

开发与 CI 统一安装 `requirements-dev.txt`，该文件引用 `requirements.txt`。运行镜像只安装基础文件。依赖版本沿用项目原有固定版本。

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

Ollama 原生向量服务使用 `provider=ollama`，当前客户端需要完整的 `/api/embed` 地址，例如 `http://localhost:11434/api/embed`。设置页保留独立服务入口，保存时不会将其转换为 OpenAI 协议。

## 旧本地配置迁移

XGBoost、unstructured 和腾讯云 SDK 的默认依赖已删除。相关本地 LTR 训练/排序、模型注册/发布、LTR 证据导出和 TCADP 解析器一并退出；DeepDoc PDF 不再加载段落合并预测模型，采用已有规则合并流程。普通证据、反馈和独立 HTTP 解析服务继续保留。

`unstructured` 未发现本地业务调用，因此移除安装声明；独立 ETL4LLM/Bisheng 服务通过 HTTP 调用，不使用该 pip 包。已有 `ltr` / `xgboost_ltr` / `tcadp` 配置需显式修正，安装旧包不能恢复已删除实现。现有环境包和用户模型文件不会自动清理。

`requirements-local-models.txt` 已删除，API 与 CI 不再提供 Torch wheel 安装步骤。安装旧模型包不会恢复已退出的实现。

| 旧选择                                                 | 处理方式                                                               |
| ------------------------------------------------------ | ---------------------------------------------------------------------- |
| `EMBEDDING_PROVIDER=local` 或数据集的 `provider=local` | 在独立服务部署原模型，显式改为受支持的 Embedding API 配置              |
| `cross_encoder`、`local_bge_v2_m3` 及其别名            | 配置 Rerank API，或显式选择现有轻量重排/关闭重排                       |
| `hanlp`                                                | 选择 jieba、jieba_textrank 或 simple；auto 固定使用 jieba              |
| `splade`、ColBERT `hf`、`sparse_splade` 配置           | 已退出，不能自动改成测试用的确定性向量                                 |
| KG 的 `gliner`、`hybrid`                               | 显式选择 llm 或 heuristic；自动标注保留 CPU、LLM API 和合规规则        |
| `IMAGE_EMBEDDING_ENABLED=true`、非空 `query_image`     | 已退出；图片向量索引/搜索旧接口返回 HTTP 410，query_image 返回校验错误 |

旧设置仍可读取以供修正，提交或执行已退出的选择会明确失败。若旧环境变量配置了本地模型或启用 CLIP/GLiNER，需要先修改部署配置才能启动。不会自动修改已保存的模型、删除向量集合或迁移索引。

要求启用重排的检索预设需要显式配置受支持的重排服务或轻量重排器；不再隐式选择旧 CrossEncoder，也不会代为启用另一个模型 API。

即使服务使用相同模型名称和维度，provider 与向量空间标识仍会变化；请单独验证模型输出、归一化方式和索引迁移/重建，不直接把旧 local 索引视为服务模型索引。模型 API 的连接测试只验证服务可用性。

## 已退出的本地向量后端

`requirements-chroma.txt`、Chroma 适配器及其元数据编码、持久化路径与安装入口已删除。旧 `VECTOR_BACKEND=chroma` 或地域映射会明确失败，不自动选择另一个索引空间。请在旧版本导出数据，再显式迁移或重建到受支持的后端。现有目录、Docker 卷和环境包不会自动删除或卸载。

生产默认使用 Milvus；memory 仅提供进程内测试/开发索引，不能替代 API/Worker 的共享持久化存储。Qdrant、pgvector 保留现有实现及其依赖要求。

`requirements-faiss.txt`、FAISS 向量存储和 ColBERT 的 FAISS 加速已删除。旧 `VECTOR_BACKEND=faiss` 或地域后端映射会明确失败，需要显式选择受支持的后端，并单独导出/重建旧索引。现有 FAISS 文件和环境包不会自动删除或卸载。ColBERT 确定性 scaffold 的余弦排序使用已有 NumPy，不再按安装环境选择加速实现。

`rank-bm25` 已移除：知识库 BM25 使用 Milvus 内置 function 和全文索引，聊天记忆在 PostgreSQL 的最近有界会话消息上进行关键词排序。API 不再构建本地 BM25 或缓存整份语料。原生 BM25 需要 Milvus，不能通过安装 rank-bm25 恢复本地实现。jieba 继续服务轻量关键词、查询处理和聊天记忆。

已有文档需要先预览并显式执行[Milvus BM25 回填](./milvus_bm25.md)，不重新计算 Embedding 或自动修改原有语义向量集合。

## Docker 与 Compose

主 Dockerfile 默认安装 `requirements.txt`，不预下载 Torch：

```bash
docker build -f docker/Dockerfile -t ragvia-api .
```

Compose 的 `BACKEND_REQUIREMENTS_FILE` 映射到该构建参数。主 Compose、lite 与 retrieval-dev 都默认使用 `requirements.txt` 和共享 Milvus。后两者复用主 Compose 的 Milvus、Etcd 和内部 MinIO 服务；文档对象存储保持关闭，不代表 Milvus 无需内部对象存储。

配置变化后需要重新构建 API 和 Worker 镜像。lite 与 retrieval-dev 不再提供无 Milvus/MinIO 的本地向量部署；已有 Chroma 数据不会自动导入 Milvus。自定义镜像仍可通过构建参数显式选择自有依赖配置。

## 现有环境与验证边界

修改 requirements 不会自动卸载当前环境已经安装的包。建议在新的虚拟环境或重新构建的镜像中验证依赖和占用，保留原环境用于回退；不要把声明减少直接等同于已释放磁盘空间。

本地界面开发继续只运行前端、API 和必要的 PostgreSQL，不因本次删除启动模型、解析服务或完整容器栈。完整后端回归工具使用 `requirements-dev.txt`；依赖审计覆盖基础配置。

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
