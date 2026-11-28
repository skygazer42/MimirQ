# Agent Note: 保留实际使用的 chunk 质量评分链路

Status: implemented

## Problem

现行入库流程使用 `score_chunk_quality`，检索追踪使用 `summarize_retrieved_chunk_quality`。同目录的 `chunk_quality_recommendation_service.py` 定义了独立建议与自动调参规划器，但完整 Git 跟踪源码、脚本、测试及配置只有该模块内的自引用，没有注册、调用或文档契约。

## Decision

退出未接入的建议模块，保留实际使用的质量评分和追踪所有者。不新增替代接口、占位结果或转发包装。

评分直接读取实际 boilerplate 结果和本地整数／浮点计数。等级计数字典只在当前调用创建和累加，直接作为结果返回；键、顺序和数值保持。原始文档对象、JSON 元数据、标签与可选分数仍在追踪边界处理。

可选分数转换只对标准数值转换失败返回 None；意外异常交给既有追踪入口记录并省略可选诊断。这沿用[共享标量转换所有者](2026-11-03-shared-scalar-coercion-owner.md)的错误归属，不改变合法数值、限额、阈值、评分公式或标签顺序。

## Alternatives considered

保留独立建议模块便于未来接入，但当前没有使用方，继续维护会留下没有运行契约的额外实现。直接把它接入 API 会新增功能和推荐行为，超出风格重构，因此不接入。

## Consequences

退出一个没有消费者的模块及其两个导出函数；所有实际入库和追踪调用保持。现行 API、事件和存储 schema 标识保持原样。验证使用全部跟踪引用、构造点、源码比较、Ruff 与 Python 3.11 语法；未新增、扩写或运行 Python 测试，也未运行评分器、检索、文件处理、数据库或服务。
