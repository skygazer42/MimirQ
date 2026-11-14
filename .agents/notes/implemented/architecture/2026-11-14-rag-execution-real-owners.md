# Agent Note: RAG执行直接依赖实际所有者

Status: implemented

## Problem

单智能体与并行智能体复制同一状态字段映射，单分支漏传已有request_id。旧tools.py被同名普通包遮蔽，prebuilt facade、两个未挂载服务工厂及三个scanner助手没有实际业务消费者；保留这些入口会使调用关系与真正执行路径混淆。

流式执行的初次与重试分支又复制同一个RRF融合实现，旧查询初始化函数已不在真实operations列表，只有冻结测试仍调用。

## Decision

两个智能体使用rag_agent中的build_agentic_rag_state模块函数，具名传递真实request与history，不新增文件或Context。原覆盖优先级、raw legacy参数和零值规则保持；单分支补传既有request_id，并行映射保持原语义。实际engine、request／结果记录、模型／registry／缓存／锁继续由有状态对象持有。

[流式依赖所有者](2026-11-14-stream-dependency-owners.md)进一步删除整engine模块透传，并以实际Graph／Request字段声明替代过期白名单；合法score阈值0不再被legacy默认替换。本篇原核心scope／资源／退休原则继续成立，其余legacy缺省不借此统一改写。

两个完整同体的融合实现归现有doc_utils.fuse_doc_lists，调用方显式传入同一fuse_docs_rrf和rrf_k，保原运算序、排序／tie和metadata复制。阶段调度、输入范围和异步边界不合并。

旧tools.py、prebuilt facade、未挂载MCP server／dashboard以及simple KB／三个无业务scanner助手退出，共八文件；包imports和exports同步清理。真实format／length／settings服务入口、simhash冻结测试和底层PII／secrets／PDF实现保持。旧工具的run_path schema测试、prebuilt适配器测试以及旧查询初始化函数的测试引用明确登记为冻结例外，不称全仓无人引用，不留生产兼容壳。

官方当前LangChain-core全局配置由自己的模块字段和getter持有，普通agents包不再给旧langchain命名空间补debug／verbose／llm_cache。真实ReAct与框架类从实际所有者导入，没有把旧facade重新接入。

检索准备继续使用现有 QueryPlan、RuntimeState、runner 和实际阶段列表。旧 support_contracts 实现及两个旧包装没有真正调度调用，闭包一起退出；只清理无根的旧分解包装和专属导入，活跃的查询分解、模型选择和阶段不删。插件策略复用其既有实际所有者，同签名内部转发改为实际函数绑定，没有新增 Context 或整个模块的 Any 透传。

KG 的 agentic_beam_search、drift_search、lazy_indexer、pprank、snapshot_router，以及独立 plaid 编解码器没有应用、脚本、配置或动态注册调用，整模块退出。plaid 有真实算法，不以 stub 为删除理由；实际 ranking/pagerank、ColBERT 索引、method_router 标签和查询字段保持。自身 __all__ 只是声明，冻结测试的直接导入真实列在证据中，不宣称全仓零引用。

跟进查询的[词数预算修复](../bug-fix/2026-11-14-followup-term-budget.md)独立持有行为决定，原排序、状态和资源所有权不因此改变。

旧 memory 包只有 summarize_messages 被真实会话摘要服务使用。该能力迁到现有 conversation_summary_service 私有函数，直接使用其 SQL 读取器已构造的 role／content 字典；实际 BaseLanguageModel 包括返回消息的聊天模型和返回文本的开发模型，两种形式都保留。原提示词、截断、提供方失败策略和异步取消身份保持，数据库读取、持久化与 Session 所有者的其余 AST 不变，日志名称归到实际服务。

没有应用／脚本／配置注册消费者的长期记忆实现、消息裁剪管理器和中间件与旧 memory 三个模块退出，未删除持久文件或配置。实际 PostgreSQL 会话摘要、结构化记忆与原生 SDK store 不是这些闲置实现，没有因同名一并删。Tracing 保留启动与 LangGraph 两个真实消费者所用的类、普通包和同步 trace，退出无调用装饰器和便利接口；[失败与取消处理](../bug-fix/2026-11-14-tracing-failure-isolation.md)单独记录。

旧 `agent.py` 转发器、`graph.py` 重导出，以及没有应用／脚本／配置注册消费者的 `output` 和 `retrievers` 五条路径退出。后两者包含真实实现，删除理由是未接入当前执行图；实际 agentic runner、LLM structured_output、层级召回与父子检索继续由原所有者持有。当前文档直接指向这些所有者，不为冻结测试或未知仓外调用保留旧壳。

HybridRetriever 保留框架状态、缓存与必要的 Mixin，退出五个没有实际消费者的文本准备转发方法；CorpusIndex 和候选排名继续调用真实 text_preparation。数据库单列行与完整数据集映射使用已经成立的读取合同，元数据 JSON、租户范围和无可用数据集仍在原边界校验。元数据补全只调用已声明的新签名，不再根据 TypeError 文本剥掉过滤条件重试。原始检索参数、排序、预算和真实降级保持。

LangGraph 状态入口直接用已有 RagStateBuildOptions 接收真实调用者的具名字段，退出没有消费者的可空 options 适配与长位置参数映射；执行参数 thread_id／runtime_context 仍显式独立。Functional 装饰器直接取现有工厂持有的 checkpointer，不再维护第二个同义单例。图的两种执行方式、checkpoint、重试和纠正预算保持；空缓存结果仍是命中，真实租约、超时、加密和可选 Redis 失败策略不改变。

## Alternatives considered

- 保留重复映射可以少改调用方，但字段已经出现request_id差异，两个实际消费者使用同一函数可消除维护分叉。
- 新增执行Context／通用manager能统一更多步骤，却隐藏当前明确的状态与函数依赖，因此沿用现有模块。
- 给没有挂载的服务补鉴权并接入口可以保代码，但会新增产品能力；完整图确认没有实际消费者后退出。

## Consequences

执行路径更直接，真实框架状态和公开业务接口保持。退休的旧私有路径和便利接口不再可用，冻结测试需要后续维护；删除路径不计作现存完成数。main的关闭回调只算既有完成文件增量，engine的流关闭只算必要partial，不能据此宣称整个engine已复核。

完整源码／定义／调用图、实际SDK声明、资源常量和限定假端口验证支持这些改动；提示词值、六种workflow模式和十五个别名保持。没有运行实际模型、工具、scanner、SDK、网络、数据库或Python应用测试，未据静态检查宣称真实执行质量通过。
