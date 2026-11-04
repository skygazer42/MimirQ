# Agent Note: 结构化分块只消费既有解析结果

Status: implemented

## Problem

格式识别、章节和记录策略已经在本模块生成位置、计数、标题层级与布尔结果，下游又重复使用 `int`、`str`、`float` 或 `bool`。这些内部值与原始 JSON、SDK `start_index` 以及公开构造参数属于不同边界。Auto 的密度计算始终返回完整字典，但调用方仍把缺键和非数值当成正常结果。

TOML 和 KV 策略对每个没有条目的 section 已执行 fallback，循环后又在全文没有条目时重复追加全文。Markdown Q/A 的两个 raw f-string 把 `{1, 6}` 当作 tuple 插值，未生成注释要求的 Markdown 标题量词。

## Decision

62 个格式、识别和分派所有者继续保留现有配置类、framework 类、私有 helper 和选择优先级。只删除实际生产者已明确生成的标量重复转换；构造参数、原始元数据、JSON／正则捕获数字和外部 splitter 的 `start_index` 保留原有解析。Auto 直接读取完整密度字典，计算式的 float 运算、阈值、bounds、overlap 和原因标签保持。

构造函数声明 `None` 返回，书籍标题回调使用两个真实数字解析函数的 `Callable` 契约，SmartCode 单元返回值声明实际三个字符串的 tuple。它们描述当前职责，不改变类、方法、导出或参数默认值。

质量、上下文、角色、布局和 provider wrapper 的 12 个所有者沿用同一边界。Counter 直接消费已 strip 且非空的字符串 key，评分只删除长度、算术和本地分数的重复转换；两个 Jaccard 的后置空 union 分支由前置集合条件排除。角色分类仅删除已经被前面相同 TABLE 条件返回覆盖的末尾分支，其他优先级保持。

SDK Document 的 `id`、semantic chunker 自己构造的 unit，以及 PDF 解析完成的坐标、偏移和长度直接使用实际字段。PDF 原始 tag 解析、坐标数值归一化和舍入、metadata hint 的异常边界继续保留。LlamaIndex 外部 node／relationship 反射、ID 和 offset 转换保持；矩阵只读取声明的 Settings bool 与本地 fixture 值，临时文件、外部结果形状、flag 恢复和计时政策不变。推荐标签与 Jina wrapper 完整源码保持。

TOML 和 KV 只删除无用的条目标记与末尾第二次全文 fallback。没有标题时 section 覆盖全文；有标题时按递增偏移构建前言和各节，每个非空节仍走原有记录或 fallback 分支。表名／节名、offset、元数据和顺序仍由每节的原路径产生。Markdown Q/A 仅把两个量词写成双花括号，生成字面 `#{1,6}`；其他前缀、空白、匹配顺序和 chunk 元数据保持。

## Alternatives considered

在输出追加去重层可以隐藏重复 fallback，但会改变重叠块或有意重复记录的含义；直接删除重复调用能保留原始 section 语义。为 Auto 和 Manuscript 新建统一分派器可以合并相似代码，但它们的策略顺序、policy-manual 支持和自适应行为不同，本批保留这些业务差异及现有检测 patch 目标。

把构造参数或 SDK 元数据也当成已校验值可以删更多转换；实际边界仍可能返回原始值，因此仅收窄已经追溯到本模块生产者的转换。不为私有小方法新建文件，也不增加 manager、Context、依赖或兼容层。

## Consequences

TOML／KV 的无条目文本只经过原有每节 fallback，Markdown 标题形式 Q/A 可以到达预期识别量词。位置、chunk 顺序、稳定 ID 和 hash 种子、metadata key 与复制政策、分派优先级、外部 provider 降级、日志和异常规则保持。

`stacktrace._infer_kind` 的 Node 分支被前面的 Java frame 条件覆盖。语言分类需要新的区分规则，本批按已确认范围保留该完整函数和现有标签；后续修复应先确定 Java 与 Node 的真实输入约定。

活跃笔记检索命中的查询准备、LLM 消息和聊天流笔记属于其他调用链，与本次完整策略域无直接决定重叠，不被替代。原有 core、strategy、heading parser、registry、factory 和兼容 shim 已关闭的所有者仅作为生产者证据，不重复处理。未修改中央覆盖表、验证文档或 README。

验证限于完整冻结 Git 源码、限定函数和表达式的 AST 归一化、实际构造器／SDK／调用方绑定、Ruff 和笔记门禁。未增加、修改或执行 Python 测试，也未执行应用、正则表达式、chunker、parser、模型、索引、网络或服务运行时；静态证明不替代真实数据的分块效果验证。
