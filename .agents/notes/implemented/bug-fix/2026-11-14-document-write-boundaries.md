# Agent Note: 文档写入使用真实索引与未分配资源权限

Status: implemented

## Problem

QA 写入把 MAX(chunk_index)=0 当作缺失，已有首块时再次使用 index 0。未分配数据集的文档删除只检查租户成员，没有沿用现有的编辑角色与 owner 规则，viewer 和其他编辑者也能进入取消／tombstone／清理流程。

## Decision

QA 下一个索引仅把数据库聚合 None 当作空集合；合法 0 得到 1。保原 active-pipeline SQL、替换旧 QA、来源、vector、DB 与 BM25 的顺序和失败政策。

删除在 enforce_permissions=True 且文档未分配数据集时，直接调用已有 assert_document_writable_for_unassigned_target。分配数据集的原 gate 保持；不增加新的角色表、owner 解析或 system 身份。权限拒绝发生在取消和 tombstone 之前，批量入口继续逐项处理。

内部显式 enforce_permissions=False 的清理不进入新 gate；实际 retention／RTBF 调用同时跳过 membership 的策略保持。仅跳过重复 membership 并不表示跳过权限：权限仍启用时由实际 owner 取得所需成员与角色。

纯 storage／hash／lookup／ACL 转发与无调用 unlink 退出，真实调用方依赖实际 owner；资源、Session 与线程桥不是普通转发。upload-only 与普通批量 finalize 共用原同体 reconcile 语句，彼此不同的 pending／idle／原始 metadata 规则继续留在其边界。

本篇部分更新[生命周期输入与查询](../simplification/2026-11-07-document-lifecycle-input-query-contracts.md)的删除权限事实；其 PATCH、单列 Row 和资源清理决定保留。

## Alternatives considered

- 保留 max_idx or -1 更短，却不能区分合法首块与空集合；在真实聚合边界区分 None。
- 为删除再写一份角色和 owner 判断能就地完成，但会让未分配文档的写入与删除再次分叉；复用现有实际权限 owner。
- 统一所有 pending 谓词能少几行，但旧 metadata 和进度归一化存在真实差异；没有证明相同时不合并。

## Consequences

合法 index 0 不再导致重复索引，未分配文档的非授权删除被原权限错误拒绝。内部清理 bypass 和已分配文档权限保持；不宣称删除流程已经具有新的跨请求版本锁或事务原子性。

原入口错误与修后角色／owner、单删／批删、None／0 及资源顺序证据分别保留。检查使用实际源码和受控数据／Session／索引端口，没有执行应用测试、真实删除、对象存储、SQL、SDK、锁或线程；冻结测试旧私有引用不作为兼容壳保留理由。
