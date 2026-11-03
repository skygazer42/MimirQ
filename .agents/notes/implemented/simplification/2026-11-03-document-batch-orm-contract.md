# Agent Note: 批量入库使用明确的 ORM 文档契约

Status: implemented

## Problem

`document_batch_ingestion` 创建 `DBDocument`，重复查询也由 `document_source_persistence` 返回 `DBDocument`，但批量文档 helper 将这些对象声明为 `Any`，并用 `getattr` 把缺少必需字段的内部对象转成空字符串。模块还保留了无调用点的对象存储布尔包装，以及与模块级导入重复的函数内配额导入。

## Decision

批量文档构造、快照、重复解析和完成 helper 使用 `DBDocument` 签名，并直接读取模型必需的 `id`、`filename`、`status` 与 `file_path`。`doc_metadata` 继续接受缺省值，nullable `owner_id` 在派发时继续映射为空字符串。删除未使用的对象存储布尔包装及其导入，并使用已有的模块级配额函数导入。

## Alternatives considered

保留 `Any` 和 `getattr` 默认值可以继续容忍不符合 ORM 契约的内部对象；没有选择这种写法，因为新建路径构造 ORM 模型，重复路径由同租户持久化查询返回 ORM 模型，且模型对直接读取字段声明了必需约束。

## Consequences

有效 `DBDocument` 的响应字段、租户范围、重复判定、任务派发和资源清理顺序保持原样。若内部调用方传入缺少模型字段的对象，错误会在字段读取处显现，而不是被序列化成空值。单独模块的对象存储能力判断仍由 `app.storage.object.runtime` 持有。

## Verification

Ruff、格式、语法、调用关系与 diff 检查通过；按用户要求未运行 Python tests，运行时行为未验证。
