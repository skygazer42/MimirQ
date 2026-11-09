# Agent Note: 将本地模型与本地向量库改为显式安装

Status: implemented

## Problem

主 requirements 同时安装远程模型 API、本地模型推理和多个可替代向量后端。即使只使用 Milvus 与远程 Embedding，安装仍包含 Torch、torchvision、sentence-transformers、Chroma 和 FAISS。HanLP、Accelerate 还会间接引入 Torch；主 Dockerfile 与文档 CI 单独预装 Torch，因此只删五个直接声明不能改变实际安装结果。

用户在 2026-11-05 确认收窄主 API 依赖。现有 Chroma/FAISS 部署和本地模型调用仍有实际代码与回归入口，本次采用按需安装边界，不删除这些运行时实现。

## Decision

本地模型安装部分由[退出 API 内模型推理](../architecture/2026-11-05-retire-in-process-models.md)接管，`requirements-local-models.txt` 与对应实现已退出。本篇继续持有 Chroma/FAISS 的按需安装边界；下述本地模型安装验证属于首次拆分时的历史证据。

`requirements.txt` 保留 Milvus、远程模型调用、现有文档处理、BM25、鉴权和服务基础依赖。`requirements-dev.txt` 继续在基础安装上叠加开发工具。本地推理依赖进入 `requirements-local-models.txt`，Chroma 和 FAISS 分别进入 `requirements-chroma.txt`、`requirements-faiss.txt`。每份可选配置引用基础文件，保留既有版本；Linux 的本地 Torch/torchvision 明确选择 CPU wheel。

`requirements-ci.txt` 汇合开发与可选配置，仅供既有完整后端回归使用。主 Docker 构建默认安装基础配置，通过 `REQUIREMENTS_FILE` 选择显式配置；已有 lite/retrieval-dev Compose 选择 Chroma 配置以保持已有存储语义。文档 CI 使用基础配置，FAISS 专用回归显式安装对应配置。依赖审计覆盖所有受支持配置。

Docker CI 同时保留默认基础镜像与独立的 `mimirq-backend-chroma-ci` 镜像。五个复用镜像的检索、JWT 与清理入口统一选择后者，避免 `--no-build` 绕过 Compose 的安装配置。夜间 FAISS 评测显式叠加 FAISS 配置，其已有词法夹具不能替代该依赖声明。

`rank-bm25` 保留：知识库混合检索和聊天记忆均通过 LangChain BM25Retriever 使用它。本次不迁移索引、不更改默认向量后端或模型配置，也不卸载现有开发环境。

## Alternatives considered

- 保留单一完整依赖文件：安装和 CI 最直接，也能继续运行所有后端；但 API 部署必须承担未选功能的推理依赖，与本次目标冲突。
- 直接删除可选后端与本地推理实现：能减少长期维护范围；但现有 Compose 与调用链明确使用它们，删除涉及存储迁移与功能退出，超出本次已确认的安装边界。
- 仅删除用户点名的五个包：改动最少；但 HanLP、Accelerate 与独立 wheel 下载会重新安装 Torch，不能满足实际安装目标。

## Testing

- 基础配置使用 uv 完整解析：Linux/Python 3.11 为 234 个包，Windows/Python 3.12 为 232 个包；两份图均不包含 Torch、torchvision、sentence-transformers、Chroma、FAISS、HanLP、Accelerate、langchain-chroma 或 nvidia-*。完整 CI 配置也完成 Linux 解析；验证工具对多个受信任源采用与 pip 相同的候选匹配方式，不改变项目包管理器。
- 相关既有依赖、CI、可选导入、远程 Embedding、解析隔离和评测配置检查共 78 项通过。基础版本先复现主安装仍包含重依赖的失败，再验证拆分结果。独立复核发现的预构建镜像和夜间 FAISS 配置均先复现契约检查失败，再修正并通过验证。检查同时修正既有 Windows 路径分隔符断言，以及受前端格式化影响的 CI 字符串断言。
- Docker Compose 实际配置展开确认主 API/worker 使用基础配置，lite/retrieval-dev 使用 Chroma 配置。只展开配置，不启动容器或完整服务栈。
- 主 Dockerfile 和文档 CI 不再预装 Torch；本地模型 CPU 版本与既有校验 wheel 清单保持一致。安装文档记录每个配置的用途、BM25 的保留原因，以及现有环境不会自动卸载旧包。

## Consequences

FAISS 的安装配置、运行时后端和可选加速由[退出 FAISS](../simplification/2026-11-06-retire-faiss.md)接管并删除；本篇其余安装隔离决定及历史验证证据保留。

BM25 的依赖与索引所有权现由[Milvus 原生 BM25](../architecture/2026-11-05-milvus-native-bm25.md)接管；本篇关于可选向量后端和安装隔离的决定保持。

基础 API 安装不再承担本地 Torch 推理和未选择向量后端的安装成本；显式使用可选功能的环境需要选择对应配置。完整后端回归仍显式安装全部可选配置，以保持既有验证范围，其资源成本保留在该 CI 环境。本次未构建镜像、运行完整 Python 测试集或重装现有环境。

基础配置仍包含 ONNX、OpenCV、解析和评测依赖，本次不将其称为最小 API 环境。解析图验证不等于完整运行时或镜像构建验证。已有环境需要重新创建才能证明实际占用变化，不能通过删除声明推算节省空间。后续只有确定退出本地后端时，才重新讨论删除实现和数据迁移。

历史检索未找到持有同一安装分组决定的活跃 Agent Note；依赖指南中“统一安装”的旧说明由本次文档替换。并行代码风格计划的 Python 测试限制属于其既定重构范围，本次独立安装契约使用相关现有检查，不接管该计划的覆盖清单。
