# Agent Note: 聊天输入、语音与摘要操作的生命周期

Status: implemented

## Problem

聊天输入框把输入法确认候选词的 Enter 当作发送，跟进问题提交与延迟 autorun 还会清空不属于该请求的现有草稿。同一挂载实例接受第二个 autorun 提问时，永久 boolean 标记会阻止新意图。用户明确修改检索设置后，迟到的系统默认值也可能覆盖其选择；无效自定义元数据 JSON 虽然显示错误，却会丢弃筛选条件并继续发送。

语音识别实例原先随 onSend 函数重建，没有在关闭或卸载时停止。识别事件只保存最后新增的 final 片段，点击停止又立即发送，忽略停止后才到达的最终文字；不支持语音时，界面仍显示正在监听。

摘要更新和清空完成时引用最新 conversation key，会把 A 的结果写到 B，或在缓存清理后写回旧摘要。清空确认使用立即关闭的 Action，不能等待删除、保留失败上下文或阻止重复请求；刷新、更新、清空也可以相互覆盖。加载失败与空摘要的显示相同。

## Decision

ChatArea 沿用 submitMessage 作为发送入口，统一只清除与已提交文本相同的草稿，移除各调用方重复清空与高度赋值；textarea 高度继续由既有 inputValue effect 推导。IME 的 isComposing 与兼容 keyCode 229 不触发发送。autorun 记录当前已消费的文本，提示消失时重置，新文本可以提交一次。迟到默认值只用于未修改设置；现有自定义 JSON 校验出错时保留草稿并阻止发送，修正后的合法对象仍按原载荷提交。

语音实例由每次打开的 overlay 持有，onSend 通过 ref 更新；关闭和卸载先移除事件归属、解绑处理器，再 stop。final 文字按浏览器累计结果完整投影，用户停止后等待 onend 再提交一次。停止中的按钮禁用；关闭、错误和自然结束不自动提交。能力缺失与识别失败有明确反馈，canvas 动画与现有中文、continuous、interim 选项保持。

摘要动作在点击时捕获 conversation ID、查询实体和视图访问。实体仍在缓存时只更新原 key；实体移除后不再写回。提示与确认关闭只作用于原视图，busy 则绑定实际会话，离开返回同一会话也不能重叠修改。读取加载时禁用修改，修改时禁用手动刷新和冲突动作；后台查询 key、缓存与重试配置保持。

更新与清空各有稳定的 TanStack mutation key，组件通过 useMutationState 订阅该动作的所有 pending 操作，再按当前 conversation ID 和仍有效的原查询实体推导 busy。最新 useMutation observer 只代表最近一次调用，无法覆盖 A 更新中转到 B、启动 B 更新后再回到 A 的情况。订阅不随当前会话改变筛选条件，因此仅导航也能立即得到正确忙状态；A 完成后即使 B 仍在进行，A 仍可清空。现有 mutation cache 是唯一待处理操作来源，不另建 ref map 或串行化不同会话。

QueryProvider 明确禁用 focus refetch，并启用 reconnect refetch。缓慢修改开始后，过期摘要仍可能在重新联网时自动读取；如果该 GET 最后完成，会覆盖已成功的更新或清空。因此，修改成功后在发布缓存之前使用 QueryClient.cancelQueries 取消原 key 的读取，await 之后重新核对原查询实体，再写入结果。这里不依赖修改开始时取消，也不关闭重连读取策略；未接入 signal 的网络 GET 可以继续完成，但 Query 取消后不能再发布旧结果。

清空确认在该所有者内使用已有 AlertDialog/Button primitives 受控呈现，不新增公共 wrapper。删除中保留确认与对象，禁用确认／取消及外层关闭；成功先写缓存再关闭，失败显示原错误并允许重试。该局部实现不改变共享 ConfirmDialog。读取错误单独显示，空摘要仍保留原空态。

## Alternatives considered

- 每个发送入口各自判断并清空输入，修改位置局部，但同一个请求与草稿的关系会继续重复，因此由现有 submitMessage 统一持有；不新增发送管理器。
- 继续依赖 onSend effect 重建识别器，能获得最新 callback，但真实父组件每次 render 都传新函数，会泄漏仍在工作的识别器，因此只更新 callback ref，资源随打开状态管理。
- 点击停止立刻发送当前 transcript，响应更快，但浏览器在 stop 后仍会交付最后的 final 结果，因此等待原生结束事件。关闭与错误保留为取消边界，避免误提交。
- 扩大修改共享 ConfirmDialog 可以统一全站异步确认，但影响超出本批五个所有者；本处使用既有 primitives 完成当前动作生命周期，共享组件及其他调用方不被迁移。
- 只检查当前会话字符串，简单且能隔离不同会话，但同 key 查询可以在身份范围变化后重建，因此缓存写入还必须匹配实际查询实体；不另建身份或摘要数据源。
- 从最新 mutation observer 的 variables 推导 busy，改动更小，但它在启动 B 后会失去 A 的待处理状态；只按当前 key 调整 useIsMutating 筛选，在现有 TanStack 版本中还可能等下一次 mutation cache 事件才重算快照。因此使用稳定动作 key 的全部 pending 快照，再在当前 render 按原会话和实体选择。

## Consequences

五个 UI 所有者完整审查，ChatPageClient 与 SlashMenu 保持原文，三个行为所有者调整。公开 props、API 方法与载荷、检索候选完整读取、路由、检索／记忆预算、消息展示数量和样式方向保持。无效筛选的发送、IME、草稿、autorun、语音和摘要生命周期是明确修正的行为。

已发出的摘要后端操作不会回滚；关闭或导航仅撤销当前视图提示，原有效查询仍可接收结果。语音继续使用既有 webkitSpeechRecognition 接口，没有引入录音上传或外部语音服务。自然结束保留已识别文字，但只在明确 stop 请求后提交。

验证使用实际 React、QueryClient、Radix 控件及本分支已有聊天 Hook，在 API 和浏览器语音边界提供替身；canvas 绘制与视觉叶子不作为浏览器验收。原五个源文件上的最终用例复现失败，修复后验证与数量记录在本批报告。浏览器／服务器启动仍被既有自动审核阻止，本批没有重试，没有 Python 或保护范围源文件修改。

活跃笔记按 ChatArea、语音、会话摘要及确认弹窗检索，没有发现相同 UI 决定。基线 84ce6083b 不包含单独审查的聊天 Hook fba 提交；本批不修改 Hook，组合版本由控制者在集成后独立验证。
