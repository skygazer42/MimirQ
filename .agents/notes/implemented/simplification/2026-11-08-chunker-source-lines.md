# Agent Note: 结构化 chunker 共享源码行切片

Status: implemented

## Problem

十三个结构化文本 chunker 各自声明相同的冻结 `_Line` 数据类，并复制相同的 `_iter_lines` 偏移计算函数。字段、换行处理、空文本处理和返回顺序的 AST 完全一致；任何偏移规则修改都需要同步十三份实现。

Markdown table 的本地记录保存原始行文本，但三处读取都会去除行尾 CR/LF，最终内容仍从原文本按偏移切片；这份记录与遍历副本也没有独立的业务职责。

## Decision

`app.rag.chunking.utils.source_lines` 持有无外部依赖的 `SourceLine` 和 `iter_source_lines`。已迁移的结构化策略具名导入实际记录与遍历函数，按各自原始读取方式使用 `plain`，保持起止字符位置及原片段。KV／TOML／YAML、Subtitle 与文本格式的调用方采用同一合同；没有为了复用把各格式的识别和 metadata 合并规则统一。

Markdown table 也使用同一 `SourceLine` 和 `iter_source_lines`，把三处 `raw.rstrip("\r\n")` 读取映射为 `plain`，原始内容仍按 `text[start:end]` 获取，不改变表格识别、片段或 offset。

`app.rag.chunking.utils.heading_parsing` 同时持有同体的 heading stack 更新规则。已迁移策略具名导入同一函数，Markdown outline 只归一参数名后复用；标题识别、section 构造与 metadata 继续由各自模块负责。Markdown hierarchy 的补空层级／max6规则不同，保留自身实现。

共享函数继续按原顺序计算每行的起止字符偏移，保留换行字符在 `end` 中的计数，并把 `plain` 限定为去除行尾 `CR/LF` 的文本。空字符串返回空列表；非空原生字符串的 splitlines 必定产生行，原不可达单行回退退出。

## Alternatives considered

- 保留每个策略的本地副本可避免新增导入，但十三份完全相同实现已经形成真实同步成本，且没有领域差异需要独立演进。
- 建立通用 chunker 基类可以进一步共享分块流程，但各策略的 section 识别、metadata 和 fallback splitter 不同；本次只抽取已证明完全同体的叶子规则。

## Consequences

源码行偏移规则只有一个维护位置，多个策略减少重复类和函数。`SourceLine` 的运行时类名与旧私有 `_Line` 不同，但这些对象没有外部或公开消费者；字段、冻结行为、相等性和策略内部访问保持。[分块公共规则所有者](../architecture/2026-11-13-chunking-shared-rule-owners.md)说明相邻的真实公共规则共享与无根副本退出，不建立通用分派基类。[终点和行边界修复](../bug-fix/2026-11-13-structured-chunk-boundaries.md)保本篇公共 span 合同，只修独立的转义／缩进／覆盖终点及终端窗口缺陷。

验证比较十三份旧类／函数 AST、共享实现的代表输入输出、各模块导入与调用绑定；Markdown table 另核三处读取映射后的完整 AST、六种 LF／CRLF／尾换行／空文本等输入与原生 Document／假 splitter 输出，独立复核确认原片段和偏移保持。Ruff、格式和笔记门禁按各批记录核对。按用户要求不运行 Python 应用测试、解析服务或真实文档回归。
