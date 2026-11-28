# Agent Note: RTBF 与成员权限共享查询的缓存契约

Status: implemented

## Problem

RTBF 与成员权限页都观察 queryKeys.rbac.members({limit:500})。RTBF 的 queryFn 返回 TenantMember[]，成员权限页返回 {items,total}。同一个 Query 因首个生产者而保存不同数据形状；真实 QueryProvider 的 fresh 窗口内，后进入的观察者直接复用该值。先 RTBF 后 RBAC 会显示空成员，先 RBAC 后 RTBF 会在 members.find 处抛错。两个组件同时观察时也会复现，只有一次成员读取。

该缺口在 f37 与缓存寿命修复后的 64 两个精确基线中都存在，与视图退出后没有失效缓存的新回归分别记录。通过接受数组／对象两种缓存值补默认空列表，会掩盖生产者契约冲突。

## Decision

两个实际 queryFn 统一返回 rbacApi.listTenantMembers 的原始 TenantMemberListResponse DTO，缓存保留服务器 total 与可选 items。RTBF 使用 useQuery select 映射 items，继续向原本地逻辑提供 TenantMember[]；成员权限页也使用 select 保留原 items／total 展示投影。select 结果属于各观察者，不再作为另一种数据写回共享 Query。

成员权限写操作按同一 DTO 类型更新缓存，其 items 可选边界使用原 DTO 的空值含义。原 key、limit=500、请求去重、权限、成员标签、当前账号识别、角色／删除／预演载荷及失败处理保持。RbacMembersSnapshot 仅表达该页既有展示投影；没有新的 API 类型、picker 专用 key、转换 manager、Context 或重复读取。

已闭合 GovernanceSection 只迁移必要的 queryFn／select 调用契约，其下游查找、筛选、选择与 RTBF 操作保持原实现，不重新计完整 owner。缓存寿命、会话与原 Query 身份判定继续沿用既有决定。

## Alternatives considered

- 给 RTBF picker 使用另一个 key 能暂时隔离类型，却会重复请求同一成员集，并增加写后失效和一致性职责。因此保留原共享 key。
- 在每个消费者用 Array.isArray 接受数组与 snapshot 两种值，可以避免部分异常，却保留不确定的生产者契约，并可能丢失 total 或静默显示空成员。因此统一缓存值，不做双形状适配。
- 把缓存全部改成成员数组，可以沿用 RTBF 的本地读取，但会丢失服务器 DTO 的 total 与可选字段。因此缓存使用原 DTO，由观察者投影所需视图。
- 在 API helper 新建通用转换层，能集中修改，却扩大到未需要改变的接口与消费者。因此只调整两个实际 Query 生产者和本地 select，复用原导出类型。

## Consequences

导航顺序和观察者挂载顺序不再决定缓存形状。角色写入保留 DTO 缓存，RTBF 和成员权限页均能观察更新；可选 items 缺失时缓存仍是原 DTO，而视图按原语义显示空集合。后续观察同一 key 的消费者需要使用同一缓存 DTO，再声明自己的观察者投影。

全仓搜索只找到这两个实际生产者。七个真实 QueryProvider／QueryClient 与原控件用例在精确 f37 和 64 基线上均 6 失败、1 个独立 RTBF 标签／预演载荷控制通过；覆盖双向顺序、两种同时观察顺序、角色写入后的双视图和可选 items。候选的七个用例通过，完整 RTBF 与访问管理组合检查随报告保留。ErrorBoundary 只用于测试捕获真实渲染错误，没有在产品中加默认成功或错误吞掉路径。

活跃笔记中未发现已有共享成员 DTO 契约记录；[访问管理操作归属](2026-11-05-access-admin-operation-ownership.md)与[缓存完成职责](2026-11-05-access-admin-cache-lifetime.md)继续持有其同步互斥、草稿和寿命规则，本记录补齐数据值契约。[算法设置操作归属](2026-11-05-algorithm-settings-operation-contracts.md)及[认证会话归属](2026-11-04-auth-refresh-session-ownership.md)不被替代或修改。没有新增完整闭合 owner、API／DTO／auth／helper／后端改动、浏览器或服务启动、Python／后端 SDK／数据库／真实授权执行。
