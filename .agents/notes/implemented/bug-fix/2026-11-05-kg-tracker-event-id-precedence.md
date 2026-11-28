# Agent Note: Tracker 保留真实事件的主键

Status: implemented

## Problem

原 ev_id 条件表达式的 AST 以 isinstance(event, dict) 为最外层判断，因此非 dict 事件总得到 None。活动链从 EventRepository.find_events_by_entities 的 select(KgSourceEvent).scalars().all() 取得真实 ORM 事件，经 expand 的 events_by_id 和 _collect_new_entities 进入节点构造；事件主键声明为 UUID primary_key，原表达式丢失了该主键。

## Decision

只给 dict 回退分支加括号，使对象 id 先参与原 or 判断。dict 输入、title/content、stage/hop、event_id 字符串字段和 node_id 的原始 UUID／字符串政策保持。节点仍经 Tracker.add_clue、ExpandResult.clues 和搜索 combined_clues 进入响应，所有线索预算、顺序与丢弃计数保持。

## Alternatives considered

保留原表达式可以避免行为变化，但已确认的真实 ORM 活动调用会继续丢失主键。统一把 node_id 转成字符串能简化类型，却会改变原 stage 为空时的 UUID 返回政策，因此只修正优先级。

## Consequences

真实 ORM 事件节点恢复原主键。此项是已授权的缺陷修复，单列原 IfExp 与新 BoolOp AST、实际查询生产者和完整消费链；其余节点构造表达式保持。验证仅使用源码与隔离 stdlib AST，没有运行应用、数据库、业务函数、正则或 Python 测试。函数归属见[搜索操作记录](../simplification/2026-11-05-kg-search-function-ownership.md)。
