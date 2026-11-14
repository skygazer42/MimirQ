# Agent Note: Dify 纯规则使用同一份实现

Status: implemented

## Problem

Dify 的 API 辅助包和服务包各自保存记录去重、评分、锚点和内容压缩规则。调用方难以判断规则归属，修改一份后也容易遗漏另一份。

三个知识范围服务入口调用纯 policy helper 时漏传必需回调，检索服务调用候选倍率 helper 时漏传 configured_max。它们在进入已有规则前就会因参数绑定失败；原 API 中已有完整的有效调用。

部分服务消费端又重复探测刚构造的策略字典、引用记录和结果标志；追踪限额及逐行去重 helper 也保留了相同副本。原始输入校验与这些内部重复混在一起，规则来源不够明确。

## Decision

纯规则由 `app/services/dify_integration/` 中现有的 `common`、`scoring`、`anchor_strength`、`compaction`、`records`、`request_preferences` 和 `tracing` 模块持有。API 和外部会话适配器直接导入这些实现，与这些规则共用的常量也使用服务包的定义。实际caller引用schema、类型和auth leaf时直达各自owner；没有生产消费者的24项HTTP转出退出，不为旧补丁留下兼容包装。

客户端IP、HTTP鉴权和当前会话持久化仍由external_api适配器处理。请求header与middleware的request_id在API层明确交给纯tracing函数；原始引用、元数据和数据库行的解析仍在实际输入边界。已经由Pydantic或内部构造保证的记录、布尔值和数值不再在消费者猜测形状。

Dify API support的token切分、常量时间比较、Bearer解析和必需UUID转换直接导入auth的同体leaf。HTTP request/header适配与_require_dify_actor由API持有，实际依赖注入、缺账号503、生产租户规则和其他HTTP错误保持；不把服务入口的默认账号分支带进HTTP。旧路由私有属性的测试补丁不作为生产兼容契约，需改用实际owner。

auth 模块只保留四个实际共享函数；知识范围也使用 token 切分和 UUID 转换，后者仍接收原始 JSON 元素并保留 None→400、object→str 的现有错误规则。token 比较直接使用两处入口已经切分／去空白的非空字符串。没有生产调用的 authenticate_actor 重复服务入口退出；实际 HTTP 依赖继续要求显式配置账号，不能将空字符串悄悄换成系统账号。模型、请求与响应仍由 integrations 领域包发布。

external_api的17个重复函数或单次包装退出，三个turn source-ID纯函数直接使用conversation_turns的同体实现；trace白名单只维护一份。其余会话写入仍保留当前HTTP实现，不混用存在owner比较差异和查询错误的另一条业务链。会话ID resolver要求完整db／tenant／account，按body和header首个合法UUID合流后统一授权；两个真实caller负责非空source ID，显式会话已授权后不重复owner检查，自动解析分支仍验证owner。

会话写入只在本地新建metadata字典设置turn_persisted与trace_seed，复用既有citation归一化／去重，不展开三次相同的字典。锁、source绑定、幂等、seed复用、事务及可选trace降级的执行边界保持，见[API执行契约](../bug-fix/2026-11-11-api-v1-execution-contracts.md)。

实际 HTTP 检索仍使用 conversations schema 的 ChatRAGConfig／EvidenceRetrieveRequest，并在原惰性调用点进入 app.services.retrieval_requests.retrieve_evidence。无生产根的独立 retrieval／warmup 及其专属 evidence_adapter 已退出，不恢复旧服务参数契约或不存在的导入路径。范围、缓存权限与真实 Future 归属的后续修正见[Dify 缓存与任务归属](../bug-fix/2026-11-14-dify-cache-access-and-flight-ownership.md)。

知识范围服务显式传入 policy_helpers 的既有映射与策略生产者，filter 和 fallback 回调用标准 partial 绑定其已有 leaf 及 planner 的倍率解析。候选倍率上限按原 API 的 INTERNAL_TOP_K_MAX、整数解析与原异常回退传入。没有给纯 helper 添加默认回调，也没有在服务中反向依赖 API、复制通用包装或改变原 API 的回调绑定。

