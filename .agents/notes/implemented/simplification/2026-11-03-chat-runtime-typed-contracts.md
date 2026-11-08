# Agent Note: Chat runtime typed contracts

Status: implemented

## Problem

Chat bootstrap accepted `Any` for requests and RAG templates, then used `getattr` defaults for fields owned by `ChatRequest` and `RagConfigTemplate`. Dataset metadata was also checked as a dictionary after its loader had already guaranteed that shape. Cache and persistence inputs used bare container annotations.

## Decision

The bootstrap runtime uses `ChatRequest`, `ChatRAGConfig`, and `RagConfigTemplate` at the existing internal boundary. It reads their declared fields directly and consumes dataset metadata as the dictionary returned by `load_dataset_metadata`. Nullable template counters still normalize `None` to zero. Cache key resolution types its database dependency as `Session`, matching `resolve_corpus_cache_token`.

Cache payload parsing remains a serialized Redis boundary: dictionary and citation shape checks, best-effort cache failure handling, and singleflight follower behavior stay in place. Optional memory lookup, cache keys, tenant/account/document scope, lease timing, timeout, and cancellation behavior are unchanged.

RAG 配置模板的 `usage_count` 是模型声明的 best-effort analytics。`rag_config_template_resolver.record_rag_config_template_usage` 统一聊天和预览入口的加一、commit、失败 rollback 与 warning；模板选择和配置应用结果不因计数失败而回退。两个消费者直接读取 resolver 返回的 `RagConfigTemplate` 字段，不再以 `getattr` 补造缺失字段。

聊天指标上下文按字段的业务顺序直接补充，不把值和启用标记组装成三元组再交给转发函数。两种配额结果来自现有配额服务，包含 enabled 字段；可选结果缺失仍以 None 表达，已有结果直接读取其真实字段，不把内部漏字段转成关闭。十三个 setdefault 写入的键、顺序和原值优先规则保持，输入指标仍复制后再补充。

LangChain 的外部事件指标由 _annotate_cache_metrics 校验并返回字典，两个实际调用点都在此之后应用上下文，因此 _apply_metrics_context 直接接收已整理的字典。外部事件形状、内容转换及真实的可选状态检查保留；token 分支不再对已经判定为字典的数据重复补空字典。

物化流的内容和 request_id 来自既有字符串生产者及声明的 dataclass 字段，消费者直接使用，不重复转字符串或用空文本遮住缺字段。dataclasses.replace 返回相同数据类，流式与 LangChain 持久化参数直接使用返回值，移除三处没有运行时转换作用的 typing.cast。缓存、断连、取消、流式分块、错误脱敏及持久化调度的原顺序和策略保持。

缓存查询统一要求必传 ChatCacheLookupInput。流式准备入口构造同一模型，保留原十五个字段及求值顺序；普通聊天和现有测试已按 options 传入。没有调用方使用模型与散装字段混合覆盖，因此删除 legacy_overrides、可选输入默认值和参数归一化 helper，不维护第三种内部调用形式。既有重导出和 HTTP 路由继续保留。

缓存与 singleflight 的布尔开关、TTL 和等待超时直接使用 Settings 已声明的类型，原 max 下限保留；singleflight_key 在首次真实赋值前不再重复初始化。分布式等待函数只有在缓存或瞬时结果已通过 isinstance(..., dict) 时才返回跟随结果，接收端直接使用该字典，不再以空字典掩盖生产者违约。缓存载荷的反序列化、正文转换、引用形状、错误降级、总等待期限、取消后重试和租约策略仍由原实现负责。

流式编排的四个私有函数直接接收已经构造的 ChatStreamRuntimeContext，复用其中三组已应用默认配置字段和两种配额信息，不在每层重复展开五个参数。两个图／LangChain 选项构造器从同一上下文读取原字段，调用方同批迁移；没有新增数据类或复制状态。心跳与断连开关仍在原位置读取，避免借参数整理改变等待或动态配置时点。

编排直接使用 ChatRequest 的记忆与结构化输出字段、ChatRAGConfig 的答案模式和 Request 的真实 client 可空边界；request_id 在入口按原缺失策略生成并只归一化一次。已被准备结果覆盖的指标和结构化数据初值删除，dataclasses.replace 直接传递返回值。RetrievalAdmissionTimeoutError 构造器必定提供 Retry-After，超时事件直接读取该字段。抽取降级的私有转发函数要求显式传入已有错误参数；真正可选的外层降级回调继续保留默认值。

消息元数据构造接收实际调用方提供的必需问题字符串、指标字典和引用列表，不重复设空容器或字符串。引用项仍属于原始提供方边界，逐项形状与字段转换继续保留。持久化直接传递内部 request_id、计数和布尔开关，流式后台任务仍复制指标字典；消息、审计、会话更新、提交、线程调度、清理与既有失败策略保持原顺序。

