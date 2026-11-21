# Agent Note: RAG 文本的归一化边界与实际类型

Status: implemented

## Problem

别名扩展已经过滤空键、空别名和相同别名，后面的私有函数重复判断。实体匹配也反复转换已清理的候选与正则 Match 的原生偏移。Store 工厂通过反射读取实际 Settings 字段，返回类型却没有说明真实资源。

## Decision

别名规则仍在 `coerce_query_aliases` 和 `_unique_alias_values` 处理原始值。双向配对、包含判断和替换直接消费该边界产生的非空、不同字符串；保留 ASCII 匹配、去重顺序、原始数值选项、截断与预算。

实体候选仍在 `_normalize_candidates` 转换、清理和过滤。内部判断直接使用已归一化表面；`re.Match.start()` 和 `end()` 是当前完整匹配的有效整数范围，后续直接构造等长空格，不再转换和钳制同一范围。EntityMatch 保留冻结数据类，分区 key 直接读取实际构造的非空值。没有任何已跟踪消费者的私有 regex 常量退出，实际匹配表达式保持。

Store 工厂直接读取两个已声明的 Settings 字段，保留原 bool、字符串归一化与默认值。资源注解使用实际 BaseStore；SDK 类型只在 TYPE_CHECKING 导入。启用判断、单例缓存、首次 require_dependency、缺失类错误、后端选择和日志保持。

结构化输出生成器继续持有实际 LLM 状态，仅补充构造函数 None 返回注解。其 schema、运行时 Union、提示词、解析、模型调用与既有失败策略保持。Pipeline 与 trace 的数据合同原文符合约定，保留原字段、隐私限制和 Pydantic 行为。

Frontmatter 标签的字符串拆分、列表清理、大小写去重与长度／数量上限由 `app.rag.preprocessing.frontmatter.normalize_frontmatter_tags` 持有。治理 processor 和 API clean preview 调用同一函数；空标签仍表示为 `None`，原 title 提取、frontmatter strip 和 preview metadata 形状不变。

## Alternatives considered

保留内部重复转换可以接受更宽的私有输入，但实际调用链只传入上述构造结果，原始输入已经有明确归属。去掉边界转换则会改变未知 JSON、候选和配置值的处理，因此继续保留。

在工厂顶层导入 BaseStore 可以避免前向注解，但会改变关闭功能时的可选依赖加载时点，因此类型导入保持静态。

## Consequences

主流程直接消费实际内部值，接口模型和有状态资源保持各自职责。匹配优先级、位置、文本长度、别名顺序、上限、输出字段及缓存行为不变。未来若改变候选生产者或传入外部 span，需要重新核对这些内部保证。

活跃笔记仅命中 KG query expansion 的另一条检索范围与实体服务链，未持有本篇的本地别名或实体匹配函数，不作替代。共享标量转换处理其他值域，本篇不修改其默认和异常策略。

验证使用六个完整原始文件、限定改动后的整模块 AST、实际 Settings／SDK 源码与内部生产者、静态调用形状、Ruff 和笔记门禁。没有添加、修改或运行 Python 测试，也没有导入或执行业务、正则、SDK、模型、数据库、CLI、输出生成器或真实数据；静态证据不代表实时检索结果已经验收。