HTTP 路由继续调用 API 自身的检索入口和 warmup；warmup_state 仍被实际启动／健康调用方使用。conversation_turns 仅保留 API 实际使用的三个 source-ID 函数，未被调用的另一套会话调度退出。冻结测试的旧服务／私有符号引用留待测试维护，不作为生产根。

服务只在具体生产者建立保证后直接消费内部值。策略工厂的正常结果始终是新建字典；其具体消费端保留 schema 与原始字段规则，省去重复的字典类型探测。引用记录的 content 始终由现有答案提示函数构造为字符串；预检和响应压缩标志、压缩阈值也来自实际布尔／浮点构造。通用回调 helper 和原始 metadata、JSON、数据库行、模型及配置入口仍保留各自校验、转换和值回退。

逐行去重复用 record_helpers 的同签名、同函数体实现，两个真实调用直接改用该模块，原本地重复退出。查询词限额复用已导入 common 的同值常量，追踪限额只保留一份声明。reranker 的两个私有结果参数标注实际 RerankResult；外部 ID、score、elapsed 的转换继续保留。声明 Settings 只移除 presence 探测，值解析、默认值和异常范围不变。

数值注解不作为原生值证明。缓存条目的时间戳只来自 time.monotonic，因此省去该字段的重复 float；TTL 的整数到浮点比较仍保留。压缩阈值只在内建 float 解析之后省去重复转换，保持原零值回退与运算顺序。实际缓存类、锁、单例和 Session 生命周期保留；缓存权限、任务归属、corpus 范围和 fast 聚合预算按上述后续决定修正，不再沿用原捷径。

## Alternatives considered

同名service可让HTTP入口一次缩为薄路由，但当前两条执行链确有配置零值、provider缺省、metadata假值、缓存corpus／解码和rollback失败政策差异。每份迁入定义按实际producer和依赖闭包核对，保留这些不同的调度与状态；不为缩小文件改变现有HTTP结果，也不新增兼容工厂或整模块Any注入。

把完整会话和鉴权都切到同名service可进一步删除HTTP代码，但conversation_turns当前用Message.role.in__导致查询构造失败，owner比较也没有HTTP既有strip；auth在账号为空时合成system:dify，而HTTP要求503拒绝。本次只复用已核对等价的leaf，两个缺陷归入仍pending的owner，后续逐文件处理；不以同名或相似结构推断业务等价。

保留两份辅助实现可以减少本次迁移的引用变化，但同一规则仍需两次维护。直接切换整条检索服务虽然能进一步缩小 API 模块，却同时涉及请求上下文、缓存、限流、追踪和会话持久化；这些职责需要各自核对，本次只合并已确认等价的纯规则。

将证据检索业务从现有路由整体迁到服务能完善层次，但需要同时迁移范围、配额、回退、轨迹及全部消费者。当前先修复适配器对未跟踪模块的依赖；整体检索迁移继续属于其业务批次，并沿实际所有者调整依赖。

给纯 helper 添加默认回调能使缺参调用继续执行，却会弱化它在 API 和服务之间已有的显式注入契约。只在遗漏的服务调用方绑定实际生产者，保留原参数要求和可观察的策略错误。

将所有相似记录函数统一到新的适配层会掩盖真实的回调注入差异，因此只合并完整等价的逐行去重 leaf。依据 int／float 注解批量删除转换也会跨越 SDK 与配置边界，因此只清理实际构造后的重复。

## Consequences

第57项对原integrations_dify.py的296个顶层定义逐项复核，四分片分别56／106／78／56项，统一写入避免同文件冲突。路由7628到3756行；116个本地定义继续持有HTTP调度与真实差异，88个实际服务owner直接绑定，92个内部名字不再由路由持有。没有新增app模块或改写service源码；引用owner不表示其整个文件已经完成本轮审核。公共承诺为router、两个HTTP处理函数与实际启动warmup函数；模型／服务规则仍归各自定义模块，纯测试转出不恢复。

