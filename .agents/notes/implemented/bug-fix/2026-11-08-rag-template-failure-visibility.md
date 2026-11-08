# Agent Note: RAG 配置准备失败直接传播

Status: implemented

## Problem

聊天和检索预览的模板准备函数捕获所有异常，再返回空模板信息。数据库查询失败、补丁校验失败或内部字段错误因此被表示为未匹配模板；预览还可能已经应用补丁，却清空记录本次补丁的诊断信息。聊天的选择器判断另用嵌套条件表达式和单次海象变量重复表达普通逻辑或，增加阅读成本。

数据集默认配置读取也在整个查询和合并流程外捕获所有异常。一次数据库或配置合并故障会被表示为没有数据集默认值，提示词与模板继承因此一起丢失。

迭代检索又在执行前把非法 Settings 转换成关闭功能，并把缺失或错误的内部 `top_k` 归零。调用方无法区分正常关闭与配置／状态损坏。

提示词预览与 LangGraph 生成链在所选模板解析失败后静默改用引擎默认模板，响应中的模板来源因此可能与实际使用内容不一致。提示词 schema 允许空字符串，但消费者以真值判断再次把它解释为没有选择模板。

## Decision

`chat_bootstrap_runtime._resolve_rag_template_runtime` 和 `rag._resolve_preview_rag_template_meta` 按原顺序解析模板、应用补丁、构造来源信息和记录使用次数。模板查询、补丁校验及内部读取错误直接交给现有请求错误入口，不再转换成无模板的成功结果。

未提供有效选择器时仍不查询；resolver 实际返回无匹配记录时仍保留现有无模板结果。选择器的优先级与空白处理不变，聊天使用与预览相同的普通逻辑或。模板使用次数仍由已有 `record_rag_config_template_usage` 处理：计数失败 rollback、warning，成功 rollback 后继续使用已经选择的配置。

计数 owner 在写入前保存已经加载的模板 ID。SQLAlchemy rollback 会过期 ORM 实体属性，异常日志只使用这个 ID，不在计数失败之后再次读取 `template.id` 并触发数据库加载；rollback 本身失败仍向上传播。

聊天和预览的数据集默认配置准备函数同样直接传播查询和合并错误。实际无共同数据集仍返回未应用默认值；原始 metadata 的存在性和字典校验由 `load_dataset_metadata` 持有，消费端不再重复猜测它的返回类型。原始 `rag_defaults` 的 schema 解析继续由现有合并模块处理，本次不重定义历史 JSON 的准入规则。

提示词预览与 `_build_generation_chain` 仅在内容为 `None` 时使用引擎默认模板；已选择的空字符串也直接进入 `ChatPromptTemplate.from_template`。预览把模板解析纳入已有的渲染错误入口，使用原有 `400 / Prompt render failed` 响应；生成链把解析错误交给既有调用方，不再使用另一份模板继续。两处都直接消费 schema/状态字段中的文本，不用 `str` 掩盖错误类型。

迭代检索直接读取声明为 bool/int 的配置，次数仍按原规则至少为一。备用状态直接读取实际 `build_rag_state` 产生且经 profile 处理的整数 `top_k`，缺字段或非法值不能伪装成零预算；20／50／80 候选下限与初次结果选择规则保持。相关性分数属于原始检索 metrics，标准数值转换失败仍按原规则返回零，只捕获 TypeError、ValueError 和 OverflowError。

本决定接续[聊天运行时类型契约](../simplification/2026-11-03-chat-runtime-typed-contracts.md)和[模型退出边界](../architecture/2026-11-05-retire-in-process-models.md)。前者的实际模型字段和 analytics 归属、后者的最终模型选择校验继续有效；这里把其他真实模板解析错误也交还调用方。

## Alternatives considered

- 保留捕获并加 warning 能增加可观测性，但请求仍可能采用另一份配置或丢掉已应用补丁的来源，不能把配置解析错误解释成模板未匹配。
- 同时删除无选择器、查无记录和 analytics 的可选分支可以进一步缩短函数，但这三类都有现行契约；它们与模板解析失败的含义不同。

## Consequences

调用方可区分查无模板和解析失败，错误不会再产生缺少模板来源的成功响应。代价是以前静默采用默认配置的请求现在会失败，需要修复存储补丁或数据库问题后重试。没有新增异常包装、重试、配置开关或兼容实现，正常请求的参数、查询范围、返回形状和补丁优先级保持。

验证使用现有 Python 3.12 环境的 Ruff check/format、Python 3.11 AST 解析、源码编译及完整模块结构对照。模板增量仅允许两个外层异常包装退出和聊天选择器条件替换；数据集默认值增量仅允许两个外层异常包装、无引用的异常导入退出和两处已保证字典的读取简化。各增量其余模块 AST 相同。按用户要求未新增或运行 Python 测试，未执行真实请求或数据库故障注入，静态结果不代表运行时回归已验证。

日志增量同时核对已安装 SQLAlchemy 的 `Session.rollback` 和 `SessionTransaction._restore_snapshot` 源码，确认 rollback 遍历 identity map 并过期实体状态；仅调整日志标识的读取时机，未执行 Session 或数据库故障模拟。

提示词增量核对 `PromptTemplateBase.content`、`RAGState.prompt_template_content`、真实状态生产者与 LangChain 模板构造器。静态核对仅调整模板选择条件、删除静默替换并将预览解析移入原 400 边界；成功路径的渲染计时仍从模板构造完成后开始，未执行提示词、检索或模型调用。
