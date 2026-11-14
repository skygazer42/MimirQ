# Agent Note: API v1 的失败、事务与异步执行契约

Status: implemented

## Problem

已有 API 路由精简了导入与装配，但部分业务异常仍被转换成正常结果：表格脱敏失败继续传递原始数据，版本查询失败转成无筛选扫描，合成用例回滚后仍报告创建成功。证据用例与关联分两次提交，第二步失败会留下孤立记录。Dify 的缓存准备在资源保护区之外，取消或失败后会遗留本机 singleflight leader。

同步 Session 查询、对象存储和文件解析还出现在部分异步入口。只把生成阶段放到 worker 不足以保证事件循环可用；准备、保存和清理需要各自明确的所有者。

## Decision

Dify 的缓存权限、metadata 范围和 Future 所有权继续受[Dify 缓存与任务归属](2026-11-14-dify-cache-access-and-flight-ownership.md)约束。后续修正要求先授权再使用快捷结果，按实际句柄发布或拒绝；本篇的取消、异常及 Session 责任继续成立，不能据历史缓存轨迹恢复权限旁路。

按 Python 规约保留正常无结果、可选 JSON、零值以及已定义的审计和增强降级，仅删除已经由实际类型或生产者保证的默认值与动态探测。无依据的查询重试、脱敏失败继续执行和主事务失败成功响应退出。PostgreSQL 与 SQLite 的不同读取路径在查询前按方言选择，数据库故障不作为选择另一种实现的信号。

版本 chunks 与 KG 数据库记录共用一次主提交，外部向量与 BM25 清理继续遵守已有的可观察降级。证据批量同步按单项先 flush 取得 ID、设置关联、再单次 commit；失败 rollback 后记录该项错误并继续。rollback 自身失败继续传播，不复用不确定的 Session。组和 SCIM 主写入先完成，专用审计边界随后提交；审计失败记录异常并恢复事务，主写入失败不被该边界捕获。

audit.py 的清理、删除、权限图导出和摘要共用一个附属审计提交函数，四处原有 action、details、commit／rollback 与失败日志保持；主查询、计划和删除仍在降级边界之外。原主操作失败传播政策继续遵守[维护失败边界](2026-11-09-maintenance-failure-boundaries.md)。审计查询与权限图共用同一 created_at／id 游标谓词，类型顺序从唯一模型注册表派生；查询自身的 LIMIT 负责分页上界，不再二次截断结果或重复检查同一预算。

导出的时间戳直接消费 ORM 的 datetime／真实缺省，不再将异常类型或序列化错误转换成 None；不支持的内部权限图类型不再生成 unknown 成功占位。正常空结果、可空标识和哈希／脱敏结果保持。gzip 压缩器由 with 关闭，尾部只在正常生产完成后交付，退出时不在 finally 中继续 yield，避免消费者提前关闭触发 RuntimeError。

同步数据库阶段使用现有 managed-session worker，在 worker 内创建和关闭 Session，向协程返回 ID、字典、模型或明确快照。ASGI Request、断连检查、异步排队和 singleflight Future 保持在所属事件循环。耗时文件操作通过已有线程桥执行；取消后先等待正在写文件的 worker 收尾，再由取得临时文件的层清理，避免清理后出现迟到文件。

文档资源的同步准备在worker内拥有独立Session并完成授权、路径／预览绑定、文件stat和对象HEAD；HTTP层只交接身份、inline及两个header值，返回构造好的Response。对象消费不再依赖数据库Session，原SDK流在消费时才打开并按原finally关闭；取消准备时等待worker结束。Range／304的本地和对象差异、主动内容attachment及私有缓存头保持，文件stat失败不伪装为空元数据；具体分类见[资源失败边界](2026-11-09-retry-source-error-boundary.md)。

分块预览的成员与dataset阶段由worker with SessionLocal持有，只返回数据，改用既有取消等待桥；临时目录删除保留单层5秒shield，取消先等正在运行的worker与清理完成。缓存条件锁由AsyncExitStack释放，初次／锁内命中提前返回，parse与store只有一份，原指纹、TTL、限额和列表副本保持。子进程成功协议必须提供documents，解析metadata编码失败抛带原链的RuntimeError，不再补空对象；原可选quality／token stats／review降级留下异常类型日志。