HTTP缓存仍独立构造自己的实例，复用缓存类及无状态lease规则，不接管service singleton或clear。HTTP Redis记录解码、Dataset.updated_at corpus hash、metadata None／空映射哈希、TTL／LRU边界和singleflight／lease的owner、heartbeat与cancel→await→release政策保持。内部follower只能收到本链resolve的records:list，distributed非leader仅在cached is not None时产生；空列表继续合法命中，缺失内部协议不再伪造空成功。

Settings经BaseSettings工厂验证，入口直接读取真实数值／布尔／字符串，仍保留0的关闭值和原上下限。warmup可选Session获取失败后的finally、调度失败关闭coroutine、任务状态和HTTP warmup集合独立性保持；真实可空ID／cache miss／lease状态仍可空。metadata fallback的kwargs本已是独立字典，调用方不再传入立即丢弃的请求db，整数毫秒预算截断／rollback／timeout规则不变。单次mixed开关及cleanup转发退出，main finally直接调用同一cleanup owner。

引用检索四个实际调用点显式提供已解析的requested_top_k与四个开关，三项真正可省略的KG数值参数继续按原配置规则补齐；已提供的top_k、mode和KG数值直接传给实际请求模型，不重复转换或回填。记录的content／refs／已构造slot字段按真实producer读取，原始metadata与SDK的ID／分数／耗时边界保留；排序的加数顺序、稳定次序、候选和压缩预算未变。函数迁入后的部分诊断logger名称归实际owner，消息、级别和既有traceback政策保持。

验证覆盖两个原生HTTP接口／8schema OpenAPI完全相同、88个实际导入对象身份、HTTP／service缓存独立及clear、5条main正常／命中／取消／HTTP错误／意外错误与finally轨迹、20组实际记录排序／去重／压缩投影和两缓存类TTL边界。分片另含98组lease TTL、31组scope／JSON、6组corpus、95签名／73绑定AST／3算法展开、113条无连接SQL编译／36组行与KG／100组主范围及四必传签名核对，三份独立复核无待修。没有运行Python应用测试、实际HTTP／SQL／Redis／模型／任务或业务文件I/O；旧私有patch及缺省参数测试留待迁移，不把保留测试字节称作测试通过。

第21项将external_api从942行／36函数收简为620行／19函数，必要caller从7674行到7628行，除request-ID适配外295个定义AST保持。两文件Ruff／格式／AST3.11／编译通过，原生Dify OpenAPI（2路径／8schema）保持；leaf59／trace30／auth288／ID48及会话243组离线对照覆盖429条编译查询和77次记录器锁调用。真实数据库锁与并发、HTTP、模型、Redis和应用测试不运行，caller及服务owner全文仍pending；历史验证不替代本次范围。

服务证据适配器的输入对照位于 E:/MimirQ/.superpowers/dify-evidence-parsed-preferences-20261107/。四个实际调用点满足五个必传字段，完整模块 AST 仅允许已解析字段消费与直接请求构造；原 HTTP 实现、schema、检索／预热调用方和 Python 测试源码保持。Ruff、格式、笔记门禁与静态调用核对不替代真实 Dify、数据库或模型验收，Python 测试不运行。

五个重复 API 辅助模块退出，纯规则及共享常量各有一个维护位置。现有路由、检索阶段和 HTTP 错误转换保持原来的实现。

验证使用源码、AST、引用核对和 Ruff；按用户要求不运行 Python 测试。运行时检索、模型和数据库行为仍未验证。

四处服务参数修复以固定基线的同域签名绑定和原 API 有效调用为证据，单列于行为保持精简之外。JSON 解析、知识映射顺序、策略字段、倍率上限和原配置异常处理沿用既有实现；只补齐进入这些规则前遗漏的参数。验证不导入应用、服务或 SDK，也不执行回调、配置 regex、模型、网络或数据库。

20 个 pending 服务 owner 的 9,244 行、369 个基线函数完整读取；7 个已闭合模块只作实际生产者／调用方依赖。行为保持部分使用完整基线／候选 AST 的限定替换、helper 等价、常量值、实际数据构造、导入依赖与资源／SQL／regex／缓存保护证据。私有生产者协议以后改变时，需要同时调整这些消费端保证。
