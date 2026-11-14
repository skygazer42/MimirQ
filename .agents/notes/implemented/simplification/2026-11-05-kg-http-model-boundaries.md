# Agent Note: KG HTTP 辅助操作使用实际模型边界

Status: implemented

## Problem

KG HTTP 的投影、快照、合并和撤销辅助操作用 Any 或 object 描述实际 ORM、模型类和 XML 对象，已有内部 dataclass 也隐藏了查询结果类型。代码因而重复探测声明字段和转换本地长度、撤销计数。

## Decision

辅助操作使用实际 KgEntity、KgSourceEvent、KgEventEntity、KgRelation、redirect 和 resolution action 类型；模型工厂参数标明 type，快照哈希标明具体 callable，GraphML 使用实际 Element、KGGraphNode 和 KGGraphLink。内部 dataclass 标明实际 ORM 集合和 SQL DateTime 结果，保留字段顺序、默认、构造与对象形状。ORM 类型依赖放在 TYPE_CHECKING 下，原函数内导入和运行时加载时点保持。

只有实际模型已声明的字段直接读取，保留同一 or 默认、str/float、Decimal、UUID、None、raw JSON 与 undo payload 转换。Settings 只退出字段存在性探测，原值转换保持。len 和 KGUndoStats 的本地整数／布尔计数直接消费，不从注解推断外部值已经验证。

所有公开 HTTP 参数、Depends、Query、默认、返回注解、路由 decorator、response model、状态、错误与 headers 保持。既有 routes facade 的直接重导出和 patch 归属保持；原查询、tenant/ACL、排序/cap、事务、审计、向量、缓存和失败策略保持。redirect 查询的既有 FakeQuery 兼容分支与 raw UUID 恢复规则保持，避免把泛化推断当作清理依据。

两处已确认的提交后关键字错误单列在[修复记录](../bug-fix/2026-11-05-kg-delete-response-keywords.md)，不归入等价整理。

## Alternatives considered

把辅助操作再包成管理器可以集中上下文，但已有模块函数和实际 dataclass 已承担各自职责，因此不增加 Manager 或 Context。把原始 JSON、SQL scalar 和 provider 值一律按注解读取会更短，却会丢失真实输入与持久化边界，所以这些转换保留。

保留全部 Any 和 presence fallback 能少改几行，但会继续遮住真实 ORM 与 XML 生产者；本次只收窄已由实际查询、构造和调用者证明的字段。

## Consequences

辅助流程的类型和数值来源更清楚，HTTP 请求与返回协议保持原样。完整操作 AST 对照只投影上述声明字段、实际类型、本地值及明确授权的两个关键字修复。没有新增、修改或运行 Python 测试，也没有导入应用、SDK，或运行数据库、服务、业务函数与正则。

笔记检索中，已有[KG 基础归属](2026-11-05-kg-foundation-owned-values.md)与[提取归属](2026-11-05-kg-extraction-function-ownership.md)覆盖仓储、正常化和资源边界；本篇只覆盖 HTTP 辅助类型与内部值，沿用其已接受的 SQL、ACL、JSON、UUID 和工厂时点决定。查询扩展与搜索操作仍属于原所有者，没有被本篇替代。