by-sha的非法dataset UUID、pipeline归一化和NaN ratio按用户输入400处理，上传原有400边界保持；内部坏协议／编码错误继续交服务器错误处理。token估计在每chunk复用一次，十字段metrics具名表达，不改变顺序／位置／统计。preview只转发chunker构造参数，不能将factory的metadata enrichment控制项一并透传而改变调用预算；HTTP参数与公开契约归属见[路由与输入所有者](../simplification/2026-11-10-api-route-and-input-owners.md)。

MinerU URL申请／状态API共用worker成员检查，只交回原role标量并在RPC前关闭Session；申请继续原.lower／EDIT_ROLES，状态不额外限制角色，RPC留在原循环。只在RPC边界转换预期ValueError／LookupError／RuntimeError，files序列化与Pydantic响应在该try之外。状态直接消费owner七字段，损坏输出不再通过KeyError／ValidationError转换成用户400或任务404，交全局服务器错误处理。

文档批量权限API把原同步写入交给with SessionLocal的worker；API保持async并等待已有线程桥，整个逐文档写入和Session关闭处于同一线程。原部分成功和逐文档commit归实际owner，不在适配器再加commit或事务包装。取消先等待这些写入与关闭完成，避免请求结束时还在使用外层Session；另外四个批量入口的原同步／异步委托保持，owner的完整审核继续按清单推进。

检索请求模型由 `app.api.schemas.retrieval` 持有，scope 由 `retrieval_scope` 持有，证据检索与共享预览操作由 `retrieval_requests` 持有。保留当前已退出图片向量检索的行为及 scope 的 None 哨兵，不切回旧的图片检索路径。Dify 支持模块直接调用本模块实现及日志、环境判断的实际所有者，不为测试补丁回取整个路由模块。评估证据校验和回归用例导入同样由专用服务持有。

Dify 缓存准备、早退和检索执行共用资源保护区；失败或取消先拒绝本机 leader，统一 finally 清理分布式租约。聊天同步保存与缓存写入在 worker 完成，singleflight Future 的完成仍在原事件循环执行。只移动整个 finalizer 会违反这项线程契约，因此异步 finalizer 明确分开这两个阶段。

Dify会话ID解析要求完整数据库／租户／账号上下文，不提供缺依赖就跳过授权的私有路径。body及两个header首个合法UUID合流后统一执行原owner／source绑定；外部非UUID source与请求ID优先级保持。已授权的显式会话不再重复owner检查，自动解析分支仍检查；原advisory锁、FOR UPDATE、幂等／seed及trace可观察降级保持。纯规则与HTTP适配的归属见[Dify单一实现](../simplification/2026-11-04-dify-helper-ownership.md)，不能把服务鉴权的默认账号或另一条会话查询错误带入当前HTTP入口。

普通聊天生成链直接传递已有 ChatExecutionContext，不在每层展开同一组字段或构造散装 kwargs。提取调用仍由一个持有 managed-session／检索限流边界的函数投影原参数，graph 在 worker 内替换 db，异步 LangChain 保留原上下文与事件循环。普通与流式入口共用 QPS、配额和会话准备，配额拒绝在保存用户消息之前发生。三个执行器返回完整结果、会话准备返回 UUID、全局中间件生成 request_id；这些内部生产者已经成立的契约不在路由重复判空或生成占位值，真实开放文档范围与可选模板继续使用 None。

摘要更新的成员和会话访问检查在 worker 内完整完成，不跨线程返回 Conversation。摘要服务先在一个 worker 物化消息并关闭读取 Session，回原循环生成，再在另一个 worker 保存。两个现有调用方的传入 Session 没有待提交主写入；不能把未来含未提交更改的 Session 随意接到这个入口。保存使用现有唯一键 tenant_id／conversation_id 的原子 upsert，摘要、消息计数及时间戳共用一次提交，避免线程化后两个首次写入同时查到不存在。任务去重和摘要版本选择仍属原业务策略。

检查点列表与详情使用同一个映射函数。当前两种 RAGState 图均返回字典 values，memory 和 sqlite saver 为已存在快照提供 configurable、checkpoint_id 和 checkpoint_ns；直接消费这些键，只有 created_at 为 None 的缺失状态返回 404。include_values 控制原状态字段是否输出，docs 始终排除，映射不修改快照本身；序列化失败不再通过空字典掩盖。真实 SDK 来源约束延续[会话与检索 API 消费实际生产者](../simplification/2026-11-05-api-session-retrieval-owned-values.md)。

