# Agent Note: 任务资源在移交与取消时明确退出

Status: implemented

## Problem

文档、图谱和索引核对的协调函数取得信号量后，可能因锁竞争、重试、任务已经结束或异常而提前退出。调用方只有在成功返回 tuple 时才收到 lease，失败退出却留下继续续租的心跳。释放多个资源时，前一个 await 被首次取消还可能跳过后续租户资源。锁的无 EVAL 兼容路径使用 GET 后 DEL，不能保证删除时仍属于原持有者。

API 队列模块在导入时构造仅 CLI 使用的 ARQ 健康检查配置，使禁用队列的 API 仍需该可选依赖；worker 设置构造又在 ARQ 接管连接前执行一次 socket 探测。队列初始化与关闭没有共用序列化，关闭可能错过尚在创建的连接池。

## Decision

jobs 协调函数只在正常返回资源 tuple 时移交 lease。未移交的退出路径负责释放，多个独立 owner 使用 nested finally，保证前一个失败或取消时仍进入后续退出。成功路径继续由原 job finally 释放，不重复回收。普通失败、Retry、取消、业务状态、commit／rollback 与九个队列参数协议保持。

Redis lease 只使用实际 ArqRedis 支持的原子 EVAL 比较 token 后删除／续期，不探测不存在的方法、不切换 GET／DEL。信号量先请求停止并取消心跳，await 与同步 result 检查分开，避免吞掉等待期间传入的父取消；原子释放在 finally 尝试。lease TTL、忙重试标记、原有告警／暂时失败重试策略保持。

queue 的初始化和关闭共用同一锁，关闭先摘下池引用再释放；普通关闭错误沿用警告，取消继续传播。WorkerHealthSettings 只有当前 CLI 明确取这个属性时才构造并缓存，通过模块 __getattr__ 保留现有命令路径，不导入 worker jobs。该形式只用于实际可选依赖和框架属性查找，不作为业务服务的通用转发方式。worker 连接与重试由 ARQ 持有，去掉 import-time socket 探测；现有 or80 等预算规则保留。

## Alternatives considered

让 caller 统一释放看似集中，但 helper 提前退出时资源没有返回，caller 无法处理。让租约自行超时也不足够，因为未停止的心跳会持续续租。仅把两个 release 顺序放在 finally，仍会被第一个 await 的取消打断；nested finally 表达两个资源各自必须尝试退出。

保留 GET／DEL 可以支持缺少脚本方法的替代客户端，但无法满足拥有者原子性；当前生产使用的 ARQ／Redis SDK 已提供 EVAL。另建健康检查文件能隔离依赖，却需要改动现有 Docker／Helm／Makefile 命令；明确的延迟类属性保持同一公共 CLI 入口，也不扩大文件数量。

## Consequences

首次取消时仍尝试停止所有已取得的心跳。中断的 Redis delete 可能留下会按 TTL 失效、但不再被心跳续租的 key，不能把尝试回收描述成真实删除全部完成。延迟子任务 finalizer 可能在父任务退出后才结束；没有承诺强制取消、重复取消或真实连接关闭的完成时限。

验证使用实际 job／lock 源码、已安装 ARQ 的 CLI 查找与参数投影源码，以及假 Redis／池／worker、本地 asyncio 取消。原错误场景保留为快照，首次取消遗留活心跳从一变为零；成功移交无双重释放。没有导入运行原生 job、连接 Redis／队列或运行应用 Python 测试，真实 Lua、并发负载和部署生命周期仍需实际环境验证。
