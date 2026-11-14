# Agent Note: 检查点由实际保存器持有状态与连接

Status: implemented

## Problem

本地 memory.py 复制内存保存器，但工厂与普通包实际使用 LangGraph 的 InMemorySaver。TimeTravel facade、两个DTO与全局缓存也没有业务、脚本、配置、动态注册或外部文档入口；HTTP检查点接口直接操作已编译图。两份源码与再导出增加无用维护点。

SQLite 的异步SDK方法直接执行同步数据库操作，连接也没有明确关闭入口。异步操作移到线程池后，标准 :memory: 路径不能继续让每个工作线程创建互不相通的数据库。

## Decision

两份无业务根的本地实现与四个 TimeTravel 导出退出。普通包保留实际 SqliteSaver、SDK MemorySaver 别名和 get_checkpointer，工厂的单例、配置选择与现有设置／重置接口保持。冻结的 test_empty_fallback_rag_memory.py 仍直接导入旧 facade，test_source_guard_contracts.py 仍含旧路径；明确这些例外，不称全仓无人引用，不为旧测试留生产壳。

SqliteSaver 保留真实配置、serde、thread-local连接、锁、SQL及公开SDK签名。三个单用纯helper在负责的调用处展开，真实parent／filter／before／limit与连接初始化的可空语义保留。

异步读写使用既有 asyncio.to_thread，alist 每次等待一个 next 结果，不把全部历史预先装成列表。执行中的阻塞工作不能被取消 await 强制终止，不把这个边界描述为线程已停止。

保存器用 ExitStack登记实际取得的连接，显式close幂等且关闭后不复用；构造失败关闭已取得资源。正常回收／解释器退出的finalizer只持有stack，不持有self。所有用户结束后再显式关闭，不承诺并发close安全或强制终止清理。

公开db_path=:memory:仍受支持。同一个保存器的各thread-local连接使用唯一shared-memory URI，构造连接随保存器存活，工作线程可以访问同一逻辑数据库；不同保存器有独立URI。普通文件路径保持uri=False语义，不把支持范围缩成文件模式。

## Alternatives considered

- 修补无根的本地MemorySaver和TimeTravel可以保旧测试，但真实业务已使用SDK与图接口，继续维护副本会掩盖实际依赖，因此退出。
- 将async方法改成同步可以避开阻塞标记，但会破坏LangGraph的异步协议；保签名并使用现有线程池。
- 异步list一次性物化全部历史更短，但会增加无界内存并改变逐项交付，因此逐项前进。
- 只把文件路径视为支持范围可以回避内存连接问题，但原公开路径接受:memory:，因此保留该合同并修连接身份。

## Consequences

检查点依赖能直接追到实际保存器，业务检查点路由、内存SDK身份、SQL/schema/参数绑定、ID/namespace/thread范围和序列化保持。异步调度与关闭时点是明确变更，不能伪称全部生命周期逐字不变。

验证使用完整源码与调用图、SDK声明、假connection／serde／path／lock／TLS与有限async端口，核查询值、SQL参数、关闭／回收／构造失败及URI身份。没有运行真实SQLite／数据库／锁／线程或Python应用测试，不能据此宣称真实事务、并发、取消底层工作或数据库运行已通过。
