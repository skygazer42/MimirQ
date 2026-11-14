# Agent Note: 数据库状态由公开模块直接持有

Status: implemented

## Problem

`app/core/database.py` 仅转出 `database_singleton.py` 的四个对象。holder 的明确理由是防止测试主动清除公开模块的 import 缓存后重复创建 ORM Base；app 和生产 scripts 没有直接消费 holder，也没有主动移除该模块的调用。两处文件和说明需要同步，但不承担两个生产职责。

## Decision

引擎参数、engine、SessionLocal、Base 和 get_db 由 `app.core.database` 一个模块持有，删除测试专属 holder。所有生产导入及四个公开名字保持；正常 Python import 缓存维持进程内对象一致。测试故意删除模块缓存后的对象身份不再作为生产兼容要求，不恢复转发壳。

本次只移动实际实现，保留池参数、SQLite 分支、Session 选项和原 get_db 失败顺序。普通异常仍尝试 rollback，原 rollback suppression、finally close 及 close 可能成为最终异常的策略没有在此被修复；不能把迁移报告成完整资源可靠性改造。相关跨层所有权原则见[API 调用与输入所有者](2026-11-10-api-route-and-input-owners.md)。

## Alternatives considered

保留 holder 可以继续支持旧测试的主动重导入，但没有生产调用需要这层，且用户明确不为旧 Python 测试增加兼容实现。另行改写 get_db 的事务和异常策略可以缩短实现，不过会同时改变资源失败行为，故本次保留原体而不把职责合并扩大成事务重设计。

## Consequences

app 当前源码少一个文件；历史覆盖表登记退役路径及原始 SHA，当前文件清单移除该路径，不通过缩小分母伪增完成数。旧测试若依赖该路径或主动清除模块缓存，应在后续测试任务调整，按当前授权不改、不跑。

静态比较确认 helper、状态创建和 get_db 可执行 AST 与旧 holder 相同，18 组假引擎／Session 轨迹覆盖正常、普通错误、取消和 rollback 失败。完整 app 冷导入确认用户、数据集、文档模型共享同一 Base.metadata，get_db 来自公开模块，旧 holder 不加载，OpenAPI 保持。真实数据库、工厂失败、close 失败和部署启动未在此验证。
