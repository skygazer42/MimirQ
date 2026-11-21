# Agent Note: 文档生命周期使用请求模型与单列查询契约

Status: implemented

## Problem

生命周期 PATCH 的负责人在服务层重复处理空白，发布状态在已校验请求和已有响应校验器之间再次设默认值。图片清理只查询一个带标签的字段，却经过两层通用查询／行适配，猜测 yield_per、迭代器、映射、属性和序列，还能在不符合查询契约时静默跳过结果。

## Decision

未分配文档删除的后续权限修正见[文档写入边界](../bug-fix/2026-11-14-document-write-boundaries.md)：沿用已有编辑角色与 owner，内部显式 bypass 保留。本篇 PATCH 与单列清理责任不变。

DocumentLifecycleMetadataUpdateRequest 的字段校验器在现有类型与 255 字符限制之后处理负责人：保留 None，去空白，空字符串归空。服务直接使用模型值和已校验的发布状态；响应模型继续使用原发布状态校验器。省略字段不修改、显式 null 清空和 model_fields_set 保持，负责人最终落盘值与原服务规则相同。

图片清理直接迭代实际 SQLAlchemy Query.yield_per 返回的单列 Row 并解包 img_id，退出本模块的 _iter_query_rows 和 _row_named_value。SQL 标签、租户／文档过滤、批大小、原字符串筛选、集合去重、排序和 MinIO 批次保持；不回退到一次性 all() 或空结果。

## Alternatives considered

- 保留通用行适配可以继续接受多个内部替身协议，但实际唯一生产者是明确的单列 Query，额外分支会掩盖不符合契约的对象，因此直接使用其现有迭代 API。
- 在服务层保留负责人清理可以避免移动校验，但同一个生命周期输入规则会散在 schema 与业务函数之间。字段校验放在现有类型和长度约束之后，服务按已校验值更新。

## Consequences

普通更新流程直接展示字段赋值，图片扫描不需要跨通用包装追踪结果类型。请求模型内的负责人值变为规范值；调用方必须使用实际请求模型，查询替身需要提供单列可迭代结果。API 路由、响应字段／状态、成员与 ACL、审计、事务、删除 tombstone、回滚、任务取消、并发与资源清理政策保持。

历史检索中，现有文档变更入口记录继续独立持有批量路由和 chunk/BM25 契约。本篇持有生命周期请求与单列清理，没有同一规则的提案需要吸收或归档。

## Verification

源码证据保存在 E:/MimirQ/.superpowers/document-lifecycle-input-query-contracts-20261107/，包含真实 API 调用、请求／响应字段、Session／Query／Row 的已安装源码、完整模块对照和独立暂存区补丁。Ruff、格式、Python 3.11 与笔记门禁提供静态证据；未运行或修改 Python 测试，未执行应用、SDK、数据库、MinIO 或删除操作，运行时行为尚未验证。
