# Agent Note: 上下文处理保留实际空结果

Status: implemented

## Problem

图流程的去噪、两种压缩和排序适配器用 `result or list(docs)` 处理 stage 结果。真实去噪和压缩 owner 会过滤空内容并返回空列表；适配器却把被过滤的原文档重新放回上下文，撤销了已成功执行的清理。流式入口直接保留去噪结果，两条路径语义不一致。

## Decision

四个适配器直接返回 owner 已生成的列表，包括空列表。`_prepare_context_docs` 继续按原开关和顺序执行，`_build_context` 沿用无可用文档时的原空文本返回。

异常和有效空结果各按既有责任处理：stage 抛错时仍走原日志与原文档降级分支，LLM 压缩的失败或空回答仍由其 owner 保留原文本；stage 成功返回空列表时不补回文档。真实过滤、metadata／ID 保留、去重、token 预算、引用列表与检索结果本身保持。

## Alternatives considered

- 保留 `or list(docs)` 可以保证输入非空时上下文也非空，但这会恢复 owner 已判定没有有效文本的内容，混淆执行失败与成功的零结果。
- 同时删除所有 stage 的异常降级可以让代码更短，但可选压缩已有失败后使用原文档的契约；本次只纠正成功结果被替换的问题。

## Consequences

清理后无有效内容时提示词上下文为空，不再悄悄恢复空白或 boilerplate 文本。检索引用仍按原路径返回，空上下文不等于重写检索结果或自动宣称没有证据。

验证核对四个真实 owner、流式消费者和图状态／上下文构造源码。完整模块 AST 对照仅允许四个返回表达式去掉真值回退；限定 Ruff check/format、Python 3.11 AST／编译及 Note 门禁通过。依用户要求不新增或运行 Python 测试，未执行去噪、压缩、提示词、模型或检索运行时。
