# Agent Note: 删除未声明的 Settings 探测

Status: implemented

## Problem

Docling 包装器通过 `getattr(settings, ...)` 读取 `DOCLING_TABLE_MODE` 和 `DOCLING_EXTRACT_IMAGES`，向量工厂以同样方式读取 `EMBEDDING_DIMENSION`。这三个名称均未在 `Settings` 模型中声明，也不在设置 API 的 schema、运行时应用列表或部署配置中。动态读取让代码看起来支持一套实际无法配置的入口，并把拼写错误或过期设计伪装成兼容逻辑。

## Decision

Docling 的表格模式和图片提取使用现有实际默认值 `markdown` 与 `False`。构造函数的 `table_mode` 和 `extract_images` 参数继续作为显式覆盖入口；OCR 与启用开关继续读取已经声明的 Settings 字段。

向量工厂不再把不存在的 `EMBEDDING_DIMENSION` 放入进程内单例缓存键，设置 API 也不再把该名称列为向量单例重置条件。provider、model、API base 和密钥哈希仍决定 embedding client 缓存身份；向量维度继续由实际 provider/model 结果管理，本次不新增配置字段。

本决定与[解析适配器辅助函数归属](2026-11-05-parser-adapter-helper-ownership.md)和[Embedding 归一化与空间指纹规则](2026-11-04-embedding-rules-owner.md)部分重叠：前者继续持有 Docling 资源边界，后者继续持有 embedding-space 指纹；两篇均未定义这三个未声明配置，因此保留原决定并由本篇收窄伪配置表面。

## Alternatives considered

- 把三个名称补进 `Settings` 可以让现有动态读取变成真实配置，但 Docling 已有构造参数，embedding dimension 也没有进入 embedding client 构造；新增字段会扩大一套没有消费者闭环的配置接口。
- 保留 `getattr` 默认值改动最小，也不会改变运行结果，但继续暗示不存在的配置能力，并让后续维护者无法判断字段缺失是有意还是遗漏。

## Consequences

Docling 默认行为和显式构造参数行为不变。向量单例缓存键删除一个恒为空的尾部片段，升级后的进程会按新键重新创建一次内存单例；没有权威数据迁移、磁盘格式或网络协议变化。

本篇只宣称上述三个未声明 Settings 探测退出。其他模块的动态读取依其自身 Settings 声明或退役决定处理；第三方集成管线 stub 不纳入自研清理结论。验证使用当前 Settings 声明、设置 API schema/应用列表、完整引用搜索、Ruff、格式和 AST；按用户要求不运行 Python 测试或真实 provider、向量库与解析服务。