会话更新、导出、消息和删除共用同一处实际访问查询，保留成员、租户、缺失与 ACL 的次序。分页值由 FastAPI Query 负责边界校验，内部收集器直接使用整数；仍扫描全部可见会话取得 total，不因页面已经填满而提前结束。只有真实的 403／404 可作为数据集不可见缓存，其他 HTTP 失败传播。导出审计保持附属降级，提交失败必须回滚并记录异常类型，回滚失败不能伪装为文件导出成功；主要查询与写入保持在该边界外。

分块预设更新与删除共用可写资源加载，先按成员、角色、租户和原数据集检查权限，再把同一个 Session 的 ORM 对象交给保存函数。后者只修改／删除并提交，不再次加载资源或生成 None／False 的结果分支；已有 scope 已获授权时不重复检查同一目标。新 scope、原 ID 400／404 和列表可读集合保持实际边界。声明可空的 payload 仅将 None 归一为空字典，其他内部错误形状交给响应模型，不继续以 dict(value or {}) 转成正常配置。

连接器预检按权限、原始配置模型、脱敏、分组引用与 egress 顺序执行。未知 ID 和真实 ValidationError 返回原有配置错误；模型／序列化的程序错误传播，不继续作为普通 200／ok=false 验证结果。仅成功配置交给可选预检，URL／DB 检查失败继续用已有警告呈现；Jira 的检查保持其已验证端点元数据语义。HTTP 层不再创建未被读取的 Session，真正的 with SessionLocal 和 async bridge 的取消等待仍由原 worker 包装持有。

分类列表的树与total由服务同一次已授权rows读取提供，使用已有树响应模型；total取全部行数，不遍历根节点或只数可呈现节点。API不再第二次COUNT，避免两个读取之间的变动导致树与总数不一致；树的既有构造、排序和不完整数据呈现策略保持。

数据集预检接口共用实际三字段扫描查询与404加载；分页、size和布尔参数直接消费已校验值。样本复核使用已有Pydantic样本模型后遍历四类分组，损坏内部条目不静默跳过；样本和近重复响应的模型错误交全局500。配置使用JSON模式写入，摘要导出使用模型原生JSON序列化，保证UUID和datetime可编码，不为这些类型加自定义编码或异常兜底。入队失败只写一次failed状态，补偿异常在API记录后仍返回原503，资源所有者退出时关闭并回滚，不继续在失败事务上执行SQL。

预检SSE只在worker内建Session、读取并转换完整JSON快照，关闭Session后才交给生成器；授权Session在函数作用域结束，不被流捕获。线程桥沿用取消后等待worker收尾的契约，初始／15秒keepalive和1秒轮询保持。后台扫描通过with关闭资源并保持本地活动注销；HTML可选样本失败仍降级，但留下异常类型日志，原路径隐私重建条件保持。

表格六入口共用原有数据集授权与成员上下文，单表入口共用解析与文档ACL，不增加原先没有的文档查询。实际查询结果进入已有TableQueryResponse后直接消费字段，Ask先保留执行不匹配诊断和strict409，SQL元数据只读取当前四分支生产者的必填键。FLS、回答模型及响应PII的先后顺序和预算保持，内部坏rows不再被转换为空成功结果。表格审计写入与提交共用一个失败边界，先回滚再记录，无法回滚继续失败；LOTUS连接用closing释放，加载的原生失败只在既定路由边界触发可观察回退。

DB目录的详情与快照共用三字段查表和404，缓存命中前仍完成当前权限与表归属检查。详情显式查询有序列并用summary模型投影，避免detail模型隐式加载columns关系。FLS和缓存直接消费owner的None／dict／字符串契约，历史快照清理及清理后缓存写入保持；目录脱敏审计在一个write／commit边界失败后回滚并记录，回滚失败继续传播。

数据集的13项公共配置在同一投影中解析，普通返回不解析导出专属policy／FLS／workflow。标量写入由请求模型选择字段，create、update和import继续各自决定None／缺省／replace；retention等owner的changed语义不统一成dict比较。列表直接返回已有模型，画像扫描使用真实ORM到Pydantic映射、共用租户三字段查询及单个入队失败边界；后台Session由with关闭。ZIP配置使用模型JSON模式，避免default=str把配置写成不能直接导入的字符串；导出的真实datetime失败继续可见，gzip由一个资源边界关闭。

