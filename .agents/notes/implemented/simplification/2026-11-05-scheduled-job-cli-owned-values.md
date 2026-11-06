# Agent Note: 定时任务 CLI 消费本地原生值

Status: implemented

## Problem

九个定时任务／诊断 CLI 在已有归一化后重复转换整数、浮点数和布尔值。解析 benchmark 的固定 case 字段仍为 Any 字典，诊断历史 loader 和动态模块返回值也未表达实际生产者契约。

## Decision

解析模块内增加 TypedDict 描述本来就构造出的 id／Path 字段，消费者直接使用这些值；实际字典、JSON 入口校验、字段别名、路径解析和 parser SDK 的鸭子类型边界保持。历史 loader 标注为现有 Path 到字典列表的 Callable；动态 .py 模块 loader 标注 ModuleType，保留 spec／loader 检查和模块执行策略。

LTR 仅退出入口 int 转换、manifest 的 int 读取或零值回退之后的重复 int 包装。sample benchmark 仅退出本地 len、浮点公式、已规范化布尔值和经 float 归一化的排序值上的重复转换；保留原始 fixture／SDK／环境解析、统计 mean 的 float 转换、整数转浮点分母、舍入、p95 索引、empty／NaN／inf 政策和 JSON 数值类型。已校验为字典的 defaults 直接取字段，原始字段默认与转换保持。

任务分支直接使用 Python 的 if／not／any 真值检查；已由 bool、is 比较和本地布尔 helper 保证的 execute／ok 直接传递。实际服务输出使用字符串键字典注解。保留所有原 CLI 参数归一化、选项／默认／help、租户权限、SQL、上限、actor、UTC、输出和退出码。

DB maintenance 的可注入延迟依赖槽、retention 的 SimpleNamespace 依赖包、nightly 的 _Runtime／_CliError 均承担现有边界或资源职责，保持其形状和失败政策。事务、session close、asyncio.run、finally 中的设置恢复和动态 SDK 访问不改；不新增 wrapper、Context、Manager 或微模块。

## Alternatives considered

- dataclass 会改变解析 case 的字典／JSON 协议，因此只用 TypedDict。
- 按注解批量退出所有转换，会波及 raw JSON、可注入对象、整数到浮点计算和统计返回类型，因此只依据实际构造链退出重复转换。
- 重做延迟依赖或运行时包会扩大初始化、注入和资源政策变化，因此保留现有所有者。

## Consequences

95 个原函数的参数种类、名字、默认、装饰器和同步／异步种类保持。四处签名注解精确化单独列明；没有删除函数或新增业务执行层。逐文件完整源码、完整函数和模块投影、原始 argparse／SQL／资源／异常 AST、注解名字以及真实调用点静态签名绑定用于核对。未新增、扩展或执行 Python 测试，也未执行 CLI、SDK、应用、DB、模型、数据集、callback 或业务正则。

活跃笔记中的[周期审计 Row 决定](../bug-fix/2026-11-05-periodic-audit-single-column-rows.md)与本组[单列 Row 修复](../bug-fix/2026-11-05-scheduled-job-single-column-rows.md)是独立缺陷决定；本篇从修复后的快照核对等价风格整理，不把旧 Row 修复混入等价投影。
