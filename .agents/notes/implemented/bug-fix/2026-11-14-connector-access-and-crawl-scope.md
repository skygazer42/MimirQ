# Agent Note: 连接器权限、完整来源与爬取会话归属

Status: implemented

## Problem

Confluence 的 JSON 查询兼容分支同时包住 ACL 写入。写失败会进入第二次查询和更新，失效 Session 的后续异常还能覆盖原错误。DB resume 被 URL 总开关挡住，而 resume 与 scheduler 没有沿用直接启动 DB 连接器已有的 settings.write 权限。

来源清单接受 10001 项，reconcile 却只保留前 10000 项，仍属于来源的文档会被判为 stale 并禁用。sitemap 重复 URL 也先占用 max_pages，挤掉后面的唯一页面。HTTP 爬取借用全局外部客户端，其 Cookie jar 能在不同 fetch 或租户之间延续。

## Decision

Confluence 按实际 bound Session 的方言预选 PostgreSQL JSON 谓词或既有有界 Python metadata 扫描，再进入唯一 ACL／provenance 循环。租户、数据集、归档、禁用、页面、base URL 和 space 条件保持。查询和 ACL 主写入失败直接传播，不在失败事务里重新查询或重复应用；原可选 provenance 旁路保留。

resume 先确认成员、run 和数据集权限，再用已有 connector enable validator 判断真实 URL／DB 开关。DB resume 与 scheduler 复用直接启动的 settings.write owner 和文案。scheduler 在 claim 和创建 run 前检查，只有明确的 403 沿既定逐配置 skipped 政策结束，数据库错误及其他 HTTP 错误仍传播。retry_failed_run 只重试失败 URL，保留原 URL 开关及整段 AST，不把 DB resume 的规则套进去。

reconcile 使用完整来源集合归一化、去重和排序，退出没有真实调用需求的私有 max_items 参数及静默截断；响应样本上限与文档查询／事务责任保留。sitemap 对已通过过滤和 robots 的规范 URL 保序去重，再占 max_pages；保 40 个 sitemap hop、每目标 SSRF 检查和原错误收集。

HTTP 与 HTTPS 客户端都由单次 fetch 拥有，在同一真实 origin 内复用，换 origin 关闭并创建独立客户端，最后由 fetch 收尾。不读取或清空全局 Cookie jar，也不借 SDK 私有 transport。HTTP 的原配置选择与 request-ID hook 使用现有实际所有者；HTTPS 的原设置、connect_url、Host／SNI、重定向逐 hop 校验、跨 origin 敏感头规则保持。

三个相近文档查询复用一个实际 query owner，专属 source URL／source ref、config、排除文档和数量条件仍由各业务函数持有。已归一化模式与已构造 state 的消费端不再重复探测；不建立新的调度 context 或权限包装器。本篇延续[终态与来源设置](2026-11-14-connector-terminal-state-and-source-options.md)的事务责任，只修正这里的真实入口。

## Alternatives considered

- 保留大 try 可以兼容更多失败，但会重复权威写入并掩盖原异常；方言预选只处理已知查询差异。
- 对超过清单容量的请求直接拒绝能阻止误删，但状态入口原本接受完整清单；使用完整集合更符合 reconcile 的来源含义，不增加另一套阈值。
- 清空全局 Cookie jar 改动较少，却会干扰其他并发请求；每个 fetch 拥有会话，不改变共享 pool 的其他消费者。
- 用全局 transport 保留连接复用需要额外的 SDK 私有依赖和关闭协议；本次不增加这样的共享资源层。

## Consequences

权限不足的 DB 启动不再创建任务，ACL 错误不再被查询重试覆盖，完整清单不会因为显示容量误删来源，重复 sitemap 项不再浪费页面预算。resume 的错误时点和部分拒绝结果有意变化，不声称完全等价的风格整理。

HTTP 不再跨 fetch 复用连接池，也不再受原全局外部客户端连接上限约束，仍使用 crawler 的并发预算。这会增加连接创建成本；同源 Cookie 流程与跨源隔离的证明来自受控客户端，真实传输、服务器 Cookie、SDK 关闭和重复取消仍未做集成验证。

原错误与修后证据保留，独立复核使用实际入口和权限／查询源码，配合内存 Session、文档、角色与客户端端口。没有运行应用测试、真实 HTTP／DNS、DB、Redis、SDK、业务文件或锁线程；非 PostgreSQL 的兼容路径是明确预选，不宣称所有数据库上与旧错误回退完全等价。
