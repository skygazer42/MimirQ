# Agent Note: 评估报告服务直接表达操作与内部记录

Status: implemented

## Problem

反馈与数据集报告仅用静态方法类作为命名空间，却没有实例状态、类资源或生命周期。完整 ORM／Pydantic 结果重复探测字段，已解析的分数与自有计数再次转型；这些处理与真实 JSONB、SDK、统计输入和导出边界混杂。旧 tuple 返回注解也未表达实际字段数量。

## Decision

FeedbackService 的七个静态方法和 ReportService 的一个静态方法迁为原模块函数，参数、默认绑定和业务顺序保持。API 通过实际模块函数调用，dispatcher 保留 else 分支中的 lazy import，避免遮蔽直接 rows 分支已有的候选 builder。三份既有测试仅迁移调用或 monkeypatch 引用，不增加断言、用例、helper 或兼容 class。

Queryset health 直接调用既有 validate_and_normalize_queryset_health_policy，退出只转发的 _resolve_policy。四份私有 TypedDict 仅描述实际构造的 benchmark 行、hardcase cluster、在线质量桶与 rollout gate level，不建立新运行时模型框架。局部零值／defaultdict／加一、明确 int／float helper、len／enumerate／time／math 生产者的结果直接使用；数字注解本身不构成删除转换的理由。

完整 Message、Conversation、MessageFeedback、EvidenceItem、RagasRegressionCase／Run／Item、connector/precheck 实体、DatasetProfileSummary 和明确标记的 Row 字段直接读取。可空的 user message／enrichment、混合 dict／Pydantic／ORM adapter、raw JSON、UUID／日期和数值解析保留。新 SDK、KG、Query／Select、embedding 与 schema 类型仅在 TYPE_CHECKING 引入；真实 lazy import、回调默认值与客户端创建阶段不变。反馈 reference helper 的既有四字段 tuple 返回值拥有准确注解。

LTR 的 RLock、原子文件、内容寻址、manifest、activation／rollback、可接受参数别名和指纹不变；online eval 的 Queue／Thread／Event、采样哈希、状态与关闭不变；Ragviz 的真实 embedding 缓存和 Numpy 到 wire 的标量转换保留。统计方法、bootstrap 哈希／种子／tie、阈值／精度、NaN／finite、空值、计算顺序、raw item adapter 和真正 int-to-float 运算不变。

输出仍显式投影、排序、限额、脱敏与复制。空列表的既有替换／副本语义保留。ReportDataProvenance.generated_by 中的 ReportService.build_dataset_report 是稳定 wire 标识，不是动态 import，继续保留原值与 schema；不为该字符串恢复兼容 class，也不修改 Root 独占的中央历史验证记录。HTML 除 histogram 的实际 tuple 行类型注解外，完整渲染与字面量保持在前置授权修复之后的状态。

## Alternatives considered

- 保留静态类或增加 singleton 可以减少调用方 diff，但它们没有资源归属，只会继续保留命名空间层。直接迁移全部真实引用，不建立新 shell。
- 依据数值注解统一删转换更整齐，但 SQL／Numpy／HTTPX、raw metadata、persisted JSON 与回调输入仍有实际边界。只退出明确生产者已建立的原生值，尤其保留空 sum、真实 int-to-float 和 wire 格式。
- 改 generated_by 来匹配新符号可以让文字更直观，却会改变公开 provenance 值。内部所有者迁移与稳定输出标识分开，不混入行为变更。

## Consequences

当前操作归属与内部数据流更清楚，代价是已有原始输入仍保留必要转换和兼容参数。未来增加不同生产者时，应重新验证边界，而不是把未知对象直接交给已收窄的函数。没有增加配置、重试、默认成功、Manager／Context、独立小模块或 speculative fallback。

本决定消费并就地更新[原策略／反馈内部值](2026-11-05-policy-feedback-owned-values.md)的一处当前函数名称，候选构造与 raw 输入决定保持。三个前置行为修复分别由[报告固定列 Row](../bug-fix/2026-11-05-report-fixed-column-rows.md)、[Ragviz 文档 ACL](../bug-fix/2026-11-05-ragviz-chunk-document-acl.md)和[HTML 属性引号](../bug-fix/2026-11-05-report-html-attribute-quotes.md)持有，风格差异不重新改变它们。活跃笔记检索没有同一操作归属的旧提案需要吸收或归档。

完整阅读 23 个 owner／9,853 行与实际调用／生产者，8 个静态方法先通过整模块纯迁移 AST 证明，再做有界字段／原生值整理。固定源码／Python 3.11 AST／显式调用绑定、Ruff、格式、diff 与笔记门禁提供有界证据；没有添加、扩展或执行 Python 测试，也没有执行应用、SDK、模型、数据库、服务、回调、业务正则、HTML generator／renderer 或浏览器，不声称运行时回归。
