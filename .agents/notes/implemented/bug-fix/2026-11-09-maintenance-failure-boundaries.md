# Agent Note: 维护主操作失败直接传播

Status: implemented

## Problem

审计日志清理的计划查询失败返回零，实际删除／commit 失败也回滚后返回零。管理员清理 API 和保留作业随后生成 eligible/deleted 为零的成功摘要，无法区分真实没有匹配记录与数据库故障。`commit=False` 分支还吞掉 flush 错误后报告删除数量。

维护入口对必填的 retention_days/max_delete 解析失败时又替换为 90 天、10 万／200／1,000 条等预算。调用方错误因此会触发另一份清理计划，尽管 CLI 已通过 argparse 提供默认值和整数解析。

## Decision

`audit_log_retention` 的四个计划／候选查询入口直接传播失败。只有查询成功且候选为空时才返回零；原租户、过滤条件、时间范围、排序和 max_delete 上限保持。

`delete_audit_log_rows` 仍按同一去重 ID 列表和 tenant 谓词删除；commit 或 flush 成功后才返回删除计数。删除、提交或 flush 失败时按原失败边界 rollback，记录带堆栈的 warning 并重抛；rollback 本身失败也向上传播。`commit=False` 继续表示正常路径只 flush，由调用方负责最终提交。

管理员授权、实际清理与“记录本次维护”的审计旁路分别保留原 owner。主动清理权威数据的错误不能借用 audit_log_event 的 fail-open 约定；后置审计失败仍由已有 API／作业边界处理，本次不使普通产品流程依赖审计旁路成功。

审计、回归运行和知识资产三个维护作业复用现有 `_normalize_retention_inputs`。它按原先顺序执行整数转换和最小一条／一天的约束，不在转换失败时选择另一份预算；非法值在候选查询前直接报错。回归运行的 5,000 条独立上限、CLI 的默认值、显式 dry_run／execute 选择和其他查询参数保持。

## Alternatives considered

- 失败后返回零并写日志可以维持成功响应，但零是有效业务结果，API 无法据此区分故障并会把请求报告为完成。
- 给所有 helper 增加 result/error 包装可以显式返回失败，但会新增一套返回模型和调用协议；现有 API／作业已经有异常入口，直接传播保留原成功返回契约。

## Consequences

数据库故障表现为维护请求或作业失败，真实空候选仍是正常零结果。以前依赖无声 no-op 的调用方需要处理真实失败；不会在错误后尝试另一种删除、扩大范围或以默认记录补成功。

验证核对管理员 API、retention_jobs、现有类型与查询／事务调用。全模块 AST 对照限定四个捕获退出和删除事务的 flush／rollback／重抛，原查询、签名及成功返回保持。Ruff check/format、Python 3.11 AST／源码编译和 Note 门禁通过。按用户要求未新增或运行 Python 测试，未执行数据库、维护、清理或任何数据删除。

预算增量核对实际 argparse 定义、两个数据库作业和知识资产调用，模块 AST 只允许参数转换失败兜底退出与两份相同准备逻辑迁到已有 helper；数据库、审计、逐文档结果和汇总语句保持。正常整数含零／负数继续使用原最小值规则，不把此次整理当作新增严格类型或范围校验。
