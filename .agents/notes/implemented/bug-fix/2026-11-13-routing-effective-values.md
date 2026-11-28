# Agent Note: 路由约束比较实际生效值

Status: implemented

## Problem

意图策略的覆盖值可能把top_k20／threshold0改为1／0.5。profile计算出应恢复20／0后，只与原始输入比较，因恰好相等而不写回，留下违反profile的覆盖值。

模型规则在去重之后才截断64字符，两个长词会变成相同token，却保留min_match2；直接预测原模型与先归一化再预测的结果不同。scope分数的metadata路径用or选择字段，显式relevance_score0会被次级正分替换。

## Decision

profile先绑定当前已采用的override／base值，contract结果与这些实际生效值比较，再写必要修正。支持的profile、原有or选择、阈值公式及没有变化时的字段省略保持。

token先按实际64字符表示截断，再按同一表示执行原ASCII casefold／非ASCII去重，保24项上限、min_match裁剪、confidence与weight规则。归一化后的模型与直接原模型采用同一有效token集合；原生产route已预归一，不能把原问题描述为已证实的route漏召。

metadata中的relevance_score／retrieval_score／score采用first-non-None选择，与同函数已有顶层规则一致。显式0／False保留，None或缺失继续选择次级字段；顶级score／relevance优先级、数值转换／异常政策、阈值、tenant／dataset过滤保持。

policy与orchestration的scope实现有不同依赖和原始分数边界，仍分别持有，不为相似名称合并重依赖。必须召回、显式空列表与None继承、二次召回、路径沙箱和准入规则不因风格清理削弱。

## Alternatives considered

- 仅在下游消费时再次套profile可以隐藏未纠正覆盖值，但会让路由输出与实际执行不一致，因此修正实际覆盖所有者。
- 在预测时反复归一化能偶然消除长词重复，但不能保证公共归一化幂等；在形成有效token表示时去重。
- 将0视为缺省可以继续用一行or链，但0在评分域有真实含义，因此只以None决定是否缺失。

## Consequences

违规覆盖值被纠正，长词规则具有一致的有效集合，scope的零分不再变成其他字段的正分。这些是明确的行为修复，不能宣称所有旧输出逐字不变。

原始公开流程与受控假端口保存失败证据，修后核对普通输入、profile字段投影、raw／已归一模型、0／False／None分数和真实优先级。没有运行实际模型文件、向量检索、SDK、网络、数据库或Python应用测试，不能据此证明实际召回质量或准入业务回归。
