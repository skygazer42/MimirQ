# Agent Note: 审计查询复用筛选规则并按单列行读取 UUID

Status: implemented

## Problem

审计列表与清理分别维护相同的七个筛选条件，三条删除路径重复事务与失败处理。清理把单列查询结果限定为 tuple；本地 SQLAlchemy 的 Query 返回 Row，它支持序列解包，但不继承 tuple，原适配会遗漏真实候选。

## Decision

八个请求与响应模型归入 app/api/schemas/audit.py，原路由继续导入这些名称。筛选规则由 audit_log_service.apply_audit_log_filters 维护，路由展开 filters.model_dump()，保留原生 datetime，避免 JSON 序列化改变数据库比较值。

清理直接解包 Query(AuditLog.id).all() 的单列 UUID 行。查询先限定租户与截止时间，再按 created_at、id 升序和 max_delete 限量；候选不再经过 tuple 判断或静默丢弃。保留按保留期与显式筛选两种范围、dry_run、权限及数量上限。

三条删除路径使用已有 delete_audit_log_rows，统一去重、租户条件、删除与 commit／flush／rollback。既有 best-effort 的返回零、日志和 rollback 保护保留。审计写入继续不自行提交，调用方的事务边界不变。

权限快照直接读取已确认的 ORM 字段、枚举和值类型；异构模型序列化仍留在现有路由，不为类型分支新增包装层。分页种类顺序、敏感字段脱敏、哈希、版本化 schema、时间格式与 gzip 规则保留。

## Alternatives considered

- 保留 tuple／UUID 适配能够兼容手造的行对象，但实际数据库契约只有单列 Row，且现有判断遗漏真实结果；直接解包更符合所有者提供的数据。
- 将筛选字典先转成 JSON 可以复用导出字段映射，但会把 datetime 变成字符串，因此数据库筛选使用 Python 模式的 model_dump。
- 保留三份删除代码可减少一次函数调用，但租户与事务规则需要多处同步；当前已有明确删除函数，复用它不增加新抽象。

## Consequences

筛选与删除规则各只维护一处。UUID 行读取修复改变原先错误的候选遗漏行为，因此该项按缺陷修复记录，不能将整批声明为纯 AST 等价重构。

八个 schema 的完整 AST、七个路由声明及参数、错误和权限调用、响应字段、筛选条件与删除事务顺序已核对；38 个参数契约及 33 个文件的 123 处确定调用通过源码检查。Ruff 与格式检查另见验证记录。按用户要求未新增、扩写或运行 Python 测试，未启动数据库；实际清理及导出运行时行为仍未验证。

历史笔记核对：已有数据集和权限／配额笔记的审计引用属于业务调用侧，与本篇查询和单列行契约无关，均保留。
