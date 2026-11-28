# Agent Note: 算法设置的输入与操作归属

Status: implemented

## Problem

RTBF 允许零次重试，但输入经 parseInt 后又使用 || 1，使零变成一次重试；空值、带尾缀和小数也会被改成默认数或截断后发送。请求期间输入的新工单会被旧响应覆盖，同一 render 前的两次点击还能重复发出请求。卸载或替换认证会话后的结果仍会通知当前用户。

行业规则的载入通过会变化的 Query observer 读取返回值。切换规则集、清除查询实体或在等待时编辑 JSON 后，迟到结果可能覆盖当前草稿，取消读取也可能显示为成功的空规则。旧保存完成还会在新认证会话中失效查询。LTR 注册会在父逻辑完成后清空文件对，但两个原生文件输入在上传期间仍可修改。

后端 API 和实际 reranker registry 支持 aliyun、late_interaction 两个持久化别名，前端共享 normalizer 却把它们当作未知值回退到 llm。RAG 三个数字输入还按字符串前缀读取指数形式的合法数值。

## Decision

RTBF 以字符串保留两个数值草稿，在发起动作时校验十进制整数及后端原有范围：文档数 1-1000，重试数 0-10。无效内容保持可见并显示错误，不发送请求；初始值仍为 100 和 1。现有私有动作函数用挂载归属、认证会话 revision 和同步忙标记发布结果，旧 finally 不写已卸载实例。工单只在当前内容仍等于提交时的草稿时自动回填。

行业规则继续使用原私有动作函数和现有 QueryClient。动作捕获原查询实体、规则集访问和认证 revision；有效保存只失效原 key，当前访问才接收编辑器更新、结果和提示。规则集访问使用实际名称建立，layout effect 在 commit 时同步引用，不依赖 callback 身份。载入只替换尚未改变的各个编辑器字符串，保留等待期间输入的内容；查询实体已移除时不发布默认空成功。

每次新的显式动作先通过现有 QueryCache.build 获取或建立当前实体；build 本身不读取网络，也不写默认成功数据。这样缓存空闲时被 QueryProvider 清理后，不需要依赖一次额外 render 或输入改动才能恢复载入／保存／预览。已经在途的动作仍持有原对象，原对象移除后即使同 key 建立新实体，也不能再次发布或失效新缓存。

原始 JSON 解析、空编辑器清空含义、glossary／patterns／intents 单节替换、嵌套 false／zero／null、API 错误及原失败提示保持。没有全局草稿库、请求 controller、共享 context 或新的传输接口。

共享 reranker normalizer 按实际后端 registry 补齐两个别名。其默认未知值仍回退 llm，现有实验页面调用不变；新增的可选 fallback 仅让 RAG 保留自己原有的未知原始值策略。显示已知别名不会自动写回配置。三个数值控件读取完整字符串，不改滑块、阈值、限额或空／零语义。

LTR 只在父级明确的 uploading 状态禁用两个文件输入，沿用现有显式 reset key 管理原生文件生命周期。父 callbacks、multipart 字段、注册／激活／回滚及错误显示策略保持，不新增 Promise 结果协议或修改父保存 Hook。

## Alternatives considered

- 数值状态直接归一化能让提交更短，但会吞掉合法零和无效原文，因此只在 RTBF 动作边界校验，保留草稿。
- 载入期间禁用整个行业编辑区可以避免覆盖，但会阻止准备下一次输入；比较实际草稿并核对规则集访问即可保留用户编辑。
- 只比较规则集字符串能隔离不同名称，却识别不了离开再返回、同 key 查询实体重建和静默认证会话替换，因此同时保留实际访问、实体和 revision 的归属。
- 要求显式动作开始前必须在缓存中找到实体，能缩短归属捕获，但空闲清理后仍挂载的 Query observer 不会立即重建实体，会吞掉新的用户操作。因此动作建立新实体，只有已经开始的旧操作才按其原实体退休。
- 在 RAG 建本地别名表能局部修复显示，但会与实际共享 normalizer 和实验页面分叉，因此在真实 helper 内补齐别名，并明确调用方的未知值 fallback。
- 重做 LTR 异步确认协议可以扩展行为，但当前缺陷只在上传时还能改文件，使用已有 uploading/reset-key props 即可修复，不跨入父级操作所有者。

## Consequences

五个 owner 完整审查；四个组件的 props、API 方法与字段、权限、成员读取 500 上限、RTBF 两步删除模式、RAG／模型预算及样式方向保持。共享 helper 新增可选参数向后兼容，原单参数实验调用的未知值政策保持。服务器已经接受的操作不会因 UI 离开而回滚。

真实 React DOM、QueryClient、Input／Select／Radix 确认与原生文件对象验证原缺陷和保留行为，仅替换 API、通知和无关 GovernanceOpsPanel 叶子。父页面／Hook、API／DTO／auth／store／document／viewer 与另一批治理父组件只读取相关契约，不作为完整 owner 关闭。浏览器／服务器／Python／模型／数据库未执行。

活跃笔记审计命中相邻的[认证会话归属](2026-11-04-auth-refresh-session-ownership.md)。本记录消费其已有 revision 边界，持有独立的 RTBF／行业编辑／LTR／provider 决定，不替代或修改原记录。
