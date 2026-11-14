# Agent Note: 配额服务保留实际使用的入口

Status: implemented

## Problem

租户配额的实际请求使用异步 QPS 执行器和用量查询，但模块同时保留没有生产消费者的两种 QPS 检查入口及同步执行器。独立的月度 token 计算工具和 RLS SQL 生成器也没有应用、脚本、注册或配置入口；它们与实际 quota_service、tenant_quota_service 的策略并存，容易使维护者误判应改哪套实现。

用量 SQL 已使用 COUNT 或 COALESCE 保证非空，消费端仍把异常的 None 当作零。只读配额检查发生错误时沿用可选降级，但没有记录发生过故障。

## Decision

删除未使用的 tenant_quota.py、tenant_rls.py，以及 tenant_quota_service 中三个没有调用的 QPS 入口。保留真实的 enforce_tenant_qps_quota_async、配置查询、上传及嵌入额度执行、三类用量展示；HTTP 响应、租户条件、缓存参数、Retry-After 和既有 fail-open／fail-closed 策略保持。

SQL 聚合的返回值直接进入 int，不再把不可能的空结果解释成零。int 继续保留，因为 PostgreSQL 对 BigInteger 求和可能返回 Decimal。嵌入窗口和 mode 由 Settings 的正数约束与选择校验确定；QPS mode、派生 burst、Redis 前缀和最短 TTL 仍有实际规范化含义，不机械删除。

只读配额降级记录异常类型，不记录异常消息或凭据，不新增审计写入；执行器仍使用原有指标／审计与失败处理。标准 UTC 时区、取消传播和原有请求／工作线程位置保持。

## Alternatives considered

保留多种入口有利于未来接入同步调用，但当前只有异步请求消费者，检查与执行的重复实现会继续分叉。让未接入工具转发到实际服务能满足旧导入，却会把测试或未来需求当作现在的生产职责。

将全部配额检查改为失败关闭可以更早暴露后端问题，但会改变现有产品策略。保留已定义的降级并补充可观察记录，权威失败不会再因聚合返回异常空值而被当作正常零用量。

## Consequences

实际配额算法有一个维护入口，退出的工具不代表部署了或移除了数据库 RLS 策略。旧测试若导入已退役工具或入口，需要在独立测试维护中更新；本任务不改、不运行 Python 测试。

离线对照使用未连接的 PostgreSQL SQL 编译、假 Session／limiter／Settings，核对零值、限制边界、Decimal、错误状态、证据、缓存、取消和只读警告。未执行真实 SQL、Redis、配额业务或数据库安全策略；调用方并发及部署效果仍需要相应环境验证。
