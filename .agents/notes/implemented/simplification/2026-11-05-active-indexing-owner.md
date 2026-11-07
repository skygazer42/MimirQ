# Agent Note: 活动索引写入所有者

Status: implemented

## Problem

`indexer.py` 仍是生产、API、解析和任务使用的写入入口；`indexing` 下另有五个模块及 `ChunkVectorWriter` 类组成的并行实现，仅互相引用。它们由同次旧拆分新增，没有接入 `Indexer`、导出或注册。两套代码在可选与严格运行配置、元数据行读取、失败后清理、BM25 调用和 rollback 上已出现差异，不能直接替换活动实现。

## Decision

现行 `Indexer` 继续持有会话、向量客户端、写入与清理流程；移除没有调用入口的并行模块、类和独占辅助函数，以及主模块中两个无调用或注册的旧私有辅助函数。`indexing/vector_writer.py` 继续持有实际使用的运行配置错误、Milvus 判断、shadow 配置、缓存和双写函数。其现有函数体及缓存签名保持。

活动代码直接读取已声明的 Settings 与 ORM 字段。`EventEntityInput`、SQLAlchemy Query 和事件／实体向量回调使用实际类型；禁用的异步写入明确返回 NoReturn。回调仍接收原来的列表和绑定方法，资源初始化、操作顺序、参数、事务、重试、部分写入清理、配额与 channel 状态政策保持。

原始元数据、UUID、查询行形状、位置、可选证据和 provider 内容继续使用原校验。IndexingOptions 等 dataclass 不执行运行时校验，因此可空选项的布尔转换和原有证据数字解析保留。缺失、零和负值的既有默认与分支保持，不新增 Context 或协调器。

事件流水线哈希由本模块的 _normalize_event_pipeline_hash 统一去空白、将空字符串归空并截断到 200 字符，退出两个旧私有入口。事件物化直接传入原始引用值，仍拒绝非字符串；向量 metadata 仍先按原事件字段／引用优先级转为字符串，再调用共同规则，两类输入边界不合并。

事件实体的四个证据字段来自实际 EventEntityInput 数据类，提取器与插件适配器都构造完整记录，因此直接读取字段，继续接受真实 None、截断引用到 240 字符并按原策略解析坐标／记录错误。基础来源字典由 build_event_entity_provenance 构造，每个关联继续复制；关联 metadata 只计算一次，空字典仍以 None 落盘。事件实体缓存、role、权重、Session 写入与向量／通道失败政策保持。

2026-11-07 初始化状态增量：真实 Indexer 构造器无条件保存 Session 到 _db，生产调用方使用该实例，清理路径直接执行原 scope 触达与 flush。异常仍在原 try／except 中记录并按 strict 收集；两个批量删除函数仅在 commit=True 时回滚，实际 Session 的 rollback 方法按 SDK 契约调用。查询已取得 Document 且非空后直接读取声明的 dataset_id，原 UUID 处理和空数据集返回保持。

Embedding 标题别名按两组明确的有序键选择原始真值，由当前模块的 _first_header_metadata_value 在四处复用。保留选择时的逐键读取和布尔判断，不提前渲染或遍历列表。轻量前缀与 field-aware 入口仍采用各自原有列表显示、section 回退和长度限制，原 content、前缀、向量输入与其版本含义保持；十个单次条件表达式绑定退出。

[文档变更入口](../bug-fix/2026-11-05-document-mutation-contracts.md)直接使用保留的 `_update_bm25_for_chunks`，不为旧调用名重建包装；该调用迁移不改变本处的 BM25 和缓存所有权。

## Alternatives considered

接入已有并行类能缩短 `Indexer`，但这些类采用不同的清理和运行配置政策，直接迁移会改变活动调用方的行为。保留两套实现可以避免删除文件，但没有实际入口的副本持续分叉，也会让后续修改选错所有者；因此保留现行入口并清理未使用副本。

- 将事件列与原始引用统一当作任意值转字符串，可以只留一条入口，但它会让先前被拒绝的非字符串引用成为哈希，因此保留原始引用的类型边界，只共享内部文本规则。
## Consequences

项目中的写入调用和现有 private hook 继续使用同一 `Indexer`，客户端与会话归属明确；已构造记录不再重复解析。五个退出模块和类的完整源码已读，Git 跟踪源码、配置、测试与包导出检索没有发现岛外使用或注册。未引入未跟踪文件、依赖或新框架。

验证限于固定 Git 源码、实际 DTO／ORM／Settings／SDK 声明、调用约定、AST 与 Ruff。Python 测试、索引、数据库、向量、模型、网络、workbook 和服务运行时均未执行。

增量记录位于 initialized-indexer-reranker-state-20261107，保存当前共享工作区开始快照、构造器和真实 Session.rollback 契约。完整模块 AST 只允许两个必有属性 guard 退出、两个回滚方法探测退出及一个声明字段读取；strict／commit、删除顺序、缓存失效、日志、回滚和重新抛出策略保持。Ruff、格式与 Python 3.11 验证通过，未执行 Python 测试或业务／SDK 函数；本轮对已有部分初始化测试对象不新增兼容路径。

标题别名记录位于 embedding-header-alias-owner-20261107。完整当前／提交源码 AST 对照限定两组有序键、同义原始真值选择器和四个调用替换；五个生产者／元数据契约文件的哈希保持，列表转换和输出代码原文保持。Ruff、格式、Python 3.11 与记录门禁通过，未执行正则、抽取、embedding、Python 测试、SDK 或模型函数。

历史笔记中，[向量 writer 所有者](2026-11-03-indexer-vector-writer-owner.md) 与 shadow 函数职责部分重叠，原位同步已退出调用者的事实，缓存决定不变。[共享标量转换](2026-11-03-shared-scalar-coercion-owner.md) 的原始值边界原则沿用，索引的 `_safe_int` 继续返回 None。[语料缓存事务](../bug-fix/2026-11-03-corpus-cache-invalidation-transaction.md) 的事务与失效规则保持；前端索引状态相关笔记属于其他调用链，不被替代。

事件索引来源契约的源码证据位于 `E:/MimirQ/.superpowers/event-index-provenance-contracts-20261107/`。完整 Indexer 源码与 AST 限于共同哈希规则、实际证据字段和关联 metadata 顺序组装；原数据类、两条真实输入工厂、来源 allowlist、ORM 与已有测试文件保存哈希。Ruff、格式、Python 3.11 与笔记门禁提供静态证据；未运行或修改 Python 测试，也未执行索引、SDK、模型、向量或数据库运行时。
