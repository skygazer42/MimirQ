# Agent Note: 文档入库使用明确的 ORM 文档契约

Status: implemented

## Problem

`document_batch_ingestion` 创建 `DBDocument`，重复查询也由 `document_source_persistence` 返回 `DBDocument`，但批量文档 helper 将这些对象声明为 `Any`，并用 `getattr` 把缺少必需字段的内部对象转成空字符串。模块还保留了无调用点的对象存储布尔包装，以及与模块级导入重复的函数内配额导入。

## Decision

批量文档构造、快照、重复解析和完成 helper 使用 `DBDocument` 签名，并直接读取模型必需的 `id`、`filename`、`status` 与 `file_path`。`doc_metadata` 继续接受缺省值，nullable `owner_id` 在派发时继续映射为空字符串。删除未使用的对象存储布尔包装及其导入，并使用已有的模块级配额函数导入。

单文件、URL 和 HTML 入库复用相同的完整 `DBDocument` 查询结果；重复持久化异常也携带实际模型。重复文档 helper 直接读取 `status`、`id`、`doc_metadata` 并写入模型已声明的 `dedup_key`。查无记录、可选入库运行和可空元数据仍按原分支处理，字段存在性不再作为兼容边界。

去重键由 `document_identity.build_document_dedup_key` 统一持有，单文件和批量调用直接传入 `content_sha256` 与 `pipeline_hash`，不再经过只改参数名的私有转发。来源元数据和流水线哈希按顺序归一化、显式将空字符串映射为 `None`；日期解析、ETag 长度上限、URL 优先级和 `setdefault` 的求值时机保持。

## Alternatives considered

保留 `Any` 和 `getattr` 默认值可以继续容忍不符合 ORM 契约的内部对象；没有选择这种写法，因为新建路径构造 ORM 模型，重复路径由同租户持久化查询返回 ORM 模型，且模型对直接读取字段声明了必需约束。

## Consequences

有效 `DBDocument` 的响应字段、租户范围、重复判定、任务派发和资源清理顺序保持原样。若内部调用方传入缺少模型字段的对象，错误会在字段读取处显现，而不是被序列化成空值。单独模块的对象存储能力判断仍由 `app.storage.object.runtime` 持有。

## Verification

Ruff、格式、语法、调用关系与 diff 检查通过；按用户要求未运行 Python tests，运行时行为未验证。

来源与重复记录这批的静态证据保存在 `E:/MimirQ/.superpowers/document-source-record-contracts-20261107/`，包含实际模型／工厂来源、完整 AST 对照以及单独的暂存区补丁。原有无关修改与测试源码保留，未执行应用、SDK、数据库或 Python 测试；静态检查不证明运行时等价。
