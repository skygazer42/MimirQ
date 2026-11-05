# Agent Note: Dify 生成代码中的 JSON 配置值

Status: implemented

## Problem

Dify workflow 的 HTTP JSON 模板改写为 Python Code 节点时，检索配置先经 `json.dumps` 序列化，再直接拼进 Python 赋值。现有 API schema 接受 `enable_kg_query_expansion` 的布尔值和 `latency_profile` 的空值，JSON 的 `true`、`false`、`null` 却会成为生成模块中的未绑定名称。节点加载会在进入 `main` 前失败；本地改写只写入代码字符串，不能据此证明节点能够运行。

## Decision

`scripts/changzhou_gov_dify_workflow_lint.py` 保留原检索配置的 JSON 序列化选项，在既有 f-string 中用 `!r` 引用这份 JSON 字符串，并由生成代码已经导入的 `json.loads` 还原配置。赋值表达式接收字符串常量，解码后保留布尔、空值、数字、字符串、键顺序和转义内容。

修复只改变 `_RETRIEVAL_SETTING` 的生成表达式。当前元数据默认值的具体生产者把每个字段构造为字符串，其原插值保持；应用与知识库 ID、HTTP 调用、图节点与边、元数据、变量选择、预算、返回字段、排序和错误路径沿用原实现。

## Alternatives considered

直接对整个配置字典使用 `repr` 可以得到 Python 字面量并省去解码，但会退出已有 `json.dumps` 的序列化与失败边界。引用已生成的 JSON 字符串可保留当前数据协议。

手工替换 `true`、`false`、`null` 看起来改动较小，但这些词也可能出现在字符串值和键中；正确处理需要额外的词法规则。现有 JSON 解码器已经持有这条规则。

## Consequences

已有合法布尔与可空配置能够表示为生成模块的数据。节点模块加载时增加一次标准 JSON 解码，不增加导入、依赖、兼容分支、异常吞咽或默认成功结果。后续若元数据默认值的生产者开始返回其他 JSON 类型，需要按其实际契约单独核对生成方式。

原模板和七组输入在修复前冻结。静态证明覆盖 `true`、`false`、`null`、有限数字、转义 Unicode 和原正常控制：旧赋值的四组输入出现未绑定名称，三组控制保持原字面量 AST；新赋值均为 `json.loads(Constant[str])`，其参数由标准库 JSON 解码后与原序列化数据的类型、值、顺序和转义一致。外层完整模块 AST 只允许这一处明确模板投影，签名、序列化调用、已有导入和元数据插值保持。

验证只使用固定源码、AST、哈希、标准库 JSON、Ruff 与笔记门禁。不新增、扩写或执行 Python 测试，不执行原生成器、生成模块或业务函数、CLI、SDK、模型、数据库、业务正则、回调或真实网络。静态证据不表示已完成 Dify 服务运行验收。

活跃笔记按生成器、检索配置与代码节点检索，没有相同决定。[本地命令入口的参数与退出状态](2026-11-05-local-cli-input-and-exit-contracts.md)同样记录程序与 JSON 数据边界，但涉及不同入口；[Dify 纯规则归属](../simplification/2026-11-04-dify-helper-ownership.md)持有后端辅助规则与初始化合同。本篇不替代或修改这些决定；源路径和 workflow 状态类型记录与本缺陷无关。
