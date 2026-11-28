# Agent Note: 退出无入口的预处理辅助副本

Status: implemented

## Problem

pii_llm_discover 与 pii_regex 形成没有生产根节点的子图，synthetic_qa 也没有当前入口。旧 document_dedup_service 仅被冻结测试与历史记录引用，实际上传和批量入库已经依赖 document_source_persistence。只保留模块内 __all__ 不能证明它们仍有业务消费者。

## Decision

退出上述四个文件。引用核对覆盖生产、脚本、配置、动态插件加载、公共文档与包导出；原文和 SHA 保留在当前批次快照及历史 coverage，不把删除算作全文完成。

PII 的实际 anonymize_pii／find_pii_matches 与 clean_preview／auto_annotations 入口保持，实际模式仍为 mask／token；CPU／LLM 标注、metadata_enrichment 与公开模板目录继续存在。上传的租户／数据集／未归档过滤、唯一约束、并发冲突和事务仍由实际 source_persistence 所有者处理，不把旧副本中的查询失败后宽泛扫描转移过去，也不声称两份实现全等。

本篇部分替代[早期数据集服务拆分](../../../../docs/maintenance/style-unification/decisions/implemented/simplification/2026-11-02-dataset-service-functions.md)中 document_dedup_service 的历史所有权记录；该旧记录说明当时取舍，当前实际依赖以 source_persistence 和本次完整消费图为准。

## Alternatives considered

- 为三个预处理叶子新增入口可利用已有代码，但会引入尚未选定的业务路径，因此不以新功能为无根模块补理由。
- 保留旧 dedup 服务给测试或未知调用者能避免改旧导入，却留下另一套未接入查询与失败政策；用户已排除测试维护，没有真实发布消费者需要兼容层。

## Consequences

实际清洗、标注和入库路径保持单一所有者。旧私有测试导入需要后续维护，当前不修改或运行。公开停用词与 16 项 reference 模板是实际资源合同，逐文件复核并保持原字节，没有执行模板代码或把它们算作运行算法行数。

相邻[未接入解析工具退出](2026-11-13-retire-unwired-parsing-utilities.md)和[质量结果所有者](2026-11-13-parse-quality-decision-owner.md)保留各自范围，本篇不删除它们的真实入口。检索未发现同题活动提案需要归档；有限源图／AST／假端口证据不等于真实模型、数据库或隐私检测效果验证。
