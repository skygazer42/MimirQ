# Agent Note: 解析管线的普通函数与结果边界

Status: implemented

## Problem

归一化、治理、切块、精确去重和索引五个阶段没有实例状态，却通过 class、factory() 和 run() 逐层传递。读入库主流程时需要跨过没有生命周期职责的对象，才能看到实际输入和结果；切块与去重的内部函数也依赖无用途的 self／cls 参数。

同一管线已经有明确的 InlineAssetResult、ChunkPostprocessStats、GovernanceStats、MarkdownCanonicalizeResult、ParsingError 和 ORM 字段，但消费端又把必需字段当作可能不存在，并重复转换本地计数、已解析分数或哈希字符串。与此同时，缓存、子进程返回、页面元数据和图像后端仍是原始或可选边界，不能与这些内部结果混为一谈。

## Decision

五个无状态阶段在原模块内使用普通函数：govern_documents、normalize_documents、chunk_documents、deduplicate_chunks 与 index_chunks。切块和去重的辅助函数仍与其入口同处 stages.py；不新增模块、统一 stage context 或一次性转发对象。函数入口先于各自细节，原参数、结果及内部执行顺序保持。

DocumentProcessorService 继续持有处理入口和现有依赖接口。ParsingStage、InlineAssetStage 与 ChunkAssetStage 仍接收 service，保留解析取消、产物目录、图像上传与 SDK 清理行为。它们通过 type-only 引用声明实际 processor 依赖，避免循环导入；图像后端在原位置加载，外部图像对象继续保留实际协议处理。

真实 flow 调用方直接接收和调用五个函数，不再构造对应阶段。这个已独立审查的模块只迁移必要的参数、类型与调用点，不作为本批完整 owner 再计完成。旧 test import、已有调用与 monkeypatch 目标同步到新符号；没有增加、扩写或执行测试用例、断言或 helper。

已构造的计数、分数、哈希与真实结果字段直接使用。InlineAssetResult 中仍可空的 audit 必须经过原 dict 判断，metadata 写入仍按原规则复制；字段表只引用该结果中真实声明的属性。DBDocument 的逻辑来源读取声明实际 ORM 类型，doc_metadata 的原始字典规则、源路径优先级与空文件名回退仍保留。

图像代码处理固定启用，因此 InlineAssetStage 中依赖 not image_code_enabled 的提前返回不可达，直接退出该死分支；其余开关仍按原顺序计算，图像代码、公式、图表、标题和上传仍按原顺序执行。

本批保留本地缓存反序列化与过期清理、质量门禁 JSON 序列化、预览解析入口、重试／checkpoint 恢复、路由选择、worker 协议和常量模块的原始边界。asyncio Process 与 Popen 两种进程、进程组信号、等待、超时、取消、日志／结果限额以及错误分类没有统一成新抽象。解析输出的顺序、metadata 名称、缓存键、租户／路径／ACL、事务和事件保持。

## Alternatives considered

- 保留五个 class 可以沿用 factory 形式，但它们没有独立状态或资源，调用者仍要维护构造和 run 两套协议。因此只退出这些壳，保留实际有 service 能力的阶段。
- 把所有阶段移到新模块或再建通用 manager，能统一接口，却增加维护位置并隐藏现有差异。因此函数留在实际业务 owner，并显式迁移真实调用方。
- 保留所有 int／float／getattr 默认写法可以兼容任意不符合内部类型的替身，但会把已保证的字段和原始输入边界混在一起。因此只简化有生产者依据的内部结果；原始数据、可选字段和 SDK 保护继续存在。
- 重写整个 process_document_flow 能进一步整理流程，但该 owner 已独立完成审查，当前只需要阶段接口迁移。因此不改其预算、fallback、事务、取消或元数据逻辑，也不重新归入完整范围。
- 把同类 JSON／标量转换全部收敛成一个 helper 可以减少重复，但各入口的布尔、NaN、异常、缺省与可选协议不同，会改变失败语义。因此不合并这些原始边界。

## Consequences

十八个 pending owner 的完整源审查覆盖 9279 行；十个 owner 调整，八个保留原文。五个新函数替代五个无状态类，十六个方法原体按显式参数／名称映射迁移，不留下兼容 wrapper。调用方和旧符号引用同批更新。

源码验证使用 Python 3.11 AST、全部模块规范化比较、明确表达式清单、生产者字段／调用方核对、Ruff 和格式检查。AST 工具只导入标准库并读取源码，不导入或执行 app、解析器、SDK、模型、数据库、服务或 Python 测试。该证据不能替代运行时解析、真实子进程／文件／图像或事务验收，也不声称执行过这些路径。

活跃笔记检索命中相邻的[文档批次 ORM 契约](2026-11-03-document-batch-orm-contract.md)、[共享标量转换](2026-11-03-shared-scalar-coercion-owner.md)和[预览结果所有权](2026-11-05-preview-owned-values.md)。本记录沿用实际 ORM 与内部结果的边界原则，但保留本管线各自既有的原始转换和失败策略，没有替代或修改这些决定。两处已完成的 package initializer 与 flow owner 不再次计入完整审查。
