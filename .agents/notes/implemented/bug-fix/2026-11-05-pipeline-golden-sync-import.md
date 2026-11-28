# Agent Note: Golden 草稿使用同步回归导入结果

Status: implemented

## Problem

非空 Golden 草稿通过 _import_plugin_golden_draft_bundle 调用 evaluations.import_ragas_regression_cases。真实生产者是同步函数，先 flush 和 commit，再返回普通字典；消费者随后 await 该字典会在导入已提交后抛出 TypeError。

## Decision

消费者直接调用现有同步导入函数，只移除这一个内层 await。外层 helper 和路由继续异步；原参数、空 bundle 结果、schema、权限、事务、返回归一化和错误传播保持。该决定依据固定第二组基线 a9db7249603f41a707250241ee0c9e09f58bc4c4 的生产者和消费者源码。

## Alternatives considered

把评测导入改成异步函数可以保留调用处 await，但会改变所有现有同步调用者及路由的职责。生产者没有异步操作，直接消费其同步结果能将修复限制在错误所在的一行。

捕获 TypeError 后返回成功能够掩盖表面错误，但它无法区分导入前失败与提交后失败，还会吞掉其他错误，因此不增加异常回退。

## Consequences

有效非空导入不再对已提交的普通字典执行 await。同步数据库调用沿用现有执行位置；本轮不引入线程调度或新的事务边界。源码静态核对确认仅该 Await 变成原 Call，不声称运行过导入、数据库或 Python 测试。

该问题与[会话和检索 API 的同步 HTML diff 消费](../simplification/2026-11-05-api-session-retrieval-owned-values.md)有相似调用错误，但属于不同消费者，原笔记不被替代。[本组生产者边界](../simplification/2026-11-05-api-dataset-pipeline-owned-values.md)记录其余风格调整。
