# Agent Note: 模型评测的算法与真实边界

Status: implemented

## Problem

部分评测私有算法没有读取 self，引用和 citation 又各自维护相同的稳定键规则。内部匹配记录、实际 Session、已构造的中位数、计数和成本与 raw SDK／JSON／ORM 字段混在一起，难以分辨哪些转换仍是边界行为。

## Decision

回归比较／导出后来按实际 ORM 与 Pydantic 输入进一步收窄，见[回归原生契约](2026-11-14-regression-native-contracts.md)。本篇的 evaluator、raw score 与实际资源边界继续成立，不能按数字或类型注解盲删。

上下文相关性与三项轨迹算法归 agent_evals 原模块函数；四个操作不读取 self，完整参数、公式、stopword、分支、返回值与调用顺序保持。BaseEvaluator 及具体策略类继续承担实际多态接口，LLM 实例、RAGEvaluator 的可修改注册表、单例和数据类保持。退出的私有方法在全库只有对应四个 self 调用，没有额外的旧测试或注册引用。

reference_match_state 用原模块内 TypedDict 描述已有十二字段字典；引用和 citation 使用既有 _stable_ref_key，退出的函数在参数名映射后整份 AST 相同。dict／Pydantic／ORM、原始引用、记录标识、semantic keys、quote、元数据、排序与截断仍按原政策处理。引用匹配的优先序和先按 chunk 去重再 limit 的规则不与其他指标合并。

RAGAS 的私有 DB 参数表达实际 Session，运行实体表达两种实际 run 模型，类型导入留在 TYPE_CHECKING。Settings、完整 DocumentChunk、case／run 和 resolve_prompt_template 实际返回的 PromptTemplate 直接读声明字段；Optional 模板与缺失 chunk 的原判断、JSONB 解析、字符串与列表复制保留。模型评判只直接消费实际 float parser／median／round 的产物，成本与 token 只消费原 SDK 边界已经转换的结果；原始分数、NaN／inf、int 到 float 分母、哈希、舍入、平局和顺序保持。

合成流水线只直接消费本地整数计数；critic 和 generator 两个 raw 数据入口保持原文。问题生成退出不被任何消费者读取的 all_tokens 本地副本，文本 tokens、Counter、随机调用与评分过程保持。已授权的[空样本返回](../bug-fix/2026-11-05-test-generator-empty-diverse-sample.md)和[数据集文档 ACL](../bug-fix/2026-11-05-test-generator-dataset-document-acl.md)仍是独立前置 bugfix；等价 style 只与包含它们的固定前序比较。

所有线程／queue／wall-timeout、LLM／embedding／HTTP 客户端、SDK callback、可注入生成与批评函数、SessionLocal／commit／rollback／close、异步关闭时点、预算、fallback、tenant／ACL 和已有错误策略保持。公开 callable 的参数、默认值和返回注解不变，不增加 Context、manager、compat wrapper、模块镜像或整个模块注入。

## Alternatives considered

把所有 evaluator 类都函数化可以减少更多表面，但它们提供真实的策略接口，RAGEvaluator 还持有运行配置和可修改注册表，因此只移动四个无状态私有算法。

两个 OpenAI callback getter 都加载相同 SDK，但原 try／return 范围不同；强行共享会扩大本批证明面，所以保留其原文。统一 raw score 和引用入口可以缩短代码，却会改变 bool、None、NaN、语义匹配与限制顺序，因此只处理有具体生产者证据的内部值。

## Consequences

算法、真实资源与原始边界的职责更清楚，现有业务和协议保持。完整模块 AST、实际生产者、公开签名、静态调用绑定、Ruff、格式与笔记门禁用于源码验证，不执行应用、SDK、模型、DB、parser、regex、数据、CLI、callback、renderer 或 Python 测试，也不提取后运行业务函数。

历史检索中的[评测质量](2026-11-05-evaluation-quality-native-rules.md)拥有前序 raw 映射规则复用与 regression sample 的 partial 增量；本篇完成该 owner 的完整模型评测类别审查。批处理、POC 与 KG 诊断各自保留原范围和决定，本篇不重复关闭它们。
