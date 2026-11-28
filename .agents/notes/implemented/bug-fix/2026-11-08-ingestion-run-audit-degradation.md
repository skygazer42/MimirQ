# Agent Note: 入库运行审计失败保持旁路且可观测

Status: implemented

## Problem

入库运行的 replay、JSON/HTML 导出和 compare 各维护一份审计 try/commit/rollback。四处都用 `contextlib.suppress` 吞掉 rollback 分支且不记录原异常，成功响应无法区分审计已落盘与审计缺失；重复实现也让新增入口容易继续复制静默失败。

## Decision

`app.api.v1.ingestion_runs._commit_ingestion_run_audit` 持有审计事件、独立 commit、失败 rollback 与 warning。四个入口继续在 replay 已创建或读取/比较结果已形成之后调用它，传入原 tenant、actor、run、action 和 details。审计失败不改写 replay、导出或 compare 的主结果；warning 带 action、run_id 和异常堆栈。

helper 不重试、不双写，也不把审计伪装成主事务的一部分。入库 run/document 状态、数据集写权限、导出内容和 replay 后台任务继续由原 owner 负责。

## Alternatives considered

- 审计失败直接返回 5xx 可以强制调用方注意，但 replay run 此时已经创建，导出/比较结果也已形成；失败响应会误导客户端重试主操作。
- 保留四份局部捕获改动更小，但无法建立一致 rollback、日志级别和异常上下文，新入口仍会复制静默 suppress。

## Consequences

审计失败后 Session 恢复可用，主 API 语义保持，日志可以定位缺失的 action 与 run。代价是成功响应不保证审计落盘；需要强一致审计时必须另行引入事务 outbox 或同事务写入，而不能依赖本旁路。

验证仅运行 Python 3.14 源码编译、限定差异/空白检查和 Note 门禁。当前环境未安装 Ruff；依用户指令未新增或运行 Python 测试，也未执行数据库、API、导出或 replay 运行时。
