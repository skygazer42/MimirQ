# Agent Note: Embedding 归一化与空间指纹规则

Status: implemented

## Problem

LangChain adapter 与 DashScope provider 各自持有相同的 NumPy 向量归一化算法；当前 Settings 和显式配置也分别构造相同的 embedding-space 指纹。重复实现会让零向量处理、URL 规范化或缓存键在后续修改中分叉。

## Decision

`app.rag.embedding.utils.normalize_embedding_vectors` 持有向量归一化规则，adapter 和 DashScope 直接调用。NumPy 仍在调用时导入；零向量的分母仍替换为 `1.0`，没有增加空输入或错误恢复分支。

`embedding_space_hash_for_config` 持有空间指纹规则，`current_embedding_space_hash` 只选择当前配置并调用它。provider 别名、模型名、URL 去查询参数与片段、尾斜线、哈希算法与截断长度保持原义；当前配置仍允许回退到 `LLM_API_BASE`，密钥不参与指纹。

provider 构造选项、batch progress、连接状态以及 BGE-M3／Matryoshka 结果使用类型声明表达既有字典形状。模型、LangChain adapter、CLIP 缓存和 HTTP 并发控制继续由有状态类持有；外部 JSON、可选依赖、缓存与 CLIP 的既定异常策略保留。

## Alternatives considered

- 在 adapter 和 DashScope 中各自保留算法，能减少跨模块调用，但继续留下两份完全相同的规则，因此采用现有 embedding utils 作为共同所有者。
- 通过新基类或配置对象统一 provider，能集中更多装配代码，但会扩大构造和资源生命周期变更范围，因此保留现有注册类和关键字接口。

## Consequences

归一化和指纹只有一个维护点，类型声明让已有内部字段可直接读取。共同函数后续修改时需要同时核对 adapter 与 DashScope；若供应商明确要求不同的归一化算法，再将差异放回该 provider。调用时机、缓存命名与 TTL、批次及结果顺序、请求格式、重试与响应关闭顺序不变。Python 测试、模型下载、HTTP／Redis／向量库运行时验证按用户要求未执行；本批以 Ruff、源码 AST、调用引用与逐文件审阅为依据。
