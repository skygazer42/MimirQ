# Agent Note: KG 搜索操作与实际状态分别归属

Status: implemented

## Problem

检索、扩展和两种排名门面只构造空对象，搜索门面也仅保存这些对象，却让引擎、重排框架和诊断链依赖类构造。Tracker 的五个纯节点构造操作与线索状态混在一起，recall 和 expand 还各自维护相同的关系方向规则。

## Decision

28 个无实例状态的操作由原业务模块持有。KGEngine 保留实际 extractor 配置对象，搜索直接绑定原 searcher 模块函数；KGReranker 保留框架接口、策略和进程缓存，只把无状态排名调用绑定到对应函数。诊断链传递具体异步搜索 callable，保持原注入点、配置、失败转换和结果组装。

Tracker 继续保存 clues、丢弃计数和预算，五个节点构造操作归 tracker 模块。两个关系方向操作由现有 relation_scoring 模块持有，保留 UUID 字符串化、谓词过滤和方向优先序，类型引用不提前导入 ORM。具体 SearchConfig、RecallResult、ExpandResult、RerankResult、Session 和 ORM 集合表达实际生产者；固定的查询模式、摘要配置和摘要计数字典使用 TypedDict，运行时形状保持。

缓存继续持有锁、条目、TTL 和 LRU；预算对象继续持有时钟和调用计数。只消费本地 len、缓存写入时生成的时钟与字符串、已解析预算和固定计数原值。外部参数、provider 分数、raw graph、持久化 JSON、Decimal、UUID、NaN、排序并列和原值转换政策保留。lazy index 的 sorted set 已保证唯一，退出其后不可达的第二次去重循环。

既有测试只迁移 import、构造调用和 patch 绑定；诊断 stub 仍是同一注入点，fake 对象继续提供原绑定方法。没有新增或扩写测试、helper、fixture 或断言，也没有运行 Python 测试。Tracker 事件 ID 的已确认缺陷单列在[对应记录](../bug-fix/2026-11-05-kg-tracker-event-id-precedence.md)，不作为等价整理证明。

2026-11-07 字段读取增量：RelationRepository 的查询明确选择完整 KgRelation，recall 和 expand 的消费链直接读取 15 处已声明字段。references 仍按原 JSON 字典边界处理，confidence 的 Decimal 转换、关系证据降级、方向、分数、溯源可空值、排序及 tenant／ACL 范围保持；不把空引用替换成伪造的 ID。

关系证据权重由已有 relation_scoring 模块的 relation_evidence 持有，两个阶段直接传入各自现有 Settings 实例。共享函数体与两份原实现相同，mention 属性仍在原分支及 try 范围内读取，浮点转换、默认值、NaN／范围限制、来源标签与异常返回策略保持。Settings 只作为类型检查依赖导入，该轻量模块的运行时初始化保持；未合并 recall 的别名门禁或 expand 的 hop 状态。

已核对三个仓储接口实际返回完整 KgEntity、KgEventEntity 和 KgRelation，图种子、边排序和实体过滤直接读取另外 13 处声明字段，事件关联映射的参数类型与真实查询结果一致。真实空字段、JSON 判断及原值转换仍保留。服务层预算的通用对象读取协议在本次保持原有范围。

## Alternatives considered

保留无状态门面能减少调用点 diff，但会继续掩盖真正状态和资源的归属。增加兼容 wrapper 或传入整个模块可以减少引用迁移，却保留第二入口或 Any 依赖，因此调用者直接绑定函数。

把缓存、预算、Tracker 和框架 reranker 一并函数化可以减少更多类，但这些对象持有实际锁、时间、线索、策略或框架职责，因此保留。把整个关系扩展合并能减少更多重复，却会改变现有 settings 读取和证据处理时点，所以只共享完全相同的方向计算。

## Consequences

检索调用路径少了空实例，配置与资源寿命更清楚；必要消费者和旧测试引用需要同步迁移。原会话关闭、timeout/cancellation、时钟调用次数、缓存复制与失效、tenant/ACL、预算、排序、分数和错误策略保持。静态检查覆盖完整操作 AST、实际生产者和调用绑定；它不替代运行时回归。

笔记检索中，[查询扩展](../architecture/2026-11-03-kg-query-expansion-owner.md)、语料缓存失效和 standard stream plan 的决定属于其他链，保持原归属；[混合排名](2026-11-05-hybrid-ranking-owned-values.md)与[检索编排](2026-11-05-retrieval-orchestration-owned-values.md)的原始输入边界原则部分重叠，沿用其结论。[KG 基础](2026-11-05-kg-foundation-owned-values.md)只追加 engine 的必要搜索绑定增量，不重复关闭 owner；[KG 提取](2026-11-05-kg-extraction-function-ownership.md)的 embedding 取得时点保持。这些既有决定均未被替代。

本次与 KG 提取增量共用 kg-declared-fields-20261107 源码核对材料，完整模块 AST 对照仅允许已批准字段读取变化，生产者、调用者和测试哈希保持；Ruff 与格式检查作为静态验证。按用户要求未运行 Python 测试或服务。autoreview 缺少 TruffleHog 的限制沿用既有记录，未运行模型审查。

关系规则增量记录位于 kg-search-relation-contracts-20261107。三个干净 owner 的完整 AST 对照限定共享原函数体、两个显式配置依赖调用、13 处已声明字段及一个关联记录注解；八个实际仓储、配置、调用入口和既有测试文件的哈希保持。Ruff、格式、Python 3.11 与记录门禁通过，未执行 Python 测试、模型、SDK 或业务函数；静态结果不替代检索运行时验收。
