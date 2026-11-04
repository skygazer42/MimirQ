# Agent Note: 消息呈现与反馈结果的生命周期

Status: implemented

## Problem

后端句子引用生成 `mimirq-citation://evidence` 链接，ReactMarkdown 的默认 URL 转换却在自定义 anchor 收到它之前清空该协议，使聊天和历史回答中的来源只能显示文本。可空的 `confidence_score` 又经 `Number(null)` 变成零，把未提供指标的回答标记成证据不足。

打字组件只在动效偏好变化时启动 effect。减少动态效果时，后续流式内容和结束通知都停在初始值；正常动效在一次完成后也不会被新的内容唤醒。

反馈评分失败后仍显示乐观星级；离开消息或更换身份后，旧请求继续提示成功／错误，证据库查询也会在完成时跳转。相同账号和 token 的显式登录不发送范围事件，但仍替换认证会话，单独监听范围变化不能隔离这类迟到结果。

开发模式支持空的 API base，以页面源代理后端请求。引用图片解析直接把空串作为 URL base，导致合法缩略图全部被拒绝；使用路径子串判断又会接受非专用图片路由。

引用 URL 恢复后，实际 AuthImage 依赖的 image-auth-proxy 仍在判断与获取阶段把空 API base 传给 URL 构造器。它因此跳过认证 fetch 并渲染原始图片 URL，JWT 图片请求缺少 Authorization；浏览器与服务端的初始受保护图片 markup 也不一致。

## Decision

消息 owner 只为能被现有引用解析器识别的 anchor `href` 保留私有协议，其他 URL 继续调用 ReactMarkdown 默认转换，普通链接和图片还经过原安全 helper。原始 HTML 仍跳过；图片不会因引用协议而获得额外许可。置信度只接受有限数值或非空数字字符串，缺失和无效值不产生徽标，真实零值继续显示。

打字组件保留现有 token、Unicode 码点、空白、换行和标点停顿规则。正常动效只唤醒已停止的循环，追加内容不会重启活动计时器；减少动态效果时按每次内容／流状态变化同步全文，并在当前周期结束时通知一次。偏好切换和卸载继续清理旧计时器。

每个消息实例保留一个本地反馈 owner。卸载或现有身份范围事件使旧 owner 失效；事件同时清空本地反馈显示。评分、分类、证据库和回归操作在开始时捕获认证会话 revision，只有 owner 和 revision 都有效时才发布结果或跳转。相同范围的显式登录也能使旧结果失效，正常 token 轮换仍属于原会话。旧 finally 只释放原 owner 的忙状态，不清除新 owner 的操作；静默换会话后，原评分恢复到提交前的确认值并释放自己的忙状态。

评分和 expert 操作的同步忙标记与现有禁用状态属于同一个 owner，阻止 React 提交下一次 render 前的重复原生点击。失败评分恢复上次确认值，成功显示 API 接受的评分。持久化 assistant UUID 限制、评分与分类字段、回归转换参数及证据库路由保持。

引用图片以配置的后端地址解析；空 API base 使用当前页面源。结果必须与有效后端同源，并以该 base 下专用的 `image/` 或 `image-url/` 路由开头。配置中的路径前缀保留，data、blob、外部源和其他后端路径仍拒绝；认证图片代理继续由原 owner 处理。

实际认证图片 owner 的两处 URL 解析复用同一个私有 resolver，以配置的 API base 或真实浏览器 origin 为 base，只在确定 HTTP(S) 后端 origin 时分类认证请求。没有浏览器 origin 时不构造 localhost 或其他占位地址。normalizeAssetUrl 保持原文，服务端仍使用 env 的已有 API 地址；受保护图片在服务端与浏览器初始 render 都不输出原始 img。原文档图片／下载路由判断、认证头、缓存范围、并发去重、blob 撤销、远程图片 opaque mint 和生产失败返回规则保持。外部图片的认证头只发送给前端自己的代理入口，不直接发送给外部 URL。

## Alternatives considered

- 把 Markdown URL 转换全部关闭，能一次恢复自定义协议及其他 URI，但会扩大所有链接和图片的许可范围，因此只保留现有解析器识别的引用 anchor。
- 让主打字 effect 依赖每次流内容变化，实现更短，但会在每个分块到达时重置活动的 token／标点延迟，因此保留循环并只唤醒空闲状态。
- 只监听身份范围事件，能复用已有页面清理；真实 auth-storage 允许相同范围的显式登录保持事件静默，因此异步发布还核对既有 session revision。
- 给反馈 API 增加 AbortSignal，可以减少离开后的传输；当前 API 没有这一契约，取消也不能撤回已接受的写入，因此本批只在消息 owner 控制结果发布，不修改 API／auth／store。
- 保留图片路径子串判断，能兼容任意前缀，但也会接受上传路径或其他路径中恰好出现的路由文字，因此按实际配置的 base 前缀验证专用图片路由。
- 只修引用 URL helper，能恢复合法地址，但真实 AuthImage 的后续代理判断仍失败，不能完成 JWT 图片预览。因此修正在实际认证 URL owner，保留 AuthImage 的现有资源与渲染接口，不绕过它另发请求。

## Consequences

可见消息内容、引用行为和反馈状态与实际数据／操作归属一致；增加的运行时状态仅属于单个消息实例，不建立共享管理器或新缓存。API 请求可能在离开后完成，已接受的服务端写入不会回滚。

ChatArea 和 History 都以消息 ID 作为 key，因此生命周期验证使用实际卸载、身份变化和静默同账号登录，不依赖真实调用者不存在的同实例换 ID 情形。证据范围、预览 anchor、来源上下文、预取去重、排序与数量以及公共 props 保持。证据弹窗、代码高亮和 Markdown 安全 helper 经完整源码复核后保留原实现。

Vitest 使用真实 React DOM、ReactMarkdown、Radix 弹窗、认证存储和 env 解析，在 API／图片代理及动效展示边界替身下复现旧行为并验证修复。活动计时器的标点停顿、减少动态效果的连续内容、合法 token 轮换、危险协议拒绝、原始载荷与导航参数有对照验证。浏览器、服务、Python 和真实身份提供方未运行；本记录不声称真实渲染帧、响应式布局或跨标签端到端已验证。

活跃笔记检索只命中相邻决定：[聊天 Hook 的会话与流式结果归属](2026-11-04-chat-hook-stream-ownership.md) 持有发送／历史加载的请求边界，[OIDC 刷新结果的会话归属](2026-11-04-auth-refresh-session-ownership.md) 持有认证 revision 与凭证写回。它们与本批消息呈现／反馈 owner 独立，本记录消费其既有接口，不吸收或修改原决定；当前树没有 proposed／rejected 消息呈现提案。

完整 owner 范围包含 image-auth-proxy；AuthImage、env、authenticatedFetch、认证存储和预取调用方保持只读的相关契约检查。真实消费者回归使用实际引用 helper、AuthImage、auth headers／storage 和 authenticatedFetch，仅替换 next/image、global fetch 与 object URL 浏览器边界，覆盖开发／生产、相对路径、外部代理、拒绝响应以及服务端／浏览器初始 markup。该静态服务端 render 不启动服务，也不等同于浏览器 hydration 验收。
