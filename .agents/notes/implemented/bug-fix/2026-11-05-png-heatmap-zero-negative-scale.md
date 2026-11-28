# Agent Note: PNG 热力图允许零负反馈

Status: implemented

## Problem

真实 coverage heatmap 为所有被引用文档创建行，无负反馈时 negative_feedback_count 为零。原 PNG renderer 对非空的全零列表取 max 得到零，随后用 negative／max_negative 计算条宽，导致正常全正向或无反馈数据触发除零。dataset analysis 的活动报告与 PNG 导出链直接消费这个结果。

## Decision

仅把 max_negative 的原表达式包在 max(1, 原值) 中，保证分母至少为 1。保留原字段 list／int／or 解析、空列表 fallback、绘制顺序、显示计数、条宽公式和画布。真实 producer 的 max_retrieval 本来就大于等于 1，因此不修改该分母。

## Alternatives considered

给服务或整个 renderer 加失败 fallback 可以掩盖异常，却仍无法产生正常报告，因此只修正真实分母。对两边分母一起加保护更对称，但 retrieval 的实际 Counter producer 已保证非零，当前只处理已确认的 negative 边界。

## Consequences

全零负反馈仍显示零计数和零条宽，非零负反馈的比例保持。Root 依据完整 Counter producer、真实服务调用和除法 AST 核定本修复；独立提交后仍需完成 POC13 的完整 style review。验证只投影固定 Git 整模块的这一个表达式，并核对数学来源，没有调用 PIL、renderer、DB、业务数据、CLI、callbacks 或 Python 测试，也没有修改既有 canvas 用例输入或断言。

活跃笔记按 heatmap、热力图与 PNG 检索，没有该分母决定的既有归属；PNG 任务状态、租约、TTL 和权限仍由原所有者维护。
