# Agent Note: 问题生成在多样性抽样为空时返回空结果

Status: implemented

## Problem

文档查询非空不代表抽样后仍有 chunk。多样性抽样会过滤 strip 后不足 50 字符的内容，真实 DocumentChunk 的 Text 字段没有这个最小长度约束。原流程在抽样为空时仍创建 HTTP／LLM 资源，再用 len(sampled_chunks) 作除数，导致活动问题生成端点失败。

## Decision

在 sampled_chunks 赋值后、创建客户端前检查空列表，并按已有 empty-chunks 策略返回 []。其余完整模块保持，包括过滤阈值、采样／随机次数、问题配额、prompt、SQL 与权限、资源 finally 和 API 既有错误转换。

## Alternatives considered

把除数改成 max(1, len(sampled_chunks)) 可以避免除零，但没有可处理的 chunk 时仍会创建客户端并解析 prompt，因此在资源创建前直接沿用已有空结果策略。放宽 50 字符阈值会改变样本质量政策，当前不调整。

## Consequences

全部 chunk 太短的文档生成请求返回空结果，不建立无用的模型或 HTTP 资源。此项经 Root 按真实 POST、SQL 模型、抽样与除法链核定，独立于 style closure。静态验证仅给固定 Git 整模块投影这一个早返回，未运行模型、DB、parser、数据、CLI、callbacks 或 Python 测试。

按 test-generator、问题生成和真实函数名检索活跃笔记，没有发现该空抽样决定的既有归属；采样和 prompt 政策仍属于原模块。

同一入口的数据集权限边界见[文档 ACL 修复](2026-11-05-test-generator-dataset-document-acl.md)，两篇分别记录独立失败原因，保持各自决定。
