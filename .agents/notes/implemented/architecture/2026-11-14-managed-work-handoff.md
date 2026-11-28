# Agent Note: 已提交准备结果直到实际任务交接都有人持有

Status: implemented

## Problem

文档 retry 和两种 dataset scan 在提交 pending 后取消，会关闭 Session 并传播取消，但没有队列或本地任务拥有后续工作。retry 的 queued 状态无法再重试；扫描则在过期前阻止下一次创建。批量预检还可能在扫描线程结束前删除 staging 目录。

## Decision

原 connector_handoff 资源所有者一对一改名为 managed_handoff，函数为 prepare_managed_handoff；三处既有 connector 调用方仅迁移 import 和五个调用名称。其 prepare、shield／drain、独立 recovery Session 与原取消优先顺序保持，不增加另一个资源层或旧路径 alias。文档与扫描直接使用同一个实际 owner，core async_bridge 和 managed-session 实现保持只读。

文档 retry 的已准备 plan 在取消后，由同一个 schedule-failed owner 补偿。只有本次文档仍 pending／queued、没有已交接 task 标记且 pipeline 未改版时才处理；已取消、运行／交接或改版状态不覆盖。plan=None 的 unchanged 结果不动，prepare／recovery Session 先关闭，原取消继续传播。现有补偿失败仍按其日志和 best-effort 策略处理，不把它说成完整的并行 retry CAS。

批量预检用现有 run_blocking_in_thread 等扫描 worker 与 Session 结束后，再删除 staging。原 precheck-only／可选扫描、失败记录与返回政策保持，不换成裸 to_thread。

dataset scan 保原授权、过期与 active 检查，结束已经没有待写的读取事务后，让 managed prepare 独立拥有 insert／commit／DTO。取消时只恢复本次未交接 pending，已运行／完成／取消状态不被覆盖；原 IntegrityError 与 409 规则保持。

enqueue 由独立 Task 持有并在取消时结算：实际 job ID 表示已接受，TaskEnqueueRejectedError 表示明确拒绝。普通无 receipt 错误保留 pending 并写可见的未知结果，不推断失败或成功，不盲目重试；原 503 detail 保持。队列关闭且尚未本地提交时取消，恢复未交接的 run；已经提交则不回滚为失败。

正常 queue-off 工作由现有本地 runner 和应用 loop 默认 executor 立即持有，退出对 HTTP Response BackgroundTasks 的依赖。复制原 ContextVars，提交前使用现有 local-active registry，提交失败解除登记，完成回调观察错误和解除登记。pending／running 都尊重实际本地 owner，包括队列开关变化的场景；不引入新的 JobManager、状态枚举、私有 transport 或可猜测成功标记。

本篇部分更新[API 执行契约](../bug-fix/2026-11-11-api-v1-execution-contracts.md)中原先已登记的创建取消缺口；其他线程、请求循环、事务和错误责任保持。

## Alternatives considered

- 只在 except Exception 增加失败补偿不会捕获 CancelledError，也不知道 broker 是否已接收；先结算实际任务结果。
- 让本地任务继续依赖 Response 改动较少，但调用方取消时没有可靠的响应后执行点；由 executor 接受后独立持有。
- 把含 Session 的资源所有者搬入 core 会反向依赖 service 的 managed-session allocator；改名现有 owner，保持真实依赖方向。
- 引入 outbox、全局调度 manager 或另一套 Job 状态能提供更强耐久性，但超出已确认的交接责任；本次不建立第二个真值来源。

## Consequences

关闭 Session 不再被当作任务已交接，取消后的准备结果有明确补偿或实际队列／executor owner。本地工作可以早于响应发送开始；它不再受响应存活控制，仍是当前进程的工作，不承诺进程崩溃、重启和 executor 关闭期的持久执行。

未知 broker 结果不是自动失败，也不是成功；保留其可观察错误并遵循现有状态核对／过期规则。取消恢复是有限的状态检查，不宣称已经解决所有并行准备或分布式队列 CAS。

验证以实际 prepare／queue／API／bridge／资源源码和手动驱动的 Task、Session、executor、registry 端口检查原四个切点与有限修后场景。没有运行事件循环、真实线程、队列、数据库、SDK、业务文件、应用测试或进程故障实验；原错误证据与最终源码绑定分别保留。
