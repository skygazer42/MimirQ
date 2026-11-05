# Agent Note: 插件合同校验与已构造结果的所有者

Status: implemented

## Problem

插件合同和 registry 各有一份与已有 helper 等价的校验逻辑。运行层、本地 runner 和报告还把平台刚构造的 validation、readiness 与 golden bundle 当作未知返回协议反复探测，实际 descriptor 依赖则标成 Any。

## Decision

合同字段列表复用现有 `_validate_optional_string_list`。registry 的 importlib getattr 匹配复用现有 `_is_module_string_getattr`，调用点明确传入 `import_module`。原 helper 退休；静态源码对照确认参数重命名和该固定字面量绑定之外，类型、None、错误类与消息、分支顺序、默认值及 tuple 构造完全相同。其他 retrieval 模块的同名 helper 语义不同，保持原样。

实际 metadata validators 的所有正常 return 都构造包含原生 bool `ok` 与字典列表 `errors` 的返回值；运行层直接读取这些已构造结果，保留空列表、字段值和错误消息回退。本地 runner 保留自己的异常与空输出分支，它们同样构造 bool 标志，后续直接传递该标志。readiness 读取本地 check 构造器已规范化的 required/passed，golden report 读取同模块链条始终返回的 items 列表。

local runner 与 reports 的 descriptor 参数标注实际 `PipelinePluginDescriptor`。该对象由 `describe_plugin_dir` 在 manifest、路径、合同和发布报告处理之后构造。新类型符号来自原本已导入的 registry，没有新模块路径、导入环或 eager 入口执行。原始 descriptor 合同字段和值仍由原校验处理，不把字段注解当作赋值验证。

当前插件执行模型仍在进程内：RLock、sys.path、sys.modules snapshot/restore、bytecode suppression、文件或 module 入口、每次 generator next 的执行上下文和 finally 顺序保持。package hash、来源证明、发布与测试报告 gating、可选 YAML、允许的前缀与平台保留命名空间不变。两个 contextmanager 只补充实际的 `Iterator[None]` 返回注解。

[政务插件的来源与内部记录](2026-11-05-governance-plugin-owned-records.md)沿用原始值边界，处理具体插件的重复来源读取、事项候选、章节和实体；平台合同及运行层决定保持。

三个已声明 Settings 字段直接读取，原 str/bool 解析与默认值保留。原始插件 Document/IndexRecord/字典/文本/迭代器、inspect.signature、JSON、YAML、regex、metadata、provenance 和黄金草稿模板仍保留全部入口检查、转换、复制和错误政策；不执行插件或安全 scanner 来验证本批。

## Alternatives considered

保留两个原 helper 可减少调用点变化，但它们与同文件已有 owner 在上述全部边界上等价，会留下需要同步维护的重复规则。复用既有 leaf owner 即可，不增加工具模块或兼容转发器。

将所有声明字段和类型注解都视作已验证结果可以删掉更多守卫，但插件、SDK、合同文件及回调仍提供原始数据。当前只收窄实际平台构造的结果，原始入口继续保持。

另建通用 registry 管理器或改成进程执行可以重新组织状态，但会改变当前导入、迭代和资源契约，超出本批范围。

## Consequences

合同列表校验和 AST 属性匹配各保留一个实现，平台内部结果的生产者更明确。原始错误文本、字段顺序、注册与阶段顺序、过滤、召回参数、持久化和哈希契约保持。若以后替换 validation、readiness 或 golden bundle 生产者，需要同时更新这些消费端保证。

历史审计中，[安全、反馈与行业规则](2026-11-05-policy-feedback-owned-values.md)与原始值边界原则部分重叠，双方互链。[Parser adapter 所有权](2026-11-05-parser-adapter-helper-ownership.md)与实际资源和普通 helper 的边界部分重叠，保留其决定并互链。检索、模型消息和前端状态笔记属于不同合同，没有被替代。

## Verification

7 个插件所有者的 5,066 行基线、240 个函数完整审阅。全库引用扫描区分限定模块及同名函数；两份 helper 的限定 AST body 等价检查通过。实际 descriptor、metadata validation、readiness 和 golden bundle 的构造与既有测试替身形状只读核对；资源函数、原始解析、调用参数、导出、错误和写入顺序作静态对照。Ruff、格式、Python 3.11 AST、diff 与笔记门禁覆盖本批。按任务限制不添加、修改或运行 Python 测试，不导入或运行应用、SDK、插件、安全 scanner、模型、网络、数据库、服务、fixture、YAML 或配置 regex。
