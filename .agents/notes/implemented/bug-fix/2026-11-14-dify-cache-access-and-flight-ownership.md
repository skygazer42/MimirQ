# Agent Note: Dify 缓存与快捷检索沿用实际权限和任务归属

Status: implemented

## Problem

Dify 的 metadata 快捷路径和响应缓存能跳过普通检索的成员、数据集、文档权限与 QPS 配额。同一数据集内撤销文档组权限不会更新 Dataset.updated_at，原缓存键仍可能命中已无权读取的内容。metadata 锚点还可能读取主范围之外的数据集，原 corpus token 没有涵盖这些来源。

API 只保留 singleflight 的 key 和 leader 布尔值，没有持有实际 Future。等待权限校验期间若原任务退出、同键新任务取得归属，旧请求可能发布或拒绝新任务的 Future，并触发它的租约收尾。

## Decision

实际 HTTP 入口在 trace、缓存和快捷检索前，使用 document_access 的 get_readable_datasets_map 检查主检索与 metadata 范围的完整并集。成员或任一数据集拒绝保持原错误，不静默删减请求范围。metadata 上下文必须携带真实 account，查询直接组合现有 dataset/document read filter，并保留租户、发布及禁用条件。

所有缓存来源先经过同一个返回入口校验文档权限，再记 trace、计一次 QPS、回填 LRU 或发布自有 Future。记录来源使用现有 document_id 和 dify_composite_source_document_ids，按首次出现顺序去重，并用 get_allowed_document_id_sets 批量复查。完整范围已检查成员，因此这里不重复成员查询。

无记录的负缓存仍是合法命中。非空缓存缺少可信来源、来源已删除或权限撤销时，按一次缓存未命中执行普通检索，不拼出删减后的缓存成功响应，也不继续轮询其他缓存来源。数据库故障和实际权限入口的拒绝继续传播。新鲜结果缺来源时仍可返回，但不写入持久缓存；不增加缓存版本、权限快照或第二套过滤器。

快捷结果和缓存命中调用原 enforce_tenant_qps_quota_async，普通检索保留实际入口的一次计数。corpus token 使用主范围与 metadata 范围并集；原 token 所有者继续对每个 Dataset.id 和 updated_at 排序、去重、哈希，响应证据范围不随缓存键扩大。

请求上下文保存实际取得的 Future，所有 Dify publish/reject 显式交回该句柄。共享缓存的 resolve_inflight_chat_response 和 reject_inflight_chat_response 在任何任务、租约或 pop 副作用前同步比较对象身份；失去归属就结束该操作。原匹配句柄的主体保持，六个现存聊天调用点仍使用原 key 协议，因此 expected_future 默认 None 有实际调用依据。共享文件只完成这两个函数的必要增量，其他聊天归属路径仍待全文复核。

实际 HTTP 编排继续由现有 API 持有。未被生产、配置、任务或启动入口使用的 retrieval、warmup、evidence_adapter 三个旧服务模块退出，warmup_state 和 API 使用的三个 turn-source ID 函数保留。record helpers 与镜像 finalize 中的无根分支退出，重复纯算法复用现有实际所有者，不以新的注入层替代旧重复。冻结测试仍引用部分退役路径，不能声称全仓零引用；本决定部分更新[纯规则归属](../simplification/2026-11-04-dify-helper-ownership.md)和[API 执行契约](2026-11-11-api-v1-execution-contracts.md)，其他事务与取消责任继续成立。

fast 记录的聚合预算为既有省略号预留三字符，避免预算 200 实际输出 203。单记录提示裁剪和其他省略号规则继续由原所有者处理，不用最后切片掩盖预算计算。

## Alternatives considered

- 只把账号加进缓存键可以区分账号，却不能感知同账号的组权限撤销；因此在复用缓存之前检查实际权限。
- 对失效缓存返回 503 能阻止旧内容，却把正常缓存失效变成业务失败；采用一次普通检索，也不从旧内容中筛出伪成功。
- 以 key 再检查 leader 状态可以减少句柄传递，但不能区分同键的新旧任务；使用已经取得的 Future 身份，无须新锁或状态标记。
- 将 API 切到旧服务编排能缩短路由文件，但该编排没有真实生产根且行为不同；保留实际入口并删除无根副本。

## Consequences

缓存命中增加一次实际文档权限查询，metadata 范围内任一无权数据集会明确拒绝。原先绕过权限或配额的请求不再返回旧成功结果；这是明确的安全行为修正，不能称为完全等价的格式整理。没有新增 app 模块、配置或权限实现。

验证使用实际入口和权限表达式的源码，配合受控 Session、行、Future、配额和缓存端口，覆盖成员／数据集／文档／配额拒绝、同键撤权、空缓存、失效后一次 fresh、主与 sibling corpus、旧句柄无副作用、正常发布／拒绝及取消异常身份。没有运行应用测试、真实数据库、锁、事件循环任务、Redis、HTTP 或模型，不把这些离线证据称为生产集成验收。
