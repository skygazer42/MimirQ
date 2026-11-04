# Agent Note: Engine 查询、文档与模型端口的内部值

Status: implemented

## Problem

Engine 的 RRF 文档融合在本地构造的分数与命中计数上重复转换数值，并把已声明的 Document 字段当作可缺失属性。模型路由也重复探测 Settings 已声明字段的存在性，使内部值与真实请求、模型和元数据边界不易区分。

## Decision

RRF 的本地 `score_map` 与 `hit_counts` 直接提供数值。两个映射在每个文档 key 首次进入 `best_docs` 前就写入；空映射已返回，因此 min/max 使用非空分数列表。排序读取当前融合步骤覆盖写入的分数、raw RRF 与命中计数；原始 base score 继续解析为浮点数。LangChain `Document` 声明 `id`，直接读取该字段，同时保留 chunk ID 的值回退。

文档元数据继续复制，原始分数解析、rerank 文档优先策略、每查询去重、退化范围得分 1.0、五级排序并列规则、字段名称和哈希保持。`DocUtilsMixin` 仍是实际 Engine 继承与类方法钩子的一部分，保留 `cls` 分派。

13 处 Settings 存在性回退使用声明属性。模型构造、mock 入口、共享 HTTP 客户端、fast/heavy 选择、兼容性检查、复杂度公式、绑定温度、重试和超时参数保持；字符串、数字、布尔转换和原默认值继续存在。

字典扩展使用标准正则匹配的可空结果判断；文件读取成功后的内容直接分行。原始规则字典和限额仍在原位置解析，YAML 子集、单次替换、顺序、去重、截断和 provenance 不变。Unicode 查询归一化、请求 dataclass、会话释放和同步/异步模型端口经完整审阅后保留。

`ChatRAGConfig.model_copy(update=...)` 不验证更新数据，dataclass 的旧参数入口也不验证字段值。因此类型注解不能替代后续配置值解析；此处不收窄这些原始边界。

## Alternatives considered

把纯文档 mixin 改成独立函数可减少类结构，但当前 Engine 继承及 `cls` 钩子承担实际调用约定，迁移还会涉及同步检索与标准流调用方。当前保留类和方法契约，只使用其本地已构造值。

依据 Pydantic 或 dataclass 的字段注解统一移除转换可以减少更多代码，但旧 overrides 与 `model_copy` 更新未经过统一验证。保留原始配置、模型输出、元数据与数值限额的解析。

## Consequences

RRF 内部值来源更直接，模型端口及资源生命周期保持。若以后允许插件改写已构造的融合排序字段，需要重新检查这些字段保证；原始 base score 仍由现有转换负责。

历史审计中，[混合检索排名](2026-11-05-hybrid-ranking-owned-values.md)与内部排名值部分重叠，[查询准备所有者](../architecture/2026-11-03-query-preparation-owner.md)与模型端口和请求边界部分重叠；保留两篇决定并互链，没有替代或扩大已闭合模块的审查范围。

## Verification

6 个查询、文档与模型端口所有者的 1,046 行基线、49 个函数完整审阅；实际 Engine 构造、同步检索与标准流调用方、LangChain Document 字段和 Pydantic `model_copy` 源码提供边界证据。验证限于 Ruff、格式、Python 3.11 AST、diff 和笔记门禁。按任务限制不添加、修改或运行 Python 测试，不导入或执行应用、SDK、模型、stream、检索、数据库、网络、服务或 fixture。