抽取式聊天执行直接读取有效 ChatRAGConfig 的 50 个声明字段，与已有图／LangChain 执行入口使用相同的字段契约。仅删除属性缺失时的 getattr 默认值，真实可空值及显式抽取模式的 if／else 保留，故障降级的查询扩展、候选数、重排预算与证据范围不变。原始模型输出、引用、ORM 元数据与提供方错误继续按原边界处理，不引入新的配置或兼容分支。

[RAG 运行链的配置字段与内部值](2026-11-05-rag-runtime-owned-values.md)沿用上述缓存边界，处理检索、图流程及实际资源的读取与签名；本篇继续持有 HTTP bootstrap 的类型决定。

## Alternatives considered

- Keep `Any` and defensive `getattr` defaults: this supports objects that do not satisfy the existing request and ORM contracts, but obscures missing internal fields and duplicates schema guarantees.
- Remove Redis payload checks with the internal checks: cached JSON is externally serialized state, so its shape still requires validation.
- 保留指标的三元组和转发 helper：可减少重复书写，但每个字段都需要跨层查找启用条件与写入规则；当前两个 helper 只有一个真正的业务调用方，直接顺序判断更易阅读。
- 保留 options 与 legacy_overrides：迁移成本较低，但会同时维护显式模型、散装参数和混合覆盖。当前两个生产调用点已能共享同一模型，流式调用方在同批迁移，不留下无调用方的混合覆盖路径。
- 继续在四层传递同样五组字段：依赖逐项可见，但每次调整都需要同步多份签名与转发。现有运行上下文已包含相同字段，直接复用可以缩短传递链；不另外引入配置对象或通用管理层。

## Consequences

Valid API requests and ORM rows use explicit declared types. An internal caller that omits a required request or template field now fails visibly instead of being treated as a disabled option or empty value. Wire formats and cache key inputs do not change. 模板计数失败仍不改变已选配置，但日志会暴露 template_id；成功请求不保证 analytics 计数落盘。

## Verification

Ruff check and Ruff format --check passed for all four target files and the direct stream orchestrator caller. Python AST parsing passed for those five files. Caller scanning confirmed the chat route, stream orchestrator, and bootstrap runtime share the declared `ChatRequest` type; cache key resolution delegates to the `Session`-typed corpus token owner. `git diff --check` passed. Python tests were not run per user instruction.

2026-11-07 的指标与流式整理证据位于 E:/MimirQ/.superpowers/chat-metrics-readability-20261107/，包括原始源码快照与源码对照结果。核对十四个既有函数签名、十三个有序指标写入、流式数据类、错误脱敏和两个流式模块的完整 AST；变更白名单限于已核实内部值、重复判断和无运行时作用的 cast。Ruff、格式、Python 3.11 语法和笔记门禁通过；未修改或运行 Python 测试，也未执行真实流、模型、Redis 或数据库。

缓存输入整理的证据位于 E:/MimirQ/.superpowers/chat-cache-input-contract-20261107/。完整模块 AST 对照仅允许输入模型迁移、已声明配置取值、重复初始化和跟随载荷兜底的变化；十五个原始构造字段、其余十六个函数签名、缓存数据类、等待／取消／异常策略保持。实际三个调用点全部提供 options，原测试源码保持；不运行 Python 测试、应用或 Redis。

编排与持久化证据位于 E:/MimirQ/.superpowers/chat-stream-owned-inputs-20261107/。三个完整源码模块按已核实变更逐项 AST 对照，五处私有调用均满足新上下文和显式错误参数契约；原数据类、HTTP 路由、请求模型与异常生产者保持。实际 schema 声明布尔字段，超时异常提供 Retry-After，原测试源码不修改。Ruff、格式、Python 3.11 语法及笔记门禁完成；这些静态证据不代替真实流、数据库、模型或 Redis 验收，Python 测试不运行。

抽取式执行字段读取的证据位于 E:/MimirQ/.superpowers/chat-execution-declared-fields-20261107/。50 个字段都存在于已提交的 ChatRAGConfig；整个执行模块 AST 仅包含对应读取变化，原签名、状态构造、模式分支、检索／模型调用与资源控制流保持。Ruff、格式和笔记门禁通过，Python 测试源码保持且不执行；自动模型审查因缺少 TruffleHog 未运行。

2026-11-08 的模板计数 owner 增量运行三个暂存源码文件的 Python 3.14 编译、限定差异/空白检查和 Note 门禁。当前环境未安装 Ruff；依用户指令未新增或运行 Python 测试，也未执行数据库、聊天或 RAG 预览运行时。
