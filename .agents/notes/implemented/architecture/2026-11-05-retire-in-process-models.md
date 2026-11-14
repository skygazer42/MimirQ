# Agent Note: 退出 API 进程内的 Torch 模型推理

Status: implemented

## Problem

将 Torch、sentence-transformers、HanLP 等拆成可选安装后，API 仍维护本地模型加载、设备选择、权重下载、缓存和多套模型选择入口。用户确认进一步删除这些能力，并明确退出本地 CLIP 图片向量检索，同时保留图片上传、预览、OCR 与模型看图对话。

## Decision

Embedding 保留现有 OpenAI-compatible、DashScope、Ollama 服务客户端及测试专用确定性实现，删除 SentenceTransformerEmbedding 和 local 模型预设。本地 CrossEncoder、BGE 重排退出；远程 Rerank 与不加载神经模型的排序器保留。HanLP 退出，关键词的 auto 明确采用已有 jieba；不再按安装环境自动选择模型。

SPLADE 和 ColBERT 的 HF/Torch 实现退出，保留已有确定性测试实现和必要索引契约。旧的 local、cross_encoder、local_bge_v2_m3、hanlp、splade、hf 选择在输入或运行时选择边界明确失败，不能静默改为另一模型或测试算法。

调用链核对发现 GLiNER 也在 API 中加载神经模型，且自动标注的默认混合预设可能绕过 KG 开关触发它。因此 GLiNER 与基于它的 KG hybrid 分支一并退出；图谱保留 llm/heuristic，自动标注保留 CPU、LLM API、合规规则，默认显式选择 CPU。历史标注结果的 hybrid 策略名称仍可读取。

CLIP 编码器、图片向量索引与查询链退出；仍被图片引用、资源访问、上传和模型看图使用的代码按实际所有者保留。旧图片向量接口明确返回能力退出错误。既有向量数据不自动删除，不执行数据库或向量索引迁移。

删除 requirements-local-models.txt、主 CI 的 Torch wheel 安装与仅服务此安装的工具；保留 Chroma、FAISS 可选配置以及 rank-bm25、jieba、ONNX OCR、普通文档解析。清理解析中的 Torch 设备探测，OCR/表格原有 ONNX 路径保留。独立解析容器的专用推理环境不属于 API 进程。

前端删除已退出的模型和关键词选项，保留用户可修正旧配置的入口；不在读取旧数据时静默改模型。同步有效配置说明、安装文档、CI 和相关测试。生成类型由实际 schema 导出维护。

数据集与流水线的共享 DTO 保持历史读取能力，校验放在明确的创建/更新请求、流水线元数据写入、治理配置写入及最终合并后的执行/预览入口。`RetiredModelProviderError` 在现有 HTTP 错误层统一返回 422，不将只读解析变成错误或静默隐藏旧配置。

会话引用与模板输出同样保留历史来源值。模板创建、更新、启用和复制版本在修改记录前校验实际生效的补丁；旧模板可以显式停用或替换为受支持的配置。聊天与预览合并请求、数据集和模板后，在 Pydantic 包装错误之前校验最终选择，并向上传播能力退出错误，不能被原有元数据容错分支吞掉。请求中显式指定的受支持覆盖继续优先。已退出的 `sparse_splade` 预设与直接选择 SPLADE 使用相同的写入和执行规则。

普通检索命中的图片引用必须经过现有资源访问所有者校验，再交给视觉读取或生成：本地预览校验账户、文档绑定与租户，复合存储引用校验租户和所引用文档的 ACL。载体分块可读不代表所引用图片可读。缺少身份上下文时不选择图片，权限存储故障向上传播；仅对确认不可读或不存在的图片作 403/404 裁剪。通过校验的图片去重并遵守既有数量上限，不重复插入普通文档列表。

## Alternatives considered

- 继续按需安装：保留全部本地能力，部署选择灵活；但维护负担仍在，与用户进一步收窄产品的决定冲突。
- 在本批新增远程 CLIP/SPLADE/ColBERT 协议：可保留相关检索功能；项目没有已确认的服务协议，新增会扩大本次退出范围。用户选择退出 CLIP 向量检索。
- 连同所有本地算法和 OCR 一起删除：范围表面统一；但 BM25、jieba、ONNX OCR 与 Torch 推理不是同一能力，仍服务明确保留的文档和图片流程。

## Testing

- 退出行为先复现失败，再验证旧 Embedding、重排、HanLP、SPLADE、HF ColBERT、GLiNER 选择和启用旧开关的配置明确失败。数据集旧重排配置在原有容错解析之前拒绝，避免变为系统默认模型。
- 图片向量旧接口返回认证后的 HTTP 410，非空 query_image 被请求模型拒绝。真实流阶段检查普通检索中的图片证据可进入视觉读取，且不重复插入文档；本地图片在元数据归一化后仍由租户目录正确读取。
- 使用实际 app 导出 OpenAPI，并重新生成前端类型。前端验证涵盖旧模型保留显示、API 服务上的 BGE 不被误判本地、CPU/LLM/规则标注与既有图片代理/引用；类型检查覆盖所有 tracked 前端来源及其真实导入。
- 保留的 ONNX OCR 不再借用 Torch 探测设备。原环境没有 nltk，未安装完整解析依赖或执行该原生视觉初始化检查；未下载模型、启动服务、构建生产镜像或删除已有数据。
- 全仓已有失败与本批检查区分记录：原工作区的旧所有者引用、Windows 路径及文档资产测试失败，以及未跟踪草稿中的 UI 门禁问题，均在原树复现；本批不以恢复旧导出或放宽权限处理这些基线问题。
- 独立审查发现的历史会话、聊天/预览容错、模板继承激活、图片引用权限问题先以 19 项失败复现，再修复；补充受支持覆盖、模板停用/替换和缺少身份的对照检查后，模型退出与审查边界合计 62 项通过。具体范围和既有失败见[验证记录](../../../../docs/development/local-model-retirement-verification.md)。

## Consequences

本篇保留 FAISS 的决定由[退出 FAISS](../simplification/2026-11-06-retire-faiss.md)部分取代，其他本地模型退出边界保持。

关于进程内 BM25 与 rank-bm25 的保留决定，由[Milvus 原生 BM25](2026-11-05-milvus-native-bm25.md)部分取代。jieba、模型服务、ONNX OCR 和本篇的其他能力退出边界保持。

已有使用本地模型的知识库必须显式改用模型服务；模型、维度和向量空间不一致时需要独立重建索引。用户已确认功能退出，不能用自动更换模型掩盖迁移要求。确定性检索仍只代表既有测试能力，不作为神经检索替代宣传。

本决定部分取代[可选安装决定](../process/2026-11-05-optional-model-vector-dependencies.md)中的本地模型配置；后续[FAISS 退出](../simplification/2026-11-06-retire-faiss.md)和[Chroma 退出](../simplification/2026-11-06-retire-chroma.md)接管相应向量后端的支持边界。原有 embedding、corpus 笔记记录的类型与资源所有者约定仍成立，涉及已删除实现的陈述由对应退出决定接管。

要求重排的检索预设不再隐式装配旧 CrossEncoder 或另一个 API 模型，必须显式配置服务或轻量重排器。HTTP 410 兼容入口不作为浏览器能力，沿用 API coverage 的非浏览器入口清单；正常 API 契约检查仍覆盖其余路由。

集成时发现原有越界问题门禁仍从已删除的 retriever 导出读取 get_vector_store，改为直接依赖实际 storage.vector.factory 所有者；其临时 retriever shim 同步修正。该修正用于保持真实 API 与 OpenAPI 可导入，不恢复旧模块的反向导出。
