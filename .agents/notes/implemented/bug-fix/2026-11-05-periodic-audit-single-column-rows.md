# Agent Note: 周期审计按单列 Row 读取范围

Status: implemented

## Problem

周期索引审计从 Dataset.id 查询自动发现数据集，却只在 isinstance(row, tuple) 时读取值。实际 SQLAlchemy Row 是序列式行，不是 Python tuple，因此默认未显式传 dataset_ids 的运行扫描零个数据集。真实 CLI 的 all-tenants 分支在 Tenant.id 查询后也有相同过滤，会跳过所有租户并仍输出空的成功结果。

## Decision

仅在这两个已知单列查询的消费者直接解包一列，再执行原有 UUID 过滤。服务端租户条件、排序、上限、默认选择、任务与错误政策保持；CLI 选项、输出、exit、会话和租户范围也保持。不增加 tuple／Row 兼容判断。

该真实缺陷与后续等价风格整理分开提交。CLI 是同一调用链的必要 delta，本次不借两处行读取修复宣称关闭整个 CLI 类别。

## Alternatives considered

- 额外识别 Row 再保留 tuple 分支，可以支持两种表现，但生产者已经明确为一个单列查询。直接解包同时适用于现有可迭代行，避免维护不需要的类型分支。
- 让 CLI 强制要求显式租户／数据集 ID 可以绕过自动发现，却会改变已有默认与 all-tenants 契约，因此修正实际读取边界。

## Consequences

自动范围中的真实 UUID 可以进入现有有界审计链；原有非 UUID 值仍跳过。运行可能实际发现问题或返回失败，而不再因范围被错误清空产生空成功。未来若查询改变列数，必须同时同步明确的行解包契约。

核对真实 CLI 默认调用以及已安装 SQLAlchemy Row、Python/Cython BaseRow 和列实体的非 scalar 契约。完整两个模块 AST 只允许这两处提取投影变化；Ruff、格式与 Python 3.11 语法检查通过。没有导入或创建 SDK／Row，没有执行 CLI、应用、DB、业务正则或 Python 测试。

按 Row／tuple-only／单列读取检索活跃笔记，没有同一周期审计所有者的既有决定需要吸收或归档。
