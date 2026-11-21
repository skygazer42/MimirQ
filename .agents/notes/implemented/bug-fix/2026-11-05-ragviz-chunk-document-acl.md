# Agent Note: Ragviz chunk 轴消费既有文档 ACL

Status: implemented

## Problem

普通认证的 similarity API 原样返回 calculate_similarity_matrix 的 x_data／y_data。dataset_chunks 和 regression_chunks 两个生产者只验证数据集可读，就把完整 chunk.content 放入结果并用于 embedding；文档的 only_me／partial_members 等 ACL 未被检查。已有 document_chunks 分支则通过 canonical 文档访问服务过滤。

## Decision

仅在上述两路原有 bounded SQL 查询之后，把真实 document ID 列表交给既有 get_allowed_document_id_sets，并按 allowed set 裁剪结果。两路之前的 assert_dataset_readable 已完成 membership，因此 canonical helper 使用 check_member=False。dataset rows 在 enumerate 之前裁剪，regression chunk_rows 在建立 chunk_map 之前裁剪，未经允许的文本不会进入 items 或 embedding。

原 SQL 的 tenant／status／排序／limit、已选择 case 顺序、矩阵算法、Numpy 序列化、DTO、资源和错误处理保持。不补扫、不 refill、不移动限额。空的可访问轴沿用现有 empty-collection ValueError 与 API result 政策；不增加 HTTP 兼容包装，不修改 document_access、document_chunks、regression_questions 或 collection counts。

## Alternatives considered

- 在新代码复制 access_mode／owner／allowlist 逻辑可减少一次服务调用，但会建立第二份权限规则并漏掉组权限。直接消费 canonical allowed set。
- 过滤后补扫至请求数量可让矩阵更满，却会改变已有查询范围和成本上限。max_items 继续作为原扫描上限，过滤后数量可以更少。
- 复用会在全拒绝时抛 403 的列表 helper 可以拒绝请求，但会改变本次选择的 empty-axis result 路径；set-returning helper 保留既有空集合处理。

## Consequences

数据集成员不再通过这两个 chunk 轴获得无文档权限的内容。可见结果保持原顺序，枚举位置对应剩余可见项，可能出现较小或空的轴。实际 auth／DB helper 错误仍按原有 API 映射，不添加默认成功或静默回退。

Root 全文核对两个生产者、dispatch、empty check、embedding 与返回、实际 API 和 canonical ACL 后批准该最小独立修复。固定源码证明完整模块只增加既有 helper 导入和两处 bounded row pruning，原 SQL、handler、资源、集合及数值形状保持。Ruff、格式、Python 3.11 AST、diff 与笔记门禁通过；没有执行应用、SDK、模型、数据库、服务、回调、业务正则或 Python 测试。

活跃笔记检索中的文档访问、租户权限与报告记录拥有原 canonical 规则，本篇仅消费而不替代；没有同一 Ragviz chunk 轴的既有提案需要吸收或归档。
