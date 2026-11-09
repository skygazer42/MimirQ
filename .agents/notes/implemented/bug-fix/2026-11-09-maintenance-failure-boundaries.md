# Agent Note: 维护主操作失败直接传播

Status: implemented

## Problem

审计日志清理的计划查询失败返回零，实际删除／commit 失败也回滚后返回零。管理员清理 API 和保留作业随后生成 eligible/deleted 为零的成功摘要，无法区分真实没有匹配记录与数据库故障。`commit=False` 分支还吞掉 flush 错误后报告删除数量。

维护入口对必填的 retention_days/max_delete 解析失败时又替换为 90 天、10 万／200／1,000 条等预算。调用方错误因此会触发另一份清理计划，尽管 CLI 已通过 argparse 提供默认值和整数解析。

知识资产清理还把空值或不识别的 lifecycle_state 当作 either，可能将调用方错误变成同时选择归档和禁用文档。陈旧报告的必填天数或数量转换失败也会改用 30 天和 5,000 条，掩盖实际配置错误。

周期审计和陈旧报告把“今日报告是否已写入”的查询异常当作 False，可能在未知状态或失败 Session 上继续运行。索引和证据报告虽收集逐数据集错误，最终却始终写 ok=True，导致依赖该字段的 CLI 返回成功退出码。两份数据集预算也会在转换失败时无声改用 50。

四个周期报告各自复制相同的写入事务，失败时只在 rollback 也失败后打印 debug；陈旧报告还压掉 rollback 异常。底层 audit_log_event 在构造或 db.add 失败时无日志返回，外层即使 commit 成功也无法观察这次审计缺失。

## Decision

`audit_log_retention` 的四个计划／候选查询入口直接传播失败。只有查询成功且候选为空时才返回零；原租户、过滤条件、时间范围、排序和 max_delete 上限保持。

`delete_audit_log_rows` 仍按同一去重 ID 列表和 tenant 谓词删除；commit 或 flush 成功后才返回删除计数。删除、提交或 flush 失败时按原失败边界 rollback，记录带堆栈的 warning 并重抛；rollback 本身失败也向上传播。`commit=False` 继续表示正常路径只 flush，由调用方负责最终提交。

管理员授权、实际清理与“记录本次维护”的审计旁路分别保留原 owner。主动清理权威数据的错误不能借用 audit_log_event 的 fail-open 约定；后置审计失败仍由已有 API／作业边界处理，本次不使普通产品流程依赖审计旁路成功。

审计、回归运行和知识资产三个维护作业复用现有 `_normalize_retention_inputs`。它按原先顺序执行整数转换和最小一条／一天的约束，不在转换失败时选择另一份预算；非法值在候选查询前直接报错。回归运行的 5,000 条独立上限、CLI 的默认值、显式 dry_run／execute 选择和其他查询参数保持。

知识资产的 `_normalize_lifecycle_state` 直接处理字符串，仅接受 archived、disabled、either；原有空白修剪和小写归一化保留，无效值在查询前失败，不替换为另一种选择范围。两个公开入口的默认 either 和 CLI choices 保持。陈旧报告的限制转换失败同样直接传播，正常整数仍使用最小一天／一条以及 50,000 条上限，默认值由既有 argparse 定义持有。

报告存在性查询直接传播数据库失败，真实查无记录仍返回 False，execute／force 的短路和已写入时的跳过响应保持。索引和证据审计继续收集原有逐数据集错误，但摘要 ok 取 not errors，使部分失败也进入 CLI 已有的失败退出策略。两个报告复用 `_resolve_dataset_audit_cap` 的整数转换、最小一条和 5,000 条上限；私有 listing 直接使用唯一调用方已归一化的预算，不再各自重复转换。

`regression_run_retention` 的计划和删除共用 `_candidate_run_ids`，同一处完成预算转换、最小一条与 5,000 条上限。计划不再先 COUNT 所有匹配记录，而是返回有限 ID 结果的长度；删除复用同一选择规则。租户、可选 dataset、completed/failed 状态、非空完成时间、cutoff 和原排序保持，单列查询按实际非空 UUID 主键解包。

三个维护作业的后置审计由同模块 `_commit_retention_audit` 持有。它仅提交既有事件，审计失败先 rollback，再以 action、tenant 和异常堆栈记录 warning，保留已完成维护的原摘要。原来三份只在 rollback 失败时 debug 的分支退出；rollback 本身失败直接传播，不伪装 Session 已恢复。

四个周期报告共用原索引报告写入函数改名后的 `_write_audit_summary`，显式传入各自 action 和 resource_type。报告详情投影、commit、成功 dry_run 与失败 ok／audit_write_error 字段保持，失败先 rollback 再 warning，rollback 本身失败传播。陈旧报告沿用自己的 error 字段和返回协议，仅采用相同的回滚与可观测原则。audit_log_event 保留原构造、db.add、无 commit 与 fail-open 返回，捕获处记录 action、tenant 和堆栈，不记录 details、ip、actor 或消息正文。

