# Agent Note: 新鲜度查询直接解包固定两列 Row

Status: implemented

## Problem

周期作业新鲜度通过真实 AuditLog.created_at 与 AuditLog.resource_id 两列查询读取最近审计事件。SQLAlchemy 返回 Row，旧代码只在 isinstance(row, tuple) 时提取两列，导致有效事件被当成没有时间戳。真实管理员与租户范围的 observability 入口因此把已经执行的四类作业也报告为 stale，last_created_at 为空。

## Decision

仅在原 empty-row guard 之后直接解包 created_at, resource_id = row。datetime 过滤、UTC 处理、SQL 租户／action／resource_type 条件、排序与上限、查询异常返回、resource_id 字符串格式和公开响应均沿用原规则。不识别或构造 SDK Row，不增加 tuple／Row 兼容分支。

实际固定列查询的消费者必须同步匹配列数。[周期审计单列读取](2026-11-05-periodic-audit-single-column-rows.md)约定继续适用于其原两个调用点；本篇持有独立的新鲜度 owner，不修改前一交付的提交与证据。

## Alternatives considered

- 扩展 isinstance 判断以接受 Row，也能读取真实结果，但生产者已经固定为两列 SQLAlchemy 查询。直接解包更准确地表达列数契约，也避免额外兼容类型分支。
- 取消 datetime 校验可以让更多对象进入新鲜度计算，但会改变现有原始字段过滤和错误政策，因此只修正行提取投影。

## Consequences

存在匹配审计的作业可以显示真实时间与资源 ID，并按原年龄阈值判断 stale；缺少记录、查询失败和无效日期仍保留原输出。查询列数未来改变时必须同步该解包。

Root 核对两列查询、实际管理员／租户 API 和已安装 SQLAlchemy Row／BaseRow 的序列契约后授权该最小修复。整模块源码与 AST 仅允许这一处两列投影变化，调用方与 schema 保持原样。Ruff、格式、Python 3.11 AST 和笔记门禁通过；没有执行应用、SDK、模型、数据库、服务、回调、业务正则或 Python 测试。

活跃笔记检索命中相邻单列审计修复，职责部分相邻但所有者不同，保留并链接；没有同一新鲜度 owner 的既有提案需要吸收或归档。
