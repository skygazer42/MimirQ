# Agent Note: 执行预算与子任务在拥有者处收口

Status: implemented

## Problem

Chain先判断condition，step.execute又判断一次，状态性谓词可能记录已执行却没有调用步骤。Parallel的fail_fast提前返回错误时兄弟任务仍运行，公开Multi流提前关闭也未确定关闭内部持有子任务的生成器。

分页content在剩余不足1000字符时重新套公共最小值，又在预算之外加页前缀。流式检索的零non-MQ预算、KG零注入上限、成功evidence提取后的token限制、buffered附加片段和长查询裁剪去重也存在已复现边界错误。

## Decision

Chain在自己的should_execute通过后调用自己构造的WorkflowStep.func；独立execute仍保原签名与条件规则，不增加check_condition开关。fail_fast显式拥有按输入顺序创建的Task，失败／取消时取消并等待兄弟任务退出，再按原异常／失败Result返回；已取消任务不重复cancel，创建失败关闭未提交coroutine，non-fast路径保持。不新增TaskGroup异常组、shield或deadline。

公开engine→agentic／multi→阶段生成器使用aclosing，确保自研持有的生成器和子Task在协作式关闭前结束。直接取得的chain.astream外层迭代器也明确关闭；当前LangChain-core内部存在裸async-for转发，不能从外层fake finally推断隐藏模型或HTTP迭代器已同步最终化。不修改SDK私有层或重写链，真实库内部资源收尾限制明确保留；取消await也不等于停止阻塞工作线程。

MCP默认客户端接收既有TIMEOUT／MAX_RETRIES配置，保零重试原class含义。实际main资源栈登记close_mcp_client，只关闭已经创建的客户端，不调用getter、不重置registry；正常退出、失败startup均覆盖，原回调逆序保持。

单文档入口保原公共长度floor和UUID→scope／ACL→page→raw limit错误优先级。分页先预留页前缀／分隔，再让同一实际读取／组装所有者按正剩余量处理，可低于1000；returned_chunks只计实际输出，truncated与页截断一致。不在最后slice伪造预算或计数，不改变权限／SQL／Session作用域。

non-MQ在append前检查预算；KG公开零上限不注入也不额外取数；成功evidence提取后仍执行既有正token限制；buffered图片／附录只在最终全文交付，非buffer和claim-check原路径保持。多查询按最终normalize／400字符加省略号的实际表示去重，保原query排除、数量和模型prompt。

## Alternatives considered

- 在Chain.execute添加绕过条件flag能保双层接口，但当前步骤由Chain直接构造且没有实际自定义execute消费，因此让Chain负责一次判断，不加公共开关。
- 仅把父调用标为失败可以更快返回，但子任务会继续改状态；拥有者等待清理才能消除原故障。
- 最后裁分页字符串更短，却会把未输出块计入returned_chunks并隐藏权限／错误顺序变化，因此在真实读取预算处处理。
- 为SDK隐藏生成器补私有关闭逻辑可能显得更彻底，但没有稳定公开资源协议可依赖，不构造推测性兼容层或伪称已证明深层关闭。

## Consequences

有状态谓词只执行一次，失败／提前关闭的自研Task不脱离拥有者，预算和buffered事件不再被重复默认或片段交付破坏。这些是明确的输出、排序或生命周期变化，不能宣称所有结果逐字不变。

timeout_sec尚不执行截止时间、RAGAS当前固定两指标、corrective阶段原scope重估政策维持原功能并明确记录，不以风格重构补新产品语义。有限原公开AST／Fake任务、分页、模型／回调与错误身份对照通过，再独立复核最终源码SHA。没有真实SDK／HTTP／DB／模型／线程或应用测试，不能据此承诺实际端到端取消、供应商质量和数据库并发通过。
