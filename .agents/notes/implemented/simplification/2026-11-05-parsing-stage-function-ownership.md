# Agent Note: 解析管线的普通函数与结果边界

Status: implemented

## Problem

归一化、治理、切块、精确去重和索引五个阶段没有实例状态，却通过 class、factory() 和 run() 逐层传递。读入库主流程时需要跨过没有生命周期职责的对象，才能看到实际输入和结果；切块与去重的内部函数也依赖无用途的 self／cls 参数。

同一管线已经有明确的 InlineAssetResult、ChunkPostprocessStats、GovernanceStats、MarkdownCanonicalizeResult、ParsingError 和 ORM 字段，但消费端又把必需字段当作可能不存在，并重复转换本地计数、已解析分数或哈希字符串。与此同时，缓存、子进程返回、页面元数据和图像后端仍是原始或可选边界，不能与这些内部结果混为一谈。

## Decision

五个无状态阶段在原模块内使用普通函数：govern_documents、normalize_documents、chunk_documents、deduplicate_chunks 与 index_chunks。切块和去重的辅助函数仍与其入口同处 stages.py；不新增模块、统一 stage context 或一次性转发对象。函数入口先于各自细节，原参数、结果及内部执行顺序保持。

文件和图像预处理的真实返回路径均构造完整结果，changed 为布尔值、output_path 由实际 Path 转字符串；消费端直接读取，不再缺省为空路径。索引开关来自 build_indexing_options 的完整 IndexingOptions，记录真实类型并直接读取字段，既有开关转换保留。checkpoint 查询得到完整 DocumentChunk／DocumentParsedContent，查无记录时明确退出，空正文、原文和原总字符规则继续处理。

两种 checkpoint 恢复共用 _checkpoint_option，在当前保存值、请求保存值、调用参数和 auto 之间按原真值顺序惰性选择，再去空白。已选中的空白字符串仍变成 auto，不继续回退到后面的字段。LangChain Document 的实际 SDK 声明了可空 id 与 metadata；来源映射和缓存写入直接读取这些成员，缓存反序列化仍验证原始载荷、真实 None 与空集合的差别保持。

DocumentProcessorService 继续持有处理入口和现有依赖接口。ParsingStage、InlineAssetStage 与 ChunkAssetStage 仍接收 service，保留解析取消、产物目录、图像上传与 SDK 清理行为。它们通过 type-only 引用声明实际 processor 依赖，避免循环导入；图像后端在原位置加载，外部图像对象继续保留实际协议处理。

真实 flow 调用方直接接收和调用五个函数，不再构造对应阶段。这个已独立审查的模块只迁移必要的参数、类型与调用点，不作为本批完整 owner 再计完成。旧 test import、已有调用与 monkeypatch 目标同步到新符号；没有增加、扩写或执行测试用例、断言或 helper。

已构造的计数、分数、哈希与真实结果字段直接使用。InlineAssetResult 中仍可空的 audit 必须经过原 dict 判断，metadata 写入仍按原规则复制；字段表只引用该结果中真实声明的属性。DBDocument 的逻辑来源读取声明实际 ORM 类型，doc_metadata 的原始字典规则、源路径优先级与空文件名回退仍保留。

processor、处理流程与恢复模块直接读取 PipelineEffective 和 GovernanceStats 的声明字段。配置解析器返回完整的 frozen dataclass，治理统计的两个真实构造路径也覆盖必填字段，其余属性由数据类缺省值创建；消费参数没有在读取前被重新赋值。因此移除 78 处 getattr 的字段存在性兜底，不再支持缺少声明成员的内部替身对象。字段值原有的 int／float／str／bool、字典复制、范围限制与 or 语义仍按原位置执行，没有把数据类注解当作运行时数值校验。

该增量不删除 ORM、SDK、原始 metadata 或动态插件返回值的取值保护；重试、取消、checkpoint、治理降级、分块、索引、租户约束、资源关闭和事务控制流保持。阶段函数、注入入口和兼容注册名称不变，不增加类、模块或解析协议。

2026-11-07 ORM 字段增量：正常流程和恢复路径的数据库查询已取得完整 Document，并在缺失时提前退出，因此另外 17 处声明字段直接读取，保留原 JSON、可空 owner／dataset、状态和失败转换。另五处错误／取消路径继续使用原 getattr：process_document 在 begin_process_document 返回前可能失败，此时 runtime_state 中还没有 db_document。它们的现有 DBDocument 注解不足以证明对象存在，不能直接替换成属性读取，也不能改变原异常处理顺序。

图像代码处理固定启用，因此 InlineAssetStage 中依赖 not image_code_enabled 的提前返回不可达，直接退出该死分支；其余开关仍按原顺序计算，图像代码、公式、图表、标题和上传仍按原顺序执行。

本批保留本地缓存反序列化与过期清理、质量门禁 JSON 序列化、预览解析入口、重试／checkpoint 恢复、路由选择、worker 协议和常量模块的原始边界。asyncio Process 与 Popen 两种进程、进程组信号、等待、超时、取消、日志／结果限额以及错误分类没有统一成新抽象。解析输出的顺序、metadata 名称、缓存键、租户／路径／ACL、事务和事件保持。

