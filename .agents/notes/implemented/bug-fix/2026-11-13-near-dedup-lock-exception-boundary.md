# Agent Note: 近重复索引锁不截获业务异常

Status: implemented

## Problem

原 _file_lock 的外层 except Exception 包住 contextmanager 的 yield。锁已取得后，调用体异常会被误认为获取锁失败，随后第二次 yield；实际 ValueError 因而被 generator didn't stop after throw() 的 RuntimeError 掩盖。原文及假 fcntl／Path 已复现该错误。

## Decision

锁的导入、文件取得、flock 获取与业务 yield 分开。缺少 fcntl 的平台和真实 OSError 继续原 best-effort 无锁路径，并在有错误时记录类型；这些获取路径不会捕获其 yield 中抛出的业务异常。已取得的锁仍在 finally 尝试释放，文件仍由创建方关闭，主异常保留身份且只经过一次 yield。

load／callback／save 顺序、原 JSON version、临时替换、桶追加／裁剪／最近候选优先与零上限规则保持。原始缓存形状仍在加载边界处理；内部已经为列表的桶不再猜测 None，真实十六进制字符串在其边界解析，未知对象不会被 str() 变成似乎有效的指纹。

## Alternatives considered

- 保留大 try 而只改异常类型容易把后续业务错误再次划进锁错误范围，因此用作用域明确区分获取和消费。
- 对全部锁获取失败强制中断能提升约束，但当前近重复索引是明确可选、跨平台的 best-effort 辅助索引；本次保留该产品合同，不增加新的失败关闭策略。

## Consequences

有限 stdlib／假 OS 端口核对锁成功、缺平台、打开失败、获取失败、释放失败、业务异常与 BaseException 的释放顺序及身份；没有真实锁或索引文件。旧错误已复现，合法缓存往返、None 更新不写入、schema 与指纹结果保持。操作系统并发与真实磁盘故障未验证，Python 应用测试未新增、修改或运行。

相邻[流程函数所有者](../architecture/2026-11-13-document-pipeline-function-owners.md)继续持有原取消与资源合同；本篇只约束近重复索引的获取／消费边界，不替代该决定。
