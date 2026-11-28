# Agent Note: 数据集问题生成沿用文档读取权限

Status: implemented

## Problem

问题生成的显式 document_ids 分支使用文档 ACL，默认范围分支也只取可见文档；dataset_id 分支却仅验证租户成员，再读取该数据集全部 completed 文档。真实 POST caller 同样只验证成员，auto-save 的后置可写检查是可选路径，不能保护生成前的文档内容和模型调用。

## Decision

保留 dataset 分支原成员检查、SQL、status 过滤、查询顺序和空集合行为，只把原查询 ID 列表交给现有 filter_allowed_document_ids。这个既有服务同时执行数据集与文档读取权限，并保留输入顺序；不修改服务定义或其他范围分支。

API 原 catch 和 status=failed 返回保持，不把服务异常改成新的 HTTP 403／404 响应。采样、配额、prompt、随机、模型和 HTTP 资源 finally 保持原样。此项按 Root 核定的活动调用链单独提交，完整 owner 的 style review 仍待完成。

## Alternatives considered

改用 list_accessible_document_ids 可以复用默认范围，但它还改变 publication、active pipeline、默认 limit 和排序，因此选择既有显式 ID 过滤服务。只检查数据集权限较短，却不能保护数据集内单个 only_me／partial_members 文档，所以使用相同的文档 ACL 边界。

## Consequences

按 dataset_id 生成只使用当前账户可读的文档，输入 ID 顺序和既有错误转换保持。验证仅核对固定 Git 整模块的这一 return-call 投影、真实 caller／callee 和 note 静态格式／hash；没有运行 DB、模型、parser、业务数据、CLI、callbacks 或 Python 测试。

活跃笔记按 test-generator 和问题生成检索；[空抽样修复](2026-11-05-test-generator-empty-diverse-sample.md)属于同一入口的另一失败边界，与本篇部分重叠并保留原决定。服务权限规则仍由现有 document_access 所有者维护。