写入型连接器准备阶段持有提交结果，直到能够交给原循环排队。等待被取消时先等待 worker 完成，使用已提交的 DTO 把尚未交接的 run 标为失败；调度入口在同一恢复事务中释放刚占用的时间窗，再继续传播取消。重复取消也不能跳过补偿。该资源边界已一对一改名为 managed_handoff，并供文档／扫描直接复用，见[已提交工作交接](../architecture/2026-11-14-managed-work-handoff.md)；没有保旧模块 alias。聊天缓存在等待分布式 singleflight 期间失败或取消，也会拒绝已经取得的本机 leader。

readiness 缓存由 `health_readiness` 持有，Dify 预热状态由 `dify_integration.warmup_state` 持有。设置热更新和健康探针直接依赖这两个所有者；健康探针不再反向读取集成路由，设置模块也不从健康路由取缓存实现。缓存以完整快照读写，预热状态仍使用原有锁和独立字典快照。

现有决定的关系：[路由与输入归属](../simplification/2026-11-10-api-route-and-input-owners.md)继续负责装配和输入；[Dify 辅助实现归属](../simplification/2026-11-04-dify-helper-ownership.md)继续负责纯规则复用，本次落实其中此前保留的实际证据检索依赖迁移；[聊天运行时数据契约](../simplification/2026-11-03-chat-runtime-typed-contracts.md)继续负责内部请求类型，本次去掉跨阶段无消费者的附着 Conversation 字段。

## Alternatives considered

- 预览去掉重复kwargs过滤后全部交factory，看起来少一个helper，但factory还会启用metadata enrichment／header等控制项，改变预览预算与结果，因此保留构造参数白名单。解析metadata出错继续补空对象可维持成功响应，却掩盖坏数据；改为明确内部失败。缓存为锁／无锁各保留一份parse/store容易偏离，使用标准AsyncExitStack只管理实际存在的锁资源。
- 批量权限入口直接改成普通同步路由能消除事件循环上的SQL，但无法像既有桥一样明确控制这条写入的取消等待与Session所有权；保留async入口，让唯一worker资源边界独占Session并沿原逐项提交完成。不把批量写入改成整批事务，也不为其增加重试或回滚后默认成功。
- MinerU两个入口维持各自手写状态投影和整段宽捕获，可让UI始终收到包装HTTP文案，但会把缺字段KeyError当成任务404、无效输出当成输入400；已有状态模型和SDK已规范化异常足以表达边界。给两个权限阶段分别写近似worker虽无额外分支，但完整TenantMember查询已提供原始role，单个资源owner返回标量即可，不增加write模式flag或ORM跨线程。
- 统一删除所有空值与宽泛异常可以缩短代码，但会破坏 PATCH 未提供语义、真实的审计降级和外部数据校验。本次按调用链和字段声明逐项处理。
- DB目录详情直接model_validate(table)可以省一次summary展开，但会读取ORM columns关系并引入隐式加载／排序变化；保留显式有序列查询。快照安全清理针对数据库历史JSON，缓存字典契约不能代替这个原始数据边界，因此只去缓存消费者的重复类型猜测。
- 数据集按一个通用mode把所有字段统一覆盖看似更短，但会改变update的None不操作／引用显式清空及retention真实changed；保留三个小的选择入口，合并重复字段处理和单次转发。把ConfigBundle整体用作列表投影也会额外解析policy／FLS／workflow；只共享真实公共13字段，保留已有模型实例。
- 表格直接使用list_tables_from_metadata能少维护解析函数，但会丢失当前文档绑定、2000列／200样本、字段截断和include=False时跳过坏可选字段的语义；现有API边界保留，只简化已形成契约的查询结果。LOTUS加载预先exists及二次HTTP包装能提供分层文案，但读取自身已会失败，路由也已拥有回退，不继续重复捕获。
- 预检继续逐项猜测样本形状或在每个JSON调用点自定义UUID编码可容纳坏数据，但会重复既有Pydantic契约并掩盖内部失败；直接使用现有模型和原生JSON模式。创建取消后的既有交接缺口需单独处理提交结果与任务所有权，本次不把它混入删减而新增一套恢复框架。
- 把完整异步路由放到私有事件循环能快速避开阻塞，却可能搬走 Request、客户端、取消协议和 Future。仅同步阶段跨线程，异步等待保持原循环。
- 为了兼容旧测试继续从路由反向寻找实现，可以避免移动补丁位置，却会保留隐式模块协议。测试直接替换实际所有者，不给业务增加兼容回路。
- 逐层展开完整生成参数能让每个调用点显式展示字段，但相同映射会随签名反复维护；复用已经存在的 ChatExecutionContext，仍在 worker 边界显式替换 Session，不增加另一种上下文或执行框架。
- 摘要保存继续先查询再插入可以复用 ORM 实体更新，但数据库操作进入独立线程后，同会话的两个首次更新会同时读到不存在。使用唯一键原子 upsert；仅在进程内加锁不能覆盖多进程，捕获唯一键错误后重试又增加不必要的失败路径。
- 每个会话入口保留完整访问查询使本地步骤全部可见，但四份成员、租户与 ACL 查询以后容易偏离；同一文件的真实查询函数负责这段访问流程，不增加通用装配器或跨路由依赖。
- 保存预设前再查一次可以发现部分恰好发生在两次读取之间的删除，但两次普通 SELECT 不能建立并发或权限的线性化保证；传递已经授权的实际对象，数据库写入异常继续传播，不为这个无锁流程增设布尔兜底或重试。
- 预检 schema 阶段捕获所有异常可使 UI 总能收到普通验证结构，但会把内部 TypeError、序列化缺陷等描述成用户配置错误；只转换已定义的输入失败，可选连接检查则按其独立的警告政策继续降级。
- 直接把验证 worker 改为裸 asyncio.to_thread 可以减少包装，却会改变已有的取消后等待清理契约；保留实际持有 Session 与 shield／等待的资源边界，删除的是无职责转发及未使用的请求依赖。
- 分类总数继续单独COUNT可复用原API查询，但会再次扫描同一租户，且可能与构树读取不是同一快照；使用已加载的全部行数。递归统计输出节点虽然能避免查询，却会漏掉未呈现的循环数据行，不作为总数所有者。
- 证据批量同步使用 SAVEPOINT 可以隔离失败，但现有产品就是每项独立提交；单项 commit 与正确 rollback 已能保持后续项和重试语义，不额外增加嵌套事务。

