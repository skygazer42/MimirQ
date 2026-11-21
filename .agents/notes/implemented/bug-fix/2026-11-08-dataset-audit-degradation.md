# Agent Note: 数据集审计失败保持旁路且可观测

Status: implemented

## Problem

数据集创建、更新、配置导入、检索审计、克隆、清理与导出在主操作之后各自写审计。部分入口把 `audit_log_event` 放在保护范围外，部分只保护 `commit`，另一些用 `contextlib.suppress` 或 debug 日志吞掉失败。审计 commit 失败后没有统一 rollback，后续响应投影可能继续使用失败的 Session；调用方收到成功结果时也无法判断审计是否缺失。

## Decision

`app.api.v1.datasets._commit_dataset_audit` 持有数据集审计事件构造、独立 commit、失败 rollback 和 warning。八个调用点继续在主业务提交或只读结果形成后调用它，传入真实 tenant、actor、dataset、action 和 details。审计失败不改写已经提交的创建、更新、导入、克隆或清理结果，也不阻断已经形成的导出响应；warning 带 action、dataset_id 和异常堆栈。

该 helper 不重试、不写第二存储、不补伪造审计记录。tenant/权限检查、主事务、响应字段、导出脱敏和清理计数仍由原 owner 负责。若未来要求审计与主业务原子一致，应采用事务 outbox 或同事务强制审计的独立设计，不能在响应提交后假称跨事务原子。

## Alternatives considered

- 审计失败直接让请求失败可以强化合规门槛，但主业务此时已经提交；返回 5xx 会诱导客户端重试并把成功写入误报为失败。
- 保留八份局部 try/suppress 改动更小，但异常覆盖范围、rollback 和日志级别继续分叉，新的数据集入口仍容易复制错误模式。

## Consequences

审计旁路失败后 Session 会先 rollback，主响应仍按既有语义返回，日志可定位缺失 action 与 dataset。代价是成功响应不等于审计必然落盘；需要强审计保证的部署仍应使用外部告警与后续对账，并评估事务 outbox。

验证仅运行 Python 3.14 源码编译、限定差异/空白检查和 Note 门禁。当前环境未安装 Ruff；依用户指令未新增或运行 Python 测试，也未执行数据库、API 或导出运行时，因此不声称异常路径已有运行时回归证明。
