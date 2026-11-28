# Agent Note: 标注器保留显式客户端并暴露错误响应

Status: implemented

## Problem

LLM 标注入口使用 client or factory，会忽略显式提供但真值为 False 的客户端。基础 chat_with_schema 只做 JSON 解码，可以返回数组或其他非对象值；入口把这些值换成 {}，随后生成没有标注的成功结果，响应违约因此不可见。

## Decision

只有 client is None 才创建客户端；已有客户端继续承担原调用。原始 LLM 响应必须为对象，非 dict 抛 TypeError。合法对象仍按原规则归一化到既有六个标注模型，不改变 schema、提示、temperature=0、1200 token 预算、取消传播和真实 CPU／LLM 的 source／default／label 差异。

调用方保留原失败策略：解析处理器记录 error metadata／日志，RPC 记录 warning 后使用原规则 fallback。没有伪造新的成功状态，也没有给重试增加额度。Document 的 model_copy 与字段直接读取依赖安装 SDK 及真实构造者合同，原始 Map／HTTP／LLM 边界仍由各自入口处理。

## Alternatives considered

- 继续把非对象响应换为空字典可减少上层错误，但无法区分合法无标注与协议违约。
- 给全部标注器套一套统一模型能减少部分重复，却会改变 CPU／LLM 原始接受范围和标签来源，因此保留各自合同，只修客户端与对象边界。

## Consequences

独立假客户端核对 falsey 实例被使用、非对象失败、取消身份和原调用参数；六模型与三关键词实现结构保持，原异常别名与 RPC 消费者仍同一对象。没有真实模型／SDK／网络调用或 Python 应用测试；这些有限端口检查不证明模型输出质量。

同批[无入口副本退出](../simplification/2026-11-13-retire-unused-preprocessing-copies.md)不影响真实标注入口，[流程函数所有者](../architecture/2026-11-13-document-pipeline-function-owners.md)继续持有原解析失败转换。检索未发现需替换的同题活动提案，两篇属于相邻范围并保留。
