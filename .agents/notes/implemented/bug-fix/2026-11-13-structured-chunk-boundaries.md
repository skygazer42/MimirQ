# Agent Note: 结构化分块正确处理行边界和终点

Status: implemented

## Problem

八个 whole-item 窗口器已经输出包含全部剩余记录的终块，却继续按 overlap 退回，重复输出完全被终块包含的尾块。HCL 的字符类把双转义 n 当成字母与反斜杠，正常的 region 标签无法按预期识别。

Compose、GitHub Actions 和 OpenAPI 的 anchor 用 `\s*` 捕获缩进，普通空行也被计入 indent，导致有效子块退成全文 fallback。POM 按 start 排序的记录可以嵌套；已计入外 plugin 的窗口却用最后一个内 dependency 的 end 截断，丢失外记录剩余配置。

## Decision

八个窗口器发块后，当 end_idx 等于实际记录数量时结束当前文档。非终端的 whole-item 重叠、0／字符串0、超长单项及全部构造参数解释保持。保留块的内容、span、ID和 metadata 保持；删除冗余尾块后，多文档 chunk_index 按现有规则连续重排。不抽取通用窗口框架。

HCL 只把字符类中的双转义改成真正 newline 边界，不排除正常字母 n，也不扩展新的 HCL grammar。三个 YAML anchor 的 indent 只捕获水平空白，保原关键字、层级和内容解析。

POM 的窗口预算、输出终点和字符 overlap 距离都使用当前记录组覆盖的最大 end。记录种类、计数、排序、原文切片及最少单项策略保持，不增加 XML parser；单调 end 的普通记录行为保持。

JSON／Code／SmartCode 沿用三套有实际状态的类及公开构造参数。JSONDecodeError 只在实际 json.loads 处转换为原 fallback，解码之后的内部同名错误继续传播；SmartCode 直接读取实际 Code 生产者每个块必有的两个 int 偏移，不用猜测缺失值。原始 language metadata 的 None／False／0 保持，两个私有类型注解如实使用 Any，不新增归一化或 Pydantic 包装。

本篇补充[既有结构化边界](2026-11-05-structured-chunk-owner-contracts.md)的具体缺陷修复，不改变原始 SDK、构造参数和不同格式的合同。[公共行切片](../simplification/2026-11-08-chunker-source-lines.md)继续持有 span／plain 规则，业务模块直接复用实际所有者。

## Alternatives considered

- 在最后追加全局去重可以隐藏重复尾块，但会误删有意重叠或相同正文的不同记录；终点判断直接修正错误的下一步。
- 统一所有格式为全文覆盖可以保留更多前缀和尾文，但服务／job、记录、补充信息等边界各有实际策略，本次不统一。
- 为 HCL／YAML／POM 更换完整 parser 可以处理更多语法，但超出已确认缺陷；只修实际转义、indent 和覆盖终点。

## Consequences

重复终块减少，正常含 n 的 HCL 标签、空行前的 YAML anchor 及嵌套 POM plugin 正确保留既定结构。这些属于明确记录的检索输入变化，不能宣称所有运行输出逐字不变。

CSV 的合成前缀虽然省略，原始 header／cell 与 source／delimiter／columns metadata 仍完整，维持原策略。Docker／Make 全局前缀、Compose／GHA 尾域、OpenAPI 根路径和文本策略的局部覆盖按原范围保留；stacktrace 的 Java／Node 已知标签决定不变，不创造统一 grammar 或全覆盖承诺。

原始失败 proof 保留，有限 AST／FakeDoc／假 SDK 验证覆盖原故障、修正及普通输入回归，再跨作者独立核对最终 SHA。JSON8／Code7／Smart5 原后有效数据对照相同，独立注入确认内部 JSONDecodeError 传播变化。没有运行 Python 应用测试、真实 parser／SDK／模型／网络或数据库，不能由此证明实际分块质量或服务运行通过。
