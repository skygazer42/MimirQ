# Agent Note: 标准流查询计划的诊断投影

Status: implemented

## Problem

标准流从完整查询计划写入 `decompose_enabled`，trace 和完成事件仍读取没有赋值来源的旧 `dq_enabled`。非拒答流程构造这些诊断时会访问不存在的状态。配置指纹还读取没有投影的 step-back 温度和长度字段，已有异常入口将这种缺字段错误转成缺失的指纹。

## Decision

trace 与完成事件读取现有 `decompose_enabled`。`prepare_query_plan` 直接投影 `plan.model_settings.step_back` 的 temperature、max_chars 和 output_max_chars，沿用同步 orchestrator 已有的数据来源。事件键、事件顺序、模型调用、检索与预算代码不变。

此保证来自实际构造链：`resolve_model_query_settings` 无条件构造 step-back 的 `TextQuerySettings`，包括禁用状态；`complete_query_plan_async` 通过 `_complete_query_plan` 将该设置放入必需的 `QueryPlan.model_settings`。禁用或长度为 0 时，模型扩展返回未运行的 outcome，配置对象仍存在。三个投影直接复制字段，不增加 `or` 默认或可空回退，有效的 0 保留。

标准流继续使用现有 `StandardStreamState`、Engine 模块回调与 `locals().copy()` 输入捕获。六组共 42 个有序操作、async generator 的关闭、信号量、admission timeout、会话释放、异常入口和请求状态生命周期保留。LangGraph 的既有再导出与 canonical 实现不迁移。

Settings 与 ChatRAGConfig 的已声明字段直接读取；旧参数与 `model_copy(update=...)` 的原始值解析、范围限制和异常默认仍保留。`len` 已生成的计数直接传递，SDK、LLM、工具、元数据、模板版本与注入回调的原始边界不收窄。

四个未接入操作表的旧 KG 私有函数经全库代码、注册、动态字符串和文档扫描后删除；扫描只命中定义。已有回归测试直接调用的 `expand_aliases_dictionary_and_init_kg` 继续保留其 Engine 模块钩子，不修改测试逻辑，也不增加兼容转发器。

## Alternatives considered

给缺字段增加默认值可以让诊断继续构造，但会让启用状态或 step-back 配置与真实查询计划不一致，并把有效的 0 与缺值混在一起。因此从现有生产者直接投影。

给运行状态另建通用 Context 或管理器可以集中声明字段，但会扩大请求与阶段迁移范围。当前状态类承担真实请求内生命周期，只修复缺失连接。

保留四个无引用的 KG 私有函数可避免删除符号，但会继续留下第二套未接入的查询扩展实现；引用与注册扫描没有发现契约。对已有直接测试调用的旧钩子则保留原约定。

## Consequences

`decompose_enabled` 的 trace 和完成指标现在反映查询计划。检索配置指纹可以使用真实 step-back 设置；这两个诊断值恢复正确是有意行为修复。事件 schema、排序、预算、租户与 ACL、模型选择、缓存键构造和同步/异步边界保持。

历史审计中，[查询准备所有者](../architecture/2026-11-03-query-preparation-owner.md)与本次缺失投影部分重叠，[Engine 查询与模型端口](../simplification/2026-11-05-engine-ports-owned-values.md)与可变配置边界部分重叠；两篇决定保持并互链。[LLM 消息转换](../simplification/2026-11-04-llm-message-content-owner.md)的内容协议和客户端生命周期不受本次改动影响。前端流、请求状态与 parser 笔记属于其他链路，没有被替代。

## Verification

12 个 Engine、graph、SLI 与标准流所有者的 4,739 行基线和 118 个函数完整审阅。静态证据对照必需 schema、实际 return 构造、禁用路径、同步投影、字段写入与读取、注册表和四个函数的全库引用；4 个退休函数之外的参数、默认值与装饰器保留。Ruff、格式、Python 3.11 AST、diff 与笔记门禁覆盖本批。按任务限制不添加、修改或运行 Python 测试，不导入或执行应用、SDK、stream、模型、检索、数据库、网络、服务或 fixture。
