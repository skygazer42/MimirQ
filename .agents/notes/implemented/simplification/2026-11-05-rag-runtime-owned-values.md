# Agent Note: RAG 运行链的配置字段与内部原生值

Status: implemented

## Problem

检索入口、图流程、缓存和追踪对已有 Settings 字段反复使用 getattr 默认值；主流程里的直接条件又先调用 bool。已经归一化的计数、分数和纠错参数再次转换，真正的回调、资源与 contextmanager 返回类型却没有写在签名里。

## Decision

六个所有者直接读取实际 Settings 声明的字段。保留每次读取的位置、原 bool／int／float／str 解析、or 默认、限额与模块快照时点。只有 if／while 中明确用作真值的单一值退出 bool 包装；返回、序列化、参数传递和复杂操作数的布尔结果仍按原合同产生。

缓存 key 的 len 直接生成整数，重排缓存写入直接返回自身 helper 的原生布尔值。ColPali 的三处 score 消费同一轮已经 float 解析的值；debug 的 channels 已由上一条 dict 构造，直接读取。纠错流程只退出 bool／int／float 解析和 min/max 后的再次转换，保留重试上限、阈值、浮点顺序和每轮摘要。

真实资源与状态继续由原类持有：两种缓存、singleflight 的 Future、锁与 ContextVar、租约心跳、HybridRetriever、文档 store、多向量检索器和追踪客户端。构造器声明 None，图节点回调声明既有 RAGState 到 RAGState，追踪上下文声明 Iterator／AsyncIterator，异步检索参数使用现有回调管理器类型。没有新增 Context、Manager、门面或业务模块。

重排 profile 的名称规则由 rerank_profile.normalize_rerank_profile 持有，配置查找和检索调试共用去空白／小写／空值规则。预算调用直接传入原字符串，由现有查找入口归一化一次，不再先做同样的清理。未知名称仍无预设；设置读取、搜索最小值、重排预设、层级扩取、上限和 MMR 乘数顺序保持。

图状态消费 `apply_retrieval_profile_overrides` 的实际固定核心字段，按键读取 profile、top_k、score_threshold 和 retrieval_mode；已有 builder 已生成原生 int/float，消费者不再补造缺失键或重复转型。阈值的零值继续规范化为正零，模式的真实可空优先级保持。层级和稀疏的可选覆盖每项只 `.get()` 一次；动态状态入口的输入解析继续由原位置负责，不能仅凭 dataclass 注解删除。

检索预算实际由 int、固定整数预设和 max／min 生成；计算与调试记录直接使用这些整数，查询归一化使用实际 NormalizedQuery 并继续复制 applied_rules 列表。实体分区元数据顺序选择原覆盖和模型值，不改变显式空值在实际分区解析与调试计数中的既有区别。已经检查为列表／元组／集合的 $in 直接按键迭代，每个原始元素只归一化一次；交集、大小写与输出顺序保持。

Redis JSON、SDK 与动态候选、模型结果、原始 metadata、授权范围和注入回调继续由原适配器处理。缓存键、内容指纹、空列表命中、租户／账号／文档绑定、加密、TTL、轮询、租约归属与续租、失败／取消与 finally 政策保持。LangGraph 的 task、entrypoint、重试／缓存装饰器、checkpointer、同步／异步边界及 stream writer 位置保持。

## Alternatives considered

把所有类型注解都当作验证，可以进一步删去数值转换与原始值判断，但 Settings 可在运行时赋值，外部 JSON、SDK 和 callback 也不保证相同原生类型，因此保留这些实际边界。

重做通用缓存或重新拆分图节点能把文件缩短，但会同时改变资源归属、导入与运行时阶段，不是统一常见写法所需的改动。当前在现有所有者内完成整理。

- 调试字段直接套用会拒绝退休值的检索 profile 校验器，可以少写归一化，但它会把原先仅展示的字段变成新的失败入口，因此不采用。重排名称规则只负责原来的清理和空值约定。
## Consequences

配置读取和主条件更直接，签名说明实际回调及资源。134 处已声明字段、27 个直接真值位置、12 处注解及18 个内部表达式是完整对照中允许的改动，249 个函数和15 个类保留。若改变 Settings 的声明、内部 helper 或缓存写入者，必须重新核对这些保证。

[Chat runtime 的类型合同](2026-11-03-chat-runtime-typed-contracts.md)继续持有 HTTP bootstrap 和序列化缓存输入；本篇处理检索／图流程内部。Dify helper 所有权记录描述另一条配置与缓存调用链，本篇不替代其决定。

验证依据六个完整原始文件、全部 diff、限定转换后的整模块 AST、实际 Settings 与 SDK 导出源码、Ruff 和笔记门禁。未增加、修改或运行 Python 测试，也未导入或执行业务、SDK、模型、Redis、数据库、业务正则、CLI、回调或真实数据。静态对照不代表实时检索排序、租约并发或生成结果已经验收。

检索预算与实体路由增量的源码证据位于 `E:/MimirQ/.superpowers/retriever-budget-routing-contracts-20261107/`。完整源码对照限于批准的重复归一化、原生预算、归一化记录类型及顺序语句；实际查询／实体生产者、固定重排预设、唯一预算调用与范围规则均已核对。Ruff、格式、Python 3.11 与笔记校验提供静态证据；未运行或修改 Python 测试，未执行检索、应用、SDK、模型、数据库或服务，排序和预算的运行时回归尚未验证。
