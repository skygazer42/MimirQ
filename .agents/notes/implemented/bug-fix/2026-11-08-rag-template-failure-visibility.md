# Agent Note: RAG 模板解析失败直接传播

Status: implemented

## Problem

聊天和检索预览的模板准备函数捕获所有异常，再返回空模板信息。数据库查询失败、补丁校验失败或内部字段错误因此被表示为未匹配模板；预览还可能已经应用补丁，却清空记录本次补丁的诊断信息。聊天的选择器判断另用嵌套条件表达式和单次海象变量重复表达普通逻辑或，增加阅读成本。

## Decision

`chat_bootstrap_runtime._resolve_rag_template_runtime` 和 `rag._resolve_preview_rag_template_meta` 按原顺序解析模板、应用补丁、构造来源信息和记录使用次数。模板查询、补丁校验及内部读取错误直接交给现有请求错误入口，不再转换成无模板的成功结果。

未提供有效选择器时仍不查询；resolver 实际返回无匹配记录时仍保留现有无模板结果。选择器的优先级与空白处理不变，聊天使用与预览相同的普通逻辑或。模板使用次数仍由已有 `record_rag_config_template_usage` 处理：计数失败 rollback、warning，成功 rollback 后继续使用已经选择的配置。

本决定接续[聊天运行时类型契约](../simplification/2026-11-03-chat-runtime-typed-contracts.md)和[模型退出边界](../architecture/2026-11-05-retire-in-process-models.md)。前者的实际模型字段和 analytics 归属、后者的最终模型选择校验继续有效；这里把其他真实模板解析错误也交还调用方。

## Alternatives considered

- 保留捕获并加 warning 能增加可观测性，但请求仍可能采用另一份配置或丢掉已应用补丁的来源，不能把配置解析错误解释成模板未匹配。
- 同时删除无选择器、查无记录和 analytics 的可选分支可以进一步缩短函数，但这三类都有现行契约；它们与模板解析失败的含义不同。

## Consequences

调用方可区分查无模板和解析失败，错误不会再产生缺少模板来源的成功响应。代价是以前静默采用默认配置的请求现在会失败，需要修复存储补丁或数据库问题后重试。没有新增异常包装、重试、配置开关或兼容实现，正常请求的参数、查询范围、返回形状和补丁优先级保持。

验证使用现有 Python 3.12 环境的 Ruff check/format、Python 3.11 AST 解析、源码编译及完整模块结构对照。结构对照仅允许两个外层异常包装退出和聊天选择器条件替换；其余模块 AST 相同。按用户要求未新增或运行 Python 测试，未执行真实请求或数据库故障注入，静态结果不代表运行时回归已验证。
