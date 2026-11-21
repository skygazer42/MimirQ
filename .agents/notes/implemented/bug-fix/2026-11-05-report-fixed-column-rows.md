# Agent Note: 报告按固定列 Row 读取路径与元数据

Status: implemented

## Problem

数据集报告的 folder tree 查询只选择 source_path 一列，metadata 查询只选择文档 ID 与 metadata 两列，却都以 isinstance(row, tuple) 决定是否读取。真实 SQLAlchemy Row 是序列式行而非 Python tuple，因此有效路径与全部治理／chunk／parse metadata 都被跳过，报告虽有文档画像却显示空目录或零值聚合。

## Decision

两处现有查询直接按一列和两列解包。路径保留原 str／strip 真值过滤，并仍把原字符串传给 folder builder；metadata 保留 dict 过滤、副本、缺 document_id 时的注入、max_docs+1 和已有 metadata 数量截断。原 tenant／account／dataset／pipeline 授权查询、SQL、排序、限额、错误返回与 DatasetReportOut 不变。

所有真实 JSON／HTML／ZIP report API 均通过 _build_report 调用本 owner，再把这些结果放进同一报告。该修复沿用 Root 已确认的[固定列 Row 读取约定](2026-11-05-periodic-freshness-two-column-row.md)，独立于后续无状态 ReportService 风格迁移，不增加 tuple／Row 兼容分支。

## Alternatives considered

- 加上 Row 类型判断可以保留旧 tuple 分支，但生产者列数已经固定，直接解包更明确，也不依赖额外 SDK 类型导入。
- 取消原始字符串或 dict 校验可以让更多对象进入输出，却会改变已有数据清理与错误政策。因此只修正两处行提取。

## Consequences

真实路径和持久化元数据能够进入原有报告计算；不存在路径、非法 metadata 与查询失败仍保留原处理。列数未来改变时必须同步消费者。截断仍按原来过滤后的 metadata 计数，不改为扫描行数或补扫。

源码证据核对完整 report owner、实际 API 和 canonical ACL 查询，以及已安装 SQLAlchemy Row／BaseRow 的序列约定。完整模块仅允许两处行提取投影变化，调用方／schema／模型保持。Ruff、格式、Python 3.11 AST 与笔记门禁通过；没有执行应用、SDK、模型、数据库、服务、回调、业务正则或 Python 测试。

活跃笔记检索只命中相邻审计与 freshness 的固定列修复，各自 owner 保持独立；没有同一报告读者的旧提案需要吸收或归档。
