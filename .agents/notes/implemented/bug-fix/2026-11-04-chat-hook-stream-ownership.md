# Agent Note: 聊天 Hook 的会话与流式结果归属

Status: implemented

## Problem

SSE token 的内容原先按分块 trim，独立空格、换行和缩进会丢失；重复 done 事件也会重复插入回答并通知会话。后端 token 载荷保留原始文本，因此分块边界不应改变答案。

清空消息、切换会话、重置或卸载后，旧 SSE callback、恢复读取和普通回退响应仍可能发布内容、会话 ID 或错误。历史加载在清空消息后也能恢复旧内容；身份变化清除了查询缓存，却没有清除 Hook 自己的消息和活动请求。已接受的 SSE error 还会进入普通 chat 回退，重放同一提问。

初始会话链接只设置会话 ID，没有加载历史；组合 Hook 的导航 callback 又依赖每次 render 新建的 session/stream 对象，使真实 ChatArea 的导航 effect 随加载状态重复启动。清空消息时 messagesRef 要等 effect 才同步，也会让同一事件中的后续发送读到旧历史。

## Decision

每次发送继续使用现有 AbortController 作为请求身份，并核对挂载状态、既有 auth session revision 和 cache scope。身份接口来自原 auth-storage 所有者，不新增 token 状态。事件、onOpen、恢复／回退完成及错误只发布给仍持有该 controller 的请求；旧 finally 也不能清除新请求的 RAF 或 loading。

用户 stop 与导航丢弃分开：stop 保留已流出的部分答案；clear、reset、loadConversation、auth scope 事件和卸载先撤销发布归属，再终止传输并清除暂态。恢复读取有独立 signal，避免正常长超时中断 SSE 后无法读取已落库回答；用户 stop 或撤销归属会停止恢复等待与后续读取。现有四次尝试、500 ms 间隔、40 条消息窗口及 request_id 匹配保持。

已接受的 SSE 请求报告 error 时直接呈现原错误，不再发第二次 chat 请求。只有尚未接受的流式请求仍走现有普通回退。done 之后不再处理该流的后续事件，会话通知按当前已确认的 ID 去重。token 的 string 内容直接拼接，未知内容仍返回空串；其他原始事件与指标的边界检查保持。

session 保留原加载请求序号，并在 clear/reset/auth 变化／卸载时使旧加载失效；完成时还核对原身份 revision/scope。clear 和历史提交同步更新 messagesRef。初始链接在挂载时加载一次；后续 URL 导航继续由现有 ChatArea 驱动。组合 Hook 只依赖稳定的具体函数，错误与会话 callback 通过 ref 更新，导航 effect 不再因匿名错误处理函数而重启。

## Alternatives considered

- 只调用 abort，能取消支持信号的 fetch；但已进入队列的 callback、无 signal 的 getMessages 和忽略取消的响应仍能完成，因此结果发布还需原请求归属。
- 导航复用用户 stop，能保留部分回答；但导航后部分回答属于已离开的会话，不能插入新会话，因此导航先撤销归属，只有明确 stop 才保留部分内容。
- 对所有 SSE 失败都回退到 chat，能掩盖流式兼容问题；但请求已接受后可能已经产生后端写入，重发会重复操作，因此保留接受前的回退并停止接受后的重放。
- 给聊天重建通用状态管理器或全局查询 store，可以统一异步状态；当前缺陷集中在五个现有 Hook 的生命周期，使用既有 controller、请求序号和 auth 边界即可，无须迁移架构。

## Consequences

API 载荷、查询 key、历史最后十条、检索范围、结构化输出和记忆字段、短／长超时保持。当前请求错误保留用户消息和原错误；普通回退与明确 stop 保留原体验。输入草稿仍由 ChatArea 持有，本改动不写其输入状态。

已发送的后端请求不会因导航而回滚。getMessages 仍沿用原 API 参数，没有传输取消接口；进行中的读取可能完成，但取消后不再发布或继续尝试。新初始链接读取使用既有查询 key/cache 行为，不另建缓存。身份变化监听只消费现有事件，不修改 auth API/store 所有者。

真实组合 Hook、session、stream 和恢复路径的边界测试复现旧结果发布、接受后重放、token 丢失和初始历史缺失；保留短／长超时、普通回退、停止部分答案、不重复发送与恢复预算控制。最终数量与命令在本批报告记录；没有启动浏览器、服务或 Python。

活跃笔记仅命中[OIDC 刷新结果的会话归属](2026-11-04-auth-refresh-session-ownership.md)，它持有传输层刷新与凭证的 revision/scope 边界；本记录消费该接口并约束 UI 结果，不替代原决定。完整源审查限定于五个 Hook，ChatArea、API 和 auth 所有者只做相关调用契约取证。
