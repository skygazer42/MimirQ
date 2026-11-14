# Agent Note: 文档处理入口直接依赖函数所有者

Status: implemented

## Problem

DocumentProcessorService 的构造函数为空，93 个方法没有实例字段写入。三个 Stage 只保存这个 service，预览服务也没有实例状态。流程通过实例、固定 factory 和六个反向 facade 逐层找真实函数；processor 同时为旧测试导出大量已经迁走的名称，实际依赖难以顺序阅读。

## Decision

process_document 位于 support/process_document_flow.py，拥有原来的借用／自建 Session、异常分支、取消与 finally。processor.py 持有文档持久化和图像助手，不再导入流程或阶段；Flow 与 Stage 从实际所有者具名导入函数。仅用于同一个生产实现的 service／factory 透传、反向 sys.modules 查找和旧测试 facade 退出，不引入通用 Context、manager 或模块参数。

解析、内联资源和分块资源分别使用 parse_document、enrich_inline_assets、process_chunk_assets；已有治理／归一化／分块／去重函数保持其职责。preview 使用 parser_service.parse_for_preview。后台任务、HTTP 调度和 worker 在同一批迁移到这些实际入口，参数、await、线程与资源时点保持。

processor 的 chunk_integrated_file 直接导入 app/third_party/integrated_pipeline 的实际桥接入口，继续持有原始 chunk 字典到 Document 的转换职责；[集成分块实际所有者](2026-11-13-integrated-pipeline-canonical-owner.md)解释生成转发退出的调用边界。

恢复模块在原验证成功位置创建实际 Indexer，直接使用实际 ORM 模型；Root 的一次性转发和固定模型注入退出。真实租户谓词、索引／数据库操作、commit／rollback／refresh 和可空计数恢复保持。nullable 数据库列与异常发生前未发布的运行状态仍可为 None，不将类型注解当作它们已经存在的依据。

ZIP 实现使用模块函数。保留的 ZipImageProcessor 只提供 DeepDoc 上游正在调用的 _safe_extract 与 _sanitize_zip_member 两个静态绑定，指向同一实现；没有旧 singleton、重复实现或推测性历史入口。app/deepdoc 按贡献指南与原计划保持字节不变，这是真实的上游协议边界。自研 ZIP 调用方直接使用函数，Markdown 文件选择由现有 artifact_normalizer 持有。

本篇部分替代[阶段与结果边界](../simplification/2026-11-05-parsing-stage-function-ownership.md)中的 service／三 Stage 接口保留决定；该篇原始数据、事务与资源原则继续成立。[辅助生产者](../simplification/2026-11-05-parsing-auxiliary-producer-boundaries.md)和[未接入工具退出](../simplification/2026-11-13-retire-unwired-parsing-utilities.md)属于相邻范围，保留并互链，没有同题提案需要归档。

## Alternatives considered

- 仅把无状态方法改成静态方法，可少改调用方，但仍要通过 service、factory 和反向 facade 找到真实实现，不能消除已经确认没有用途的对象层。
- 把全部助手再包进一个新的 Context／Adapter，能保旧签名，却会让同一无状态依赖继续被逐层转发，因此使用实际模块函数。
- 将 DeepDoc 的两个 ZIP 调用改为新名字能删除最后的类名，但会违反上游目录保留约定；两个同函数绑定足以满足真实协议。

## Consequences

主流程能直接读出调用的函数和数据。实际 SDK parser、模型缓存、存储客户端及阶段结果数据类继续保留；旧私有类、singleton 和 monkeypatch 入口不作为生产兼容对象，冻结测试需要后续维护。

验证包括完整原后源码／定义映射、模块函数迁移的完整 AST 对照、真实调用方和依赖图、有限假资源／模型值／Session 协议、Ruff、格式与完整应用 OpenAPI。类迁移以清理 docstring 缩进后的业务 AST 核对，非业务代码逐项说明；不以格式通过代替流程检查。没有运行 Python 应用测试或真实 SDK／模型／数据库／子进程，不能据此宣称实际解析、事务并发或操作系统子树验证通过。
