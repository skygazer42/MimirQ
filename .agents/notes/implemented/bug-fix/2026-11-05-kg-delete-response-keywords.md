# Agent Note: KG 删除后的列表调用使用真实参数名

Status: implemented

## Problem

delete_kg_entity_alias 与 delete_kg_predicate_ontology 在成功提交删除和审计后，分别调用原列表端点返回最新集合。实际 callee 的鉴权参数名是 _account_id，旧调用却传 account_id，因此真实 Python 参数绑定会在提交后失败，客户端得不到已完成删除的列表响应。

## Decision

只把两处调用关键字改为 _account_id，传入同一个 account_id 值。callee 的全部公开参数、Depends、tenant、查询和返回保持，caller 的删除、审计、commit、rollback、错误与身份依赖保持。两次删除的其余完整函数 AST 与原实现一致。

## Alternatives considered

给列表端点增加 account_id 兼容参数能接受旧调用，但会扩大公开参数与鉴权协议；改变 callee 参数名也会影响原 HTTP 依赖，因此只修复两个内部调用的实参名。

## Consequences

成功提交后能继续绑定原列表端点。修复单列原调用绑定失败与新调用绑定通过的静态证据；没有通过执行端点、数据库或 Python 测试验证。HTTP 类型与协议边界见[对应记录](../simplification/2026-11-05-kg-http-model-boundaries.md)。
