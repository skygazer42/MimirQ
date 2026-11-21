# Agent Note: 硬负样本加载按 query 保持 200 条上限

Status: implemented

## Problem

JSONL 加载器逐行复用同一 query_hash 的输出列表和去重集合。原 helper 只在 append 后判断长度 200；前一行已填满列表时，后一行仍能添加一个新 ID，再退出循环。真实 LTR 训练入口加载这个 lookup，按问题 hash 读取其中的完整列表。

## Decision

在原 setdefault 之后、遍历新行之前检查已有 bucket 长度，达到 200 就返回。保留原循环末的 200 条检查、去重、首次出现顺序、字符串处理、JSONL 解析、文件资源和训练侧独立选择预算。此项按 Root 已核定的最小边界单独提交，不作为整个 owner 的 style closure。

## Alternatives considered

加载完整文件后再截断列表能约束最终输出，但仍会让中间列表和 seen 持续增长，并多处理超过预算的条目，因此在已有 bucket 满额时退出 helper。提高或配置化上限会改变既有加载协议，当前仍采用原 200 条限制。

## Consequences

同一 query_hash 跨多行仍只保留最先出现的 200 个唯一 ID；后续 JSONL 行仍按原加载器解析。验证使用固定 Git 的整模块 AST，只投影该早返回与 note 静态格式／hash；没有执行业务 helper、实际 JSONL 数据、CLI、callbacks 或 Python 测试。

活跃笔记按 hard-negative、负样本和 LTR JSONL 检索，没有发现该加载上限的既有决定归属；其他排序、采样和训练策略保持原所有者。
