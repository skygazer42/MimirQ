# Agent Note: 结构化记忆按真实换行分事实

Status: implemented

## Problem

开启结构化记忆后，消息持久化通过现有入口抽取用户事实。事实分句的 raw 字符串使用两个连续反斜杠，字符类因此匹配字面反斜杠和字母 n，而没有表达换行；它会错误拆开包含 n 的英文内容，并把不含句末标点的多行事实连在一起。

## Decision

`extract_fact_sentences` 仅把这一 raw 字符类中的双反斜杠改为单反斜杠的换行转义。原有句末标点、PII 过滤、长度、去重、数量上限、顺序、flags 和外部 schema 保持。该业务修复与后续等价风格整理分开提交。

同文件其余转义逐项核对：用户／助手拼接的分隔值已经是 U+000A，上下文前缀与 join 分隔也都是真实换行；它们保持原样。CJK、版本、邮箱、URL 与长数字的 raw 正则使用各自有意的单反斜杠语法，token strip 的 tab／CR／LF 也正确，不做全局替换。

## Alternatives considered

- 将整个正则改成普通字符串也能表达换行，但会混合 Python 和正则两层转义，扩大需要核对的表面。这里保留 raw 字符串，只修正错误的一个字面量。
- 统一替换文件中的反斜杠写法更省操作，但会损坏版本、PII 与 Unicode 范围规则，也可能误改已经正确的拼接和渲染，因此逐项按实际值判断。

## Consequences

事实拆分的输入仍来自受 enabled 和 STRUCTURED_MEMORY_ENABLED 门控的既有持久化链。新抽取结果可以按换行分开事实，英文 n 不再作为该字符类的分隔符；不会重写已保存的记忆，也不改变后续上下文构造规则。

使用 AST 字面量与码点证据核对唯一改动；完整模块其余 AST 节点及调用方保持一致。Ruff、格式与 Python 3.11 语法检查通过。本次不新增或运行 Python 测试，不编译或执行业务正则，不以源码证据声称运行时回归已完成。

活跃笔记按 structured_memory_service、extract_fact_sentences 和事实换行检索，没有同一决定需要吸收或归档。

同一完整文档类别中的资源所有权与原生值整理见[文档服务所有者](../simplification/2026-11-05-document-service-ownership.md)，它以本修复为基线，不改变这条分句规则。
