# Agent Note: 离线检索与 LTR 工具的规则归属

Status: implemented

## Problem

离线评估、训练、融合权重学习和策略生成脚本重复维护相同规则。相同名字之外还存在真实差异：导入脚本可能初始化应用包，case loader 的 dataset ID 类型并不统一，模型与模块工厂也有运行时职责。直接按注解删除转换或把所有 helper 集中到一个新模块，会掩盖这些边界。

## Decision

本篇 LTR 训练和评测所有者部分由[退出 XGBoost、unstructured 和腾讯云 SDK](2026-11-06-retire-parser-ml.md)取代：LTR 模块与 `eval_ltr_offline.py` 退出，保留的 pipeline 评测在自身脚本持有原有通用指标；其他 HTTP、trace 和策略规则归属继续适用。

五个 HTTP 工具直接导入 `scripts/retrieval_ablation.py` 现有的 JSON 读取、请求头和 case bundle 归一化规则，其中三个工具同时复用相同的 JSON 写入规则。替代定义的完整参数、默认值、异常和函数体一致，仅说明文字不同。这个所有者只导入标准库和 httpx，五个消费者本来都依赖 httpx。需要跨脚本导入的独立 CLI 在导入前按现有形式加入自身仓库根路径。

rerank 评估和训练脚本复用 `eval_ltr_offline.py` 的相同标量转换、reference ID 和对应指标或 pipeline hint 规则。两个消费者原本已经依赖同一 LTR 模块；新增导入不构造模型或客户端。两个不同的 citation 特征构造函数继续分别持有各自字段语义。adaptive policy 直接复用 channel policy 的 `_safe_float` 和 export intent 的 `_resolve_path_under_cwd`；这些所有者只有标准库依赖，路径边界仍在每次调用时按当前工作目录解析。

trace miner 继续持有自己的 JSON／case 规则，因为它没有 HTTP 依赖。已经关闭的 nightly 工具返回 UUID dataset ID，和这些字符串 ID 规则不同，继续保留。采集／回放脚本的独立规则归属见[诊断与回放脚本](2026-11-05-evidence-replay-cli-owned-values.md)，本篇只扩展离线检索与 LTR 工具的归属。

成功的 case 归一化路径产生原生字符串 ID 和新字典列表，后续切片保持这些类型；内部循环直接使用。完整本地统计、指标、预算和输出记录按构造者提供的键访问。原生计数、长度、enumerate 值、float 结果、文件行和正则完整匹配文本直接使用。意图模型的空输入摘要没有 `rules_total`，读取时继续保留该键的默认值；具有输出隔离意义的字典／列表复制继续保留。

整数到浮点数的除法操作数、log／round 顺序、零值和 NaN 处理、阈值、稳定排序、负样本上限和 hash 输入保持。原始 JSON、CLI、Settings、SDK、数据库和反馈边界继续执行原转换；有业务含义的布尔计数也继续转换。既有负样本容量约束见[按查询加载上限](../bug-fix/2026-11-05-hard-negative-per-query-load-cap.md)。

两个 importlib 工厂说明实际 `ModuleType` 返回值，工厂主体、加载时机和模块注册保持。手动激活 sentinel 说明 `Any` 参数及 `NoReturn`，继续立即抛出原异常。channel policy 的可选报告读取函数不捕获 CLI 局部状态，因此作为同模块普通函数持有原参数和完整函数体。四个有状态或资源职责的类、装饰器和模型工厂继续保留。

## Alternatives considered

采集入口已经持有相同的 JSON／case helper，直接复用能减少更多重复。不过 `app/__init__.py` 执行 LangChain 设置，evaluation 包初始化还导入评估器和 Ragas／benchmark 代码；把当前只有标准库和 httpx 的 ablation 入口接到该链会扩大初始化范围。因此 HTTP 工具选择现有 ablation 所有者，trace miner 保留独立规则。

新建通用 CLI 模块可以集中跨类别 helper，但会引入新的运行时所有者和迁移面。现有所有者已经提供完全相同的实现与足够小的依赖范围，因此直接导入即可。

根据类型注解统一删除所有兜底和转换会产生更短的代码，但原始输入、可变 Settings、SDK 返回和动态加载仍需要原边界。本次只简化有完整本地生产者证据的值；同名但语义不同的 nightly case、citation 特征和输入适配器分别保留。

## Consequences

二十四份 HTTP／LTR 重复定义及两份策略重复定义退出，规则沿用现有所有者。模块级函数从 229 个变为 204 个，四个真实类保持。脚本间出现明确依赖；以后移动所有者或给它增加顶层初始化时，需要同时核对独立 CLI 启动和消费者的依赖范围。

活跃笔记按十六个脚本名和 helper 检索后分类：诊断／回放笔记部分重叠，双方互链并各自保留归属；[评估质量内部规则](2026-11-05-evaluation-quality-native-rules.md)是相近原则但不同所有者；负样本加载上限是独立缺陷约束；`common.py` 的 shared scalar coercion 笔记针对不同参数与异常合同，保持原决定。没有完全吸收或需要归档的笔记。

验证读取全部 6,357 行原始所有者和最终 diff，以固定原始哈希、两阶段完整模块 AST 投影、选定调用的静态 `inspect.Signature.bind`、受保护边界、Ruff 和笔记门禁为依据。八份既有测试及两个已关闭 nightly 脚本保持原 Git blob。按本次任务约束，不新增、扩写或执行 Python 测试，不执行 CLI／help、应用、SDK、模型、HTTP、数据库、数据、业务正则或回调；静态证明覆盖源码与调用形状，运行时训练、检索和资源行为仍需在允许执行的环境另行验证。
