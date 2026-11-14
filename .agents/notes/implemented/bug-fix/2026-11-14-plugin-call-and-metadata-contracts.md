# Agent Note: 插件调用尊重签名与同一元数据值

Status: implemented

## Problem

已命名的positional-only参数被放入kwargs，有kwargs时又丢掉必需位置参数。元数据验证用flat字段，而view／identity用dot遍历，同一schema可能读到不同值；合法带dot字段再交str.format会被当作Python属性访问而失败。

## Decision

已有signature适配按Parameter.kind构造位置与关键字参数，函数只执行一次。声明首位的未知必需位置参数保原documents协议，signature不可获取保原三位置fallback；跨positional-only槽只使用其真实声明默认，不猜值或扩大VARargs，不增加第二次试调用。

合同验证、view、identity、retrieval-text及golden这些消费者复用同一_value_from_metadata：完整literal key存在即优先，包括None／False／0，不存在才按dot遍历。它们对同一字段取值一致；reports自身的Mapping reader保持，KG前缀、保留字段、schema、类型和stage／report门控保持。

已解析的合法模板field转换为内部顺序slot，再交既有str.format，只修dot字段与Python属性grammar冲突。原missing／畸形／opening brace／conversion／spec跳过和右括号转义政策保持，不增加新DSL／formatter类或getattr执行。

真实_coerce_kg_event只返回IndexRecord或抛错，去无来源None分支；chunk重复metadata／marker维护点收敛。插件trust、hash、隔离、发布报告与输入范围仍完整保留，不因检查多裁安全边界。

## Alternatives considered

- 捕获TypeError后换另一套参数重试可能掩盖插件内部错误并执行两次，因此在真实签名处绑定一次。
- 给验证和view各补fallback会继续留下两套规则，因此保一个实际reader。
- 为模板设计新formatter可以支持更多语法，但超出已有合同；只把合法字段转为安全slot。

## Consequences

声明签名与schema值在实际调用中一致，显式空值不会落到其他字段。注册表仅排版，资源与schema数据AST保持；原不支持的模板形式没有新增能力。

原失败、修后受控callable与metadata／template代表核对，并做完整源码／差异／最终SHA独立复核。没有载入或执行真实插件、SDK、子进程、OS锁、网络或应用测试，不能由受控函数通过宣称插件整体安全和隔离已集成验证。
