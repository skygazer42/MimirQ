# Agent Note: KG 提取使用模块函数与实际资源对象

Status: implemented

## Problem

KG 正常化和 embedding 门面没有使用实例状态，却要求调用链构造并传递空对象。提取器大量操作只消费参数，仍占据配置对象的方法空间；四个提取通道还重复维护同一置信度转换规则。类型中的 object 和 SimpleNamespace 也遮住了已有生产者。

## Decision

实体名称与类型正常化由原 parser 模块的两个函数持有，保留原常量表、Unicode、正则、括号、标点与大小写顺序。真实调用者直接导入函数，退出空 parser 实例和仅为传递该实例而存在的参数；原函数内延迟导入继续在原时点执行。

两个 embedding 操作归原 loading.processor 模块。实际 get_embedding_client 在每次调用时经 asyncio.to_thread 构造 EmbeddingClient，原门面没有保存客户端；模块函数保留每次取得客户端、await、结果和 AIError 转换，不增加缓存或提前初始化。

提取器中不读取实例状态的操作归同一模块，Session、信号量、进度和已有后处理状态仍通过原参数传入。EventExtractor 保留实际 model_config 与依赖该配置的构造流程。GLiNER 模型缓存、Hybrid 的后端依赖、LLM 与允许谓词对象继续保留；HeuristicExtractor 保留既有后端对象协议的方法，纯计算归模块。

四份相同 clamp 由既有轻量 evidence 模块持有，显式 default、Exception、math.isnan 和 min/max 顺序保留。其他关系、别名和技能的不同 NaN、零值和默认策略不合并。内部类型引用实际 backend selection、LLM、Session、Indexer、PersistEventsResult 和 KG 模型；不新建通用 Context 或模块 Any 注入。

引用迁移只改真实 import、调用、旧参数、导出和 patch 绑定。既有测试仅适配退休符号与隐式 self 绑定，不增加用例、helper、fixture、断言或执行测试。已完成的 repository 仅迁移 _normalize_alias_surfaces 的延迟正常化调用，原参数、默认、查询与异常保持，不重复计完整 owner。

2026-11-07 字段读取增量：核对实际 ExtractConfig 构造、数据库 DocumentChunk 查询、后端分派和 AliasCandidate 生产者后，提取器与 heuristic 后端直接读取 31 处已声明字段。常规 sections 保持数据库 chunk，只有插件输入经 _document_from_chunk 转成 LangChain 文档；不把两个协议混用。真实可空位置、插件参数与别名引文仍按原值处理，JSON 检查、超时、重试、清理和事务策略保持。

## Alternatives considered

保留全部空对象可以减少本次 diff，但会让没有实例状态的规则继续依赖构造器和参数传递，真实资源的寿命也更难辨认。

把所有处理器一起函数化能减少更多类，却会抹平缓存模型、LLM、允许谓词和既有后端对象协议，因此只退出没有实际状态职责的门面，并保留资源对象。

新建统一管理器或兼容 class 可以集中调度，却增加第二套入口和维护点。当前在原模块持有函数，真实调用者直接迁移，不添加兼容包装。

## Consequences

配置和资源对象与普通操作的职责更明确，调用链少了空实例。迁移保留原方法绑定后的参数、语句、资源、并发、事务、预算、指纹、排序、超时、取消、原始 JSON／向量／SDK 验证和失败策略；已确认的行为修复仍按所属组单列。

[KG 基础归属](2026-11-05-kg-foundation-owned-values.md)与正常化调用局部重叠，保留其已接受的仓储、ACL、分桶和事务决定；[KG 查询扩展所有者](../architecture/2026-11-03-kg-query-expansion-owner.md)仍持有检索编排边界，不迁移其策略。

验证限于源码、实际生产者／调用者／SDK、Ruff、格式与隔离 stdlib AST311／哈希／静态绑定。没有执行应用、SDK、模型、服务、数据库、真实正则或 Python 测试，不把静态投影写成运行时回归。

本次字段增量与 KG 搜索一起记录在 kg-declared-fields-20261107 源码核对材料中：四模块 AST 只允许 46 处已批准字段读取变化，声明所有者、真实调用者和既有测试的字节哈希保持。另有两处 heuristic target 读取来自已核实的 sections[0]。预提交 autoreview 的已知限制仍是缺少 TruffleHog，未运行模型审查，也未安装额外工具。