## Consequences

真实故障现在可能表现为请求失败或明确的单项错误，而不再是空结果、伪统计或未脱敏的成功响应。合法空解析、可缺省字段、审计 fail-open 和可选增强回退继续保留。启动配置、数据库 schema、部署和向量后端不在本次修改范围内。

聊天路由不再提供无生产消费者的私有别名；依赖这些属性的旧测试补丁需要改为实际所有者，不能据本次离线对照声称测试套件通过。直接读取 request_id 和执行结果要求内部调用遵守真实生产契约；若新增无需中间件的正式入口，应在该入口定义 ID 所有者，不能恢复每层兜底。

摘要生成期间释放读取事务，数据库操作多了明确的线程交接和 Session 创建成本；保存端依赖实际数据库的 ON CONFLICT 语义。已有唯一键无需迁移，多个成功生成的摘要仍按写入先后覆盖；不承诺最新消息版本必胜，也不新增生成任务调度。检查点字段的直接读取依赖当前工厂及 saver，正式接入其他返回契约时应在其边界适配。

私有分页调用不再接受非整数后返回 20，正式请求仍由原 Query 约束转换和拒绝。列表中的未知 HTTP 错误以及导出审计回滚失败可能成为显式请求失败；这是错误归属的修正，不能恢复成不可见数据或成功下载。合法空数据、scope 和无 limit 消息模式保留。

预设保存的内部调用方必须提供已在同一 Session 中加载、按租户和账户授权的对象；未来增加正式调用方时需遵守这个契约。并发资源撤回继续服从既有 ORM／数据库语义，未增加任务锁或版本约束。旧测试的私有别名及散装 ID 保存调用不作为生产兼容接口保留。

预检内部错误现在可能成为明确服务器错误；输入错误、权限拒绝、必需 egress 和可选预检警告各由原边界持有。Pydantic 类型决定后续预检分派，URL 元素直接使用模型已规范化结果；全空 URL 列表的既有归一化问题仍归属 schema 全文复核，不能通过在每个消费者补判空遮住。删除的请求 db 参数和私有 schema／转发 helper 不再供旧测试补丁兼容。

分类服务list_tree的内部返回改为已有Pydantic树响应，唯一生产调用方同步迁移；其他分类业务函数不因此被声明已规范化。并发变动下total对应这次rows读取，不对应稍后的独立COUNT结果；没有新增锁或改变写入事务。

预检与画像创建原先在commit后或等待enqueue期间取消，可能遗留没有队列／本地任务所有者的pending并造成409。后续已连同dataset_scan_session、两个实际API及queue协议核对修正，见[已提交工作交接](../architecture/2026-11-14-managed-work-handoff.md)：确定拒绝、已接受、未知 receipt 与本地 executor 分别处理。原SSE／后台清理验证不冒充该后续修复的运行验收。损坏样本更早在模型边界失败、内部异常明文退出及HTML可选样本降级继续保留。

