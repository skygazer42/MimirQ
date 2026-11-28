# Agent Note: 流式阶段直接导入实际依赖

Status: implemented

## Problem

StandardStreamExecutor与State把整个engine模块作为Any传给业务阶段，阶段再用runtime.module查函数。engine因此维护大量无实际外部消费者的重导出，依赖方向和调用内容难以追踪，也直接违反项目NAM-003约定。

智能体另行复制可接收的Graph输入字段表，已存在的industry／overfetch字段被过滤；一些已声明的Graph选项没有从engine传入。合法的数值score_threshold=0还会被legacy真值默认换成0.7。

## Decision

流式阶段从实际函数定义者或稳定SDK公共入口导入69处模块内符号绑定。四个KG助手直接来自kg_merge_boost，reranker描述直接来自capabilities，不经orchestrator／factory转导。logger继续使用同一rag.engine名字；agent入口保持条件内惰性导入，不产生eager循环。

Executor和State删除module参数／属性，engine引用声明实际RAGEngine类型。真实请求数据、顺序operations、finished状态及异步生成器协议保留，不把模块换成另一个DependencyContext／manager／字典注入器。engine清理旧重导出和单次agent转发，三个真实模型构造调用与未使用的chat_cls参数同时收敛。

接收字段来自现有RagStateBuildOptions和AgenticStreamRequest的dataclass声明，不再另维护手写字段副本。engine传入已经声明的Graph选项，保核心tenant／account／db覆盖优先级和未知键过滤。数值0／False阈值保为0，None仍使用原默认，字符串0保持0；未批准的非法top_k legacy默认不顺手改变。max_tokens的None语义保持，不以0替代缺失。

本篇部分更新[执行实际所有者](2026-11-14-rag-execution-real-owners.md)的依赖现状，原状态／资源与退休边界继续成立。恢复字段传递不等于承诺每个下游模式已实现所有可选功能，隐藏SDK流最终化的已知限制不改变。

## Alternatives considered

- 仅把module改成Protocol可说明名字，却继续从装配器反向取业务实现，因此从实际所有者导入。
- 新建统一依赖对象可以少写import，但只是换一种整包透传，未减少维护点。
- 继续手写白名单能保持局部可见，但已经与实际字段声明分叉；复用声明避免遗漏，未知键仍不传入。

## Consequences

能从每个阶段的import找到实际依赖，engine只保自身模型／请求／工厂职责。内部module参数和旧私有重导出不保冻结测试兼容；这些是既有完成文件必要增量，不重复计数。

验证包括15完整业务AST的限定依赖变换、69实际定义绑定、静态eager导入图、公开engine→agent字段失败与修后受控流程及Executor正常／finished／提前关闭的复制和事件对照。没有实际模型构造、提示词渲染、网络、DB、线程或应用测试，不宣称端到端模式和所有SDK资源已验证。