## Alternatives considered

- 保留五个 class 可以沿用 factory 形式，但它们没有独立状态或资源，调用者仍要维护构造和 run 两套协议。因此只退出这些壳，保留实际有 service 能力的阶段。
- 把所有阶段移到新模块或再建通用 manager，能统一接口，却增加维护位置并隐藏现有差异。因此函数留在实际业务 owner，并显式迁移真实调用方。
- 保留所有 int／float／getattr 默认写法可以兼容任意不符合内部类型的替身，但会把已保证的字段和原始输入边界混在一起。因此只简化有生产者依据的内部结果；原始数据、可选字段和 SDK 保护继续存在。
- 重写整个 process_document_flow 能进一步整理流程，但该 owner 已独立完成审查，当前增量只需要阶段接口迁移与已声明字段读取。因此不改其预算、fallback、事务、取消或元数据逻辑，也不重新归入完整范围。

表格和质量结果的消费端直接读取实际 TableAsset、TableRouteDecision、TextQualityScore、GovernanceStats 与完整 PipelineEffective 的声明字段。两条导入路径都返回完整资产列表；保留表格数量的序列化转换以及列／样例的列表副本，退出字段存在性与列表缺失兜底。治理原因和命中统计由固定工厂构造为字典，按原顺序展示和记录，不再猜测容器类型。

文本评分的 content_chars 来自 len，解析总分来自原评分器的浮点 round 结果，消费者直接保留这些值。门槛仍在原入口以 int／float 与 max 解析，不再在后续 metadata 记录中再次转换同一局部值。恢复模块直接读取已声明 Settings 字段和已通过查无记录检查的完整 Document；动态设置名称、原始 JSON、错误／取消时可能缺失的文档、可选统计及路由结果仍保留各自边界。
- 把同类 JSON／标量转换全部收敛成一个 helper 可以减少重复，但各入口的布尔、NaN、异常、缺省与可选协议不同，会改变失败语义。因此不合并这些原始边界。

## Consequences

十八个 pending owner 的完整源审查覆盖 9279 行；十个 owner 调整，八个保留原文。五个新函数替代五个无状态类，十六个方法原体按显式参数／名称映射迁移，不留下兼容 wrapper。调用方和旧符号引用同批更新。

源码验证使用 Python 3.11 AST、全部模块规范化比较、明确表达式清单、生产者字段／调用方核对、Ruff 和格式检查。AST 工具只导入标准库并读取源码，不导入或执行 app、解析器、SDK、模型、数据库、服务或 Python 测试。该证据不能替代运行时解析、真实子进程／文件／图像或事务验收，也不声称执行过这些路径。

声明字段读取增量的证据位于 E:/MimirQ/.superpowers/pipeline-declared-fields-20261107/。三个完整模块 AST 只包含指定字段读取变化；两个数据类、真实构造器、输入变量绑定、签名、装饰器、SQL 与值转换均有静态核对。Ruff、格式和笔记门禁完成，Python 测试源码保持且不执行；自动模型审查仍因本机缺少 TruffleHog 无法启动。

ORM 字段增量与 API、连接器、文档服务及检索候选的同类读取一起记录在 record-declared-fields-20261107 源码核对材料中。45 个批准表达式之外的完整模块 AST 保持，五个真实可空对象保护单列为保留项；既有工作区改动按开始快照保留。验证仍限于源码、Ruff、格式、语法与记录门禁，未执行 Python 测试或业务函数。

活跃笔记检索命中相邻的[文档批次 ORM 契约](2026-11-03-document-batch-orm-contract.md)、[共享标量转换](2026-11-03-shared-scalar-coercion-owner.md)和[预览结果所有权](2026-11-05-preview-owned-values.md)。本记录沿用实际 ORM 与内部结果的边界原则，但保留本管线各自既有的原始转换和失败策略，没有替代或修改这些决定。两处已完成的 package initializer 与 flow owner 不再次计入完整审查。

解析结果消费端的增量证据位于 `E:/MimirQ/.superpowers/parsing-record-consumers-20261107/`。两个完整模块仅接受逐表达式字段读取和已证明局部值的变更；实际表格导入、路由、评分、治理统计、配置构造器与调用者源码保存哈希。配置数字转换、表格列表副本、质量门禁严格／降级、重试、隔离、事务、取消和清理保持。Python 3.11、Ruff、格式及笔记校验是静态证据，未运行或修改 Python 测试，也未执行应用、SDK、模型、数据库或服务。

预处理与 checkpoint 记录增量的源码证据位于 `E:/MimirQ/.superpowers/preprocess-checkpoint-records-20261107/`，保存两个预处理结果的全部返回路径、实际索引选项工厂、完整 ORM 查询、已安装 Document SDK 声明、解析生产者与既有测试源码。完整当前／提交源码只包含批准的规则复用、真实字段和已归一化字典读取。Ruff、格式、Python 3.11 与笔记门禁提供静态证据；未运行或修改 Python 测试，未执行预处理、解析、SDK、业务文件操作、模型或数据库。