表格的非法内部查询值现在更早在模型边界失败；审计写入失败也会触发回滚，回滚失败不再继续产品流程。LOTUS回退禁用时仍返回400，原因文字使用原生加载错误，不再包含二次table_load_failed包装。SQL／FLS／LOTUS业务owner的全文审核仍各自pending，不能用本次必要契约核对代替。

DB目录审计的写入异常现在也回滚，不恢复成日志后继续复用失败事务。缓存键、过期与历史缓存策略没有在本步重新设计，相关owner的全文审查仍待其清单；必要类型核对不代表整个缓存可靠性验收。

数据集ZIP的config字段从原字符串修正为结构化对象，版本化envelope及其他条目保持；原先依赖这个错误字符串的工具需改为真实配置对象。异常时间或gzip关闭失败现在保持可见，不再伪装null或正常导出。原raw metadata的best-effort、敏感字段隐藏、统计外连接None归零、配置空对象和任务降级仍按原所有者处理。

验证覆盖真实 SQLite 事务、故障注入、权限与范围、合法零值、取消后临时文件清理、线程中的 Session 生命周期，以及 Future 在原循环完成。PostgreSQL 集成测试仅在明确启用环境时运行；不把静态检查或 SQLite 通过声称为生产数据库、对象存储或模型服务验收。

初始全 API 相关测试收集被仓库现有缺失模块阻断；已把仍被实际消费者使用的 rerank profile 预算计算迁入现有 retrieval options 所有者，未恢复退出的配置包、数据类或向量实现。旧测试中针对已迁出的私有路由属性的补丁按实际所有者更新。扩展检查中的范围外失败单独列明，不以增加生产兼容分支掩盖。

## Verification

2026-11-12第27项预览1697→1522行；62组native解析、184配置／192raw参数／96实际内置chunk响应／291缓存／64API组合对照通过，输入呈现差异按路由Note单列。实际取消等待桥验证member／dataset同worker关闭以及临时目录一次性删除；token计数替身在固定语料504→288，不当作生产性能基准。元数据编码／缺协议字段不再假成功，by-sha三种坏输入400；没有应用测试、真实SQL、文件读写／发送、worker进程、模型、HTTP或Redis。

2026-11-12第25项document_batches.py从119行到116行，四个完整handler AST保持；35组适配、5组实际权限owner循环和重复取消收尾通过，OpenAPI5路径／14schema保持。worker使用记录器Session，下层单文档写入也为记录器，未执行应用测试、真实SQL／事务、权限写入、后台任务或HTTP。

2026-11-12第24项document_batch_upload.py从90行到73行，OpenAPI2路径／6schema保持；82组离线入口、六种真实status normalizer及ContextVars／worker关闭／重复取消／RPC取消对照通过，独立只读复核无新增需修项。Ruff／格式／AST3.11／编译通过，没有应用测试、真实SQL／事务、RPC、HTTP或上传。

2026-11-12第23项document_assets.py从524行到480行，109组入口／42组Range／32组disposition离线对照通过；三个入口的真实线程桥重复取消都等到记录器Session关闭，响应前已关闭，未消费时对象连接未打开。原生OpenAPI3路径／2schema除下载说明纠正外保持；SDK迭代器配内存响应核对正常关闭释放。Ruff／格式／AST3.11／编译通过，没有应用测试、真实数据库、文件发送、HEAD／HTTP或ASGI断连验收。

2026-11-12第21项external_api.py及必要caller的两入口OpenAPI保持，620行／19函数替代942行／36函数，24项无生产消费者转出退出；295个caller定义AST未改。leaf59／trace30／auth288／ID48／会话243组离线对照核对429条编译查询与77次记录器锁调用，独立复核无新增需修项。两个未修改service owner的既有查询／默认身份缺陷复现后记录pending；没有执行应用测试、真实SQL／事务／锁、HTTP、模型或Redis。

2026-11-12第19项db_catalog.py从277行收简到257行；191组离线入口、362条编译查询及40组缓存场景核对通过，局部OpenAPI3路径／8schema保持。真实FLS／privacy与纯内存cache owner验证正常／缺失／过期及清理时点，审计write／commit／rollback失败明确。Ruff／格式、Python3.11 AST／编译通过；不运行应用测试、真实数据库、事务或网络。

