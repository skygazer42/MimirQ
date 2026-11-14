# Agent Note: 质量门禁结果由实际构造者持有

Status: implemented

## Problem

质量门禁只在 evaluate_parse_quality_gate 中构造 ParseQualityGateDecision，实际使用者也在同一模块；独立 schema 文件却再次猜测 grade、flags 和列表是否缺失，并递归把未知对象转成字符串。已有历史记录保留了这套宽泛序列化，不能把本次收窄描述为原样保留。

## Decision

内部数据类与唯一构造者共同位于 app/parsing/processors/parse_quality_gate.py，原 parse_quality_schema.py 退出，不提供旧路径壳。dataclass 继续表达内部结果；它不是请求或响应的 Pydantic 模型，不改变 API schema。

构造者产生固定字符串 grade、布尔标记和动作、标准标量／列表／字典组成的 evidence 与 thresholds；warnings 使用独立列表工厂。to_metadata 使用 asdict，保留嵌套容器副本及原 schema 标识；应用元数据直接读取这些已成立字段。不继续支持没有生产调用依据的任意对象转文本或错误内部字段默认成功。

此决定只替代[阶段与结果边界](2026-11-05-parsing-stage-function-ownership.md)中保留质量门禁通用序列化的部分，其他阶段接口、原始 SDK／JSON 校验和资源合同保持。外部元数据仍由门禁的原始信号解析入口处理；不把内部记录的前提推广到原始输入。

## Alternatives considered

- 保留独立文件和递归转换可接受更多任意对象，但全仓生产／脚本引用只显示门禁中的单一构造者；额外兼容掩盖了实际合同并增加阅读跳转。
- 将原始信号和内部结果全部换成新 Pydantic 模型能统一验证，却会改变历史 SDK／metadata 的接受范围；本次只整理内部结果所有权。

## Consequences

一次门禁修改集中在一个文件，标记不再被缺省成 pass。记录和返回 metadata 的容器仍独立；公开 wire 名称、评分权重及默认阈值保持。原始标量、合法零值和缓存的必要边界见[辅助生产者](2026-11-05-parsing-auxiliary-producer-boundaries.md)及[共享标量转换](2026-11-03-shared-scalar-coercion-owner.md)。冻结测试中的旧模块导入需要后续迁移，当前按用户要求不改、不运行测试。

检索活跃笔记后，上述三篇均为部分重叠，保留并互链；没有同题提案或否决记录需要退出。历史覆盖行保留旧 SHA 和审核来源，当前 app 清单只登记现存文件，不将删除算作完成。

验证使用冻结原文与当前源码的有限 AST 隔离对照，覆盖分级、原始信号、零值、门槛与深层副本，另核完整应用冷导入和 OpenAPI。没有执行请求、真实 SDK、解析、模型或服务；这些证据不代表真实文档质量或环境验收。
