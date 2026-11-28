# Agent Note: 重排缓存区分评分域并传递真实上下文

Status: implemented

## Problem

内部ScoreCache保存归一化之后的分数，key却不含normalize，交替请求可能把raw2.0与归一化0.880797混用。Document适配器丢弃tenant_id／query_type，LLM入口读不到真实权重；candidate投影又丢掉已有向量锚点。

模型回复含全部外来ID时，未被使用的分数仍让llm_scores_present为真，导致它与合法空回复采用不同融合路径，违反提示词仅返回输入ID的合同。

## Decision

内部ScoreCache读写key同步加入实际normalize评分域，继续保存post-normalize分数，保实例缓存、TTL、容量及外部result cache协议。

Document适配器通过窄private options hook选择具体run协议。默认没有附加字段，只有LLM选择tenant_id和query_type，不把全部kwargs灌入其他严格签名。实际RagState通过asdict保留UUID，LLM边界用已有文本规则转换为canonical字符串，以匹配tenant权重映射；None／空值保全局规则。

候选投影只按字段存在性携带vector_score／score／distance，保原优先级及显式None／False／0。模型prompt仍不包含这些分数，原模板与实际prompt文本保持。

建立llm_scores时只接受payload已有ID，保原ID归一化、已知重复覆盖、合法0分及partial策略。foreign-only回复与现有合法空列表走同一既定fallback；坏JSON、重试、取消与预算不扩展。

## Alternatives considered

- 缓存统一保存raw值可以共享更多数据，但会移动既有compute_score归一化职责；只为key增加实际评分域。
- Base.run直接接收全部kwargs可以更短，但不同实现有严格协议；只在实际LLM边界传两个已支持字段。
- 把向量分数加入prompt可以让模型参考，但会改变模型输入与标定，因此锚点只供既有本地融合。
- 外来ID保留下来再在最终输出过滤会继续污染presence判断；在接收分数时验证已有ID集合。

## Consequences

缓存命中与fresh结果使用相同评分域，租户／查询类型权重及既有向量锚点能经真实通用入口生效。这些明确修复会改变原来错误的分数与排序，不能宣称全部输出未变；非LLM与无缓存原有效路径保持。

有限假HTTP／缓存／模型／Document和原生UUID验证四类失败与修复，独立核对None／False／0、非LLM严格签名、partial／重复／外来ID、prompt隔离及原异常／取消身份。未调用真实SDK、NumPy、Jieba、模型、网络或应用测试，不证明真实模型排序质量。原始数值／shape及重试／取消／资源边界仍由实际所有者处理。
