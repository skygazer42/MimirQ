# Agent Note: 结构化 chunker 共享源码行切片

Status: implemented

## Problem

十三个结构化文本 chunker 各自声明相同的冻结 `_Line` 数据类，并复制相同的 `_iter_lines` 偏移计算函数。字段、换行处理、空文本处理和返回顺序的 AST 完全一致；任何偏移规则修改都需要同步十三份实现。

## Decision

`app.rag.chunking.utils.source_lines` 持有无外部依赖的 `SourceLine` 和 `iter_source_lines`。Ansible、Dockerfile、Docker Compose、GitHub Actions、GitLab CI、Jira、JSONL、Makefile、Markdown frontmatter、OpenAPI、postmortem、PRD 和 stacktrace 策略将这两个公共符号别名为原私有名称，因此策略主体、类型使用和调用位置保持不变。

共享函数继续按原顺序计算每行的起止字符偏移，保留换行字符在 `end` 中的计数，并把 `plain` 限定为去除行尾 `CR/LF` 的文本。空字符串返回空列表；没有 splitlines 结果但文本非空时保留单行回退。

## Alternatives considered

- 保留每个策略的本地副本可避免新增导入，但十三份完全相同实现已经形成真实同步成本，且没有领域差异需要独立演进。
- 建立通用 chunker 基类可以进一步共享分块流程，但各策略的 section 识别、metadata 和 fallback splitter 不同；本次只抽取已证明完全同体的叶子规则。

## Consequences

源码行偏移规则只有一个维护位置，十三个策略减少重复类和函数。`SourceLine` 的运行时类名与旧私有 `_Line` 不同，但这些对象没有跨模块或公开消费者；字段、冻结行为、相等性和策略内部访问保持。

验证比较十三份旧类／函数 AST、共享实现的代表输入输出、各模块导入与调用绑定，并运行 Ruff、格式和笔记门禁。按用户要求不运行 Python 测试、解析服务或真实文档回归。