维护、周期审计和陈旧报告的摘要时间来自 `now or datetime.now(UTC)`，cutoff 由该时间减去 timedelta 得到；三处 `_dt_to_json` 因此直接接收 datetime 并返回字符串，保留各自原有的时区转换和 UTC 的 Z 表示。无效内部时间不再变成空时间。审计／回归的计划长度与真实 SQLAlchemy 删除行数直接使用；知识资产计划自行构造的必有 document_id 和 lifecycle_state 按键读取，不再跳过失效候选或补 unknown。可选 dataset、actor、外部时间戳解析、逐项删除失败归类和零候选结果保留原政策。

报告消费端直接读取完整 builder／Pydantic DTO 中必有的字段，排序、计数和 Counter 累加使用其实际字符串、整数、浮点数和列表；样本仍取新切片并保持原上限。陈旧报告直接使用自己的十字段查询投影及已归一化预算，保留外部 metadata 时间解析、来源优先级和真实缺失字段的业务含义。两份 CLI 使用 argparse 已产生的原生值，UUID 回调只转换真实 ValueError，真实主键单列查询不再静默丢弃记录。参数声明、默认值、互斥、资源关闭、主顺序、JSON 和退出码逻辑保持。

## Alternatives considered

- 失败后返回零并写日志可以维持成功响应，但零是有效业务结果，API 无法据此区分故障并会把请求报告为完成。
- 给所有 helper 增加 result/error 包装可以显式返回失败，但会新增一套返回模型和调用协议；现有 API／作业已经有异常入口，直接传播保留原成功返回契约。
- 不识别状态时改用 either 可以容忍旧调用方，但会改变本次清理范围；CLI 已明确提供默认值与 choices，内部无效值直接失败更符合调用意图。

## Consequences

数据库故障表现为维护请求或作业失败，真实空候选仍是正常零结果。以前依赖无声 no-op 的调用方需要处理真实失败；不会在错误后尝试另一种删除、扩大范围或以默认记录补成功。

验证核对管理员 API、retention_jobs、现有类型与查询／事务调用。全模块 AST 对照限定四个捕获退出和删除事务的 flush／rollback／重抛，原查询、签名及成功返回保持。Ruff check/format、Python 3.11 AST／源码编译和 Note 门禁通过。按用户要求未新增或运行 Python 测试，未执行数据库、维护、清理或任何数据删除。

预算增量核对实际 argparse 定义、两个数据库作业和知识资产调用，模块 AST 只允许参数转换失败兜底退出与两份相同准备逻辑迁到已有 helper；数据库、审计、逐文档结果和汇总语句保持。正常整数含零／负数继续使用原最小值规则，不把此次整理当作新增严格类型或范围校验。

回归候选增量核对 `_base_query`、真实主键声明、两个 API／作业调用者。全模块 AST 限定共同候选选择、两处失效预算兜底退出和计划的有界计数，实际删除及提交语句保持。SQL 执行计划、并发变化和数据库扫描成本未做运行验证；至多读取 5,000 个结果 ID 不等于声称数据库只扫描 5,000 行。

后置审计增量逐项对照三个原事件的 action、resource、actor 和 details 实参及其顺序，模块结构对照限定共同提交／回滚／warning 政策与调用迁移。没有新增审计字段、配置、重试或持久化副本，未执行任何维护或审计写入。

摘要值增量核对实际 datetime 赋值链、同模块计划的完整键、真实主键和安装版本 Query.delete 的 rowcount 返回，完整模块 AST 对照仅允许这些已核实的取值／格式化简化。未改动各查询、租户范围、删除参数、事务、排序或原始连接器时间戳解析；静态验证不能证明真实数据库和时区运行行为。

选择范围和陈旧报告预算增量核对两个 CLI 的真实 choices／整数默认、服务入口和查询前的转换顺序。完整模块对照限定两个归一化函数的失败政策，其他函数与所有查询、删除、提交、报告计数、来源时间戳优先级和序列化保持；没有执行报告或维护任务。

报告状态增量核对两个 CLI 对 res.ok 的累计及退出码、五处报告存在性调用、两个私有 listing 的唯一调用方和实际 SQLAlchemy first 的可空返回。完整模块 AST 对照限定上述捕获退出、状态标志和单一预算 owner，原查询谓词、排序、有效预算、错误样本上限、业务计数及写入语句保持。未执行 CLI、查询或报告运行时；源码核对不等同于这些失败路径的运行回归。

报告写入增量先证明四份事务 AST 仅 action／resource_type 字面量不同，再核对提取后调用实参与展开顺序。全模块对照限定共享提交政策、两个 warning 边界和底层排队失败日志；事件构造、detail 字段、错误标志、所有查询、业务汇总和外部输入解析保持。没有增加重试或另一个写入目的地，未调用业务、日志服务、Session 或任何外部系统。

原生值增量核对七个索引报告字段在 HEAD 与工作树中的实际生成表达式、证据审计 DTO 与空结果字典、十字段陈旧报告生产者、真实非空 UUID 主键和 argparse 声明。全模块对照限定取值／转型与两份 CLI 的声明契约，来源时间戳解析和所有 SQL 谓词保持；仅私有摘要 helper 退出一个失去用途的 dataset_id 参数并同步唯一调用方，未新增包装层、运行时模型或文件。静态核对不包含实际 CLI 或报告执行。