2026-11-12第18项datasets.py从3393行收简为2897行、126函数减为110；546组写入、84组输出、324组表路由、253组30handler和220条编译查询对照通过，局部OpenAPI24路径／61schema保持。另核对history6／gzip4／datetime4／background10及ZIP配置对象可导入；重复取消的完整任务交接仍未验收。Ruff／格式、Python3.11 AST／编译与独立审阅通过；不运行应用测试、真实数据库／SQL／资产／队列或网络服务。

2026-11-12第17项dataset_tables.py从1271行收简到1029行、40函数减为32；130组离线API、69条编译查询和80组元数据对照通过，六入口及局部OpenAPI（6路径／13schema）保持。真实SQL生产者四分支提供必填诊断，真实回答owner配假LLM确认完整提示词一致且已FLS掩码；pandas及记录器核对选择预算、引用和连接关闭。Ruff／格式、Python3.11 AST／编译及独立审阅通过；无应用测试、真实数据库、SQL、资产文件、网络或模型调用。

2026-11-12第16项dataset_precheck.py从962行收简为676行，16入口与原生局部OpenAPI（15路径／35schema）保持。58组离线适配对照、48条编译SQL及HTML隐私／后台清理／SSE快照、keepalive与取消等待通过；复现并修复配置和摘要导出的UUID JSON缺陷。Ruff／格式、Python3.11 AST和编译通过，独立审阅无新增待修项；创建取消遗留pending在两版复现，按上述边界记录。未运行应用测试、真实数据库事务、HTTP、扫描、队列或渲染器。

2026-11-12第15项五个分类HTTP合同与局部OpenAPI（3路径／8schema）保持，六组列表、八组CRUD适配对照验证总数、递归投影与权限。十五条编译查询中五次重复COUNT退出，行查询保持；服务除list_tree外12函数AST一致，schema58行原样已符合。Ruff／格式和Python3.11 AST／编译通过，不执行应用测试、真实数据库／HTTP或事务；部分修改的服务仍保留pending。

2026-11-12 第 13 项仅重构 connectors_validation.py，Ruff／格式、Python 3.11 AST／编译与局部 OpenAPI（1 路径／4 schema）对照通过。25 组离线接口值及轨迹保持，两个程序错误故障按新政策传播，54 个记录器 worker Session 关闭；旧／新各一次调用方取消等待清理，四种无预检类型返回原空检查。使用真实 Pydantic／async bridge 和无 I/O 替身，不执行应用测试、真实数据库／DNS／HTTP／队列。未使用请求 db 由 AST 验证，实际 worker 包装 AST 完全相同，独立审阅无待修项；原空白 URL 规范化发现记录到 pending schema，不能据此声明其全文完成。

2026-11-12 第 07 项复核 chunk_presets.py 与必要持久化 owner，限定 Ruff／格式、Python 3.11 AST／编译、4 个入口与完整 OpenAPI（358 路径／637 schema）对照通过。40 组入口和 10 组 ID 解析核对返回值、权限顺序、scope、保存字段与写入轨迹；72 条 SQL 编译记录中，创建／列表筛选保持，10 次重复预设 SELECT 及一次相同 scope 检查有意退出。正常可空／字典响应保持，损坏形状进入 Pydantic 错误，独立审查无待修项。其他 1,268 个 app Python、610 个测试、HEAD 与已暂存条目保持；未运行 Python 应用测试、真实数据库／HTTP 或并发事务，不把两次无锁读取当成原有线性化保证。

后续逐文件第 06／83 步仅重构 chat_conversations.py，Ruff／格式、Python 3.11 AST／编译、6 个 HTTP 契约及完整 OpenAPI（358 路径／637 schema）对照通过。43 组入口／导出和 9 组批次分页的离线结果、内容字节、正常调用轨迹及 SQL 对照保持；四项故障核对覆盖 HTTP 500／503 继续传播与附属审计回滚／warning／回滚失败，全部记录器合计收到 152 条编译 SQL。两个未改查询 helper 完整 AST 相同，独立审查无待修项。其他 1,269 个 app Python、610 个测试、HEAD 和暂存条目保持；未运行应用测试、真实 SQL／事务、文件导出、HTTP 或服务生命周期。总目标已扩大至 app，以主清单记录，不把 API 子清单等同全目标。

