# Agent Note: 集成分块直接依赖实际实现

Status: implemented

## Problem

app/rag/chunking/integrated_pipeline 的16份生成文件仅把32个函数调用转发到 app/third_party/integrated_pipeline。同一个实现出现两套导入路径，普通 chunking 包又有一层没有消费者的 integrated_chunk_file 转发，增加查找成本。

third_party 的目录名也不能决定全部文件都是上游代码：17份源码中，7份有上游或派生来源证据，另10份是项目自己的适配与资源绑定。

## Decision

app/third_party/integrated_pipeline 是集成分块的实际所有者。桥接函数返回上游原始 chunk 字典；processor.chunk_integrated_file 继续负责项目 Document 转换，两者有不同的数据协议。所有真实自研调用方同批改为直接导入实际所有者，16份生成转发和无消费者的包级转发退出；普通 chunking 包保留工厂和层级分块两个实际公开对象。

7份上游或派生实现按逐路径来源、NOTICE 和初始导入证据保留原始字节，不宣称与某个上游版本逐字相同。10份本地集成逐个全文审核，显式覆盖 Ruff 的目录排除设置，不把跳过检查计作规范通过。真实 tokenizer 模型状态、公开 strQ2B 拼写及其固定消费者绑定保留；四种 chunker 仍按原白名单延迟加载。

另外，无生产调用、注册、配置或动态加载根的 workflows/query_rewrite.py 退出；真实 CHAIN 注册仍指向 ChainWorkflow，不把死实现接入主流程。查询两个展开入口只共享同义值清理，保留各自字符串键、词边界／子串、单向／对称、配额和追踪契约。

本篇部分取代[结构化分块边界](../bug-fix/2026-11-05-structured-chunk-owner-contracts.md)中的生成 shim 保留状态，其策略、位置和外部结果规则继续成立。[文档处理函数所有者](2026-11-13-document-pipeline-function-owners.md)的流程职责保持，processor 的集成导入更新到实际实现。

## Alternatives considered

- 保留旧命名空间可以少改调用方；完整调用图已确认没有需要独立迁移窗口的外部客户，转发只增加查找层，因此同步迁移真实调用方。
- 把 third_party 全部当作上游可避免修改固定实现；这会掩盖10份本地集成的维护责任，因此按逐路径来源分别处理。
- 合并原始 chunk 桥接和 Document 转换入口可以少一个函数；两者承接不同消费者和返回协议，因此保留各自职责。

## Consequences

集成分块只有一个实际命名空间。旧私有路径和无根 workflow 不再提供生产兼容壳，冻结的旧测试引用需要另行维护；删除路径不计作现存文件完成数。

工厂的模型复制失败直接传播，不再重建一个可能丢失 subclass／id／扩展字段的 Document。合法复制保留原类型与字段；Lazy Mapping、False sentinel、签名探测边界及缓存顺序保持。策略矩阵的62份 fixture、783行数据保留原字节和结构，没有执行真实分块样例。

验证限于完整源码及定义覆盖、调用图、有限假端口与轻量 Document 协议、Ruff／格式／AST／内存编译及应用装配和 OpenAPI。应用测试不修改、不运行；未执行真实 chunker、NLP、模型、网络或数据库，不能据此宣称实际解析保真或分块效果通过。