后续逐文件第 05／83 步处理 chat_conversation_memory.py 及必要摘要服务，限定 Ruff／格式、Python 3.11 AST／编译、7 个 HTTP 契约和完整 OpenAPI（358 路径／637 schema）对照通过。35 组 API、10 组摘要的离线值与业务轨迹保持，消息查询 SQL 相同；保存查询有意改为原子 upsert，7 条语句的 PostgreSQL／SQLite 编译结果覆盖正确冲突键和更新字段。21 个记录器 Session 经真实 worker helper 创建、使用并关闭，3 个真实内存 SDK 快照验证字段、404 和 docs 排除。独立审查发现并修复首次并发保存的 P2，增量复核无待修项。其他 82 个 v1、610 个测试、HEAD 和已暂存条目保持；未运行应用测试、pytest、真实数据库／模型／HTTP 或写 worker 取消时序，不把语句编译称为数据库并发运行验收。

后续逐文件第 04／83 步仅重构 chat.py，从 849 行收简到 554 行。限定 Ruff／格式、Python 3.11 AST／编译、两个 HTTP 入口签名／装饰器／说明和完整 OpenAPI（358 路径／637 schema）对照通过；三个未改生命周期 helper 完整 AST 一致。11 组生成、15 组普通入口与 4 组流式入口的离线值及调用轨迹保持，覆盖 worker 数据库身份、provider 降级、缓存和 503／取消拒绝 leader，独立审查未发现需修复项。其他 82 个 v1 文件、610 个测试文件、HEAD 和已暂存条目保持；Python 测试未改、未跑，未执行真实 Session、数据库、模型、Redis、HTTP 或服务器生命周期。详细范围与原始产物见验证记录，不把下述历史 pytest 结果算作本步执行。

后续逐文件复核第 02／83 步仅修改 audit.py，其余 82 个 v1 文件与该步起点字节相同。7 个 HTTP 入口签名、装饰器、说明和完整 OpenAPI（358 路径／637 schema）保持。92 个离线入口／故障场景中，192 条编译 SQL、65 条附属审计路径及响应／提交／回滚／警告轨迹一致；另外核对时间、标识哈希、32 份权限图记录、脱敏和 gzip 内容，复现旧 gzip 生成器提前关闭的 RuntimeError，并确认修正后正常关闭。该步不运行 Python 测试或真实数据库，不能将下述历史 pytest 结果当作本步重跑。

最终合并 33 个相关测试文件：609 passed、2 skipped、1 deselected。两个跳过项来自未启用的 PostgreSQL 版本接口集成环境；被排除的是此前已经失败的 `test_api_internal_state_contracts.py::test_runtime_migration_default_tenant_must_not_fabricate_zero_identity`，它检查 `app/core/migrations.py`，本轮没有修改该迁移工具，也没有把排除视为通过。

执行环境为 `ENV=test`、`EVIDENCE_POST_RERANK_PROVIDER=none`，解释器是 `E:/MimirQ/.venv/Scripts/python.exe`，没有修改本机 `.env`。命令使用 `-p no:cacheprovider` 和仓库外的 basetemp。精确命令、输出和 OpenAPI 在 `%TEMP%/mimirq-v1-guidelines-20261110/verified-command.json`、`verified-pytest.txt`、`final-openapi.json`；原始产物不加入源码目录。

83 个 `app/api/v1` 文件及 21 个必要支持文件的 Ruff 检查和格式检查通过。83 个目标文件均可按 Python 3.11 语法解析、为 UTF-8 且无 BOM。直接异步阻塞模式复扫排除明确的同步 worker 回调后没有命中；这项扫描只辅助人工调用链检查，不作为深层服务完全无阻塞的证明。OpenAPI 可生成 416 个路由对象、356 个路径和 640 个模型；没有启动应用 lifespan、模型、解析器或容器服务。

独立复核先在真实 SQLite 中发现了调度取消后遗留 pending run 的回归，修复后补齐提交后取消、准备和补偿期间重复取消、worker 失败、释放窗口后重试的行为用例；19 个连接器相关用例通过。聊天和 Dify 的原循环 Future、租约和取消路径也有独立行为验证。

模块依赖复扫中，新所有者没有路由反向引用；目标目录只剩 `documents.py` 六条现有的具名路由导出，属于仍有实际 Python 调用方的装配接口。全库模块边界检查仍报告历史迁移清单的过期记录，本轮没有改写范围外的清单。记录格式与归档检查通过；记录树检查仍有十条历史失效链接，不包含本篇新增链接。没有自动提交、重置或暂存已有改动。
