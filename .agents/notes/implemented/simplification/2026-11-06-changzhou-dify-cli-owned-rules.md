# Agent Note: 常州 Dify 评测与交付脚本的规则归属

Status: implemented

## Problem

评测、工作流诊断和交付脚本重复维护相同的文本、UTC、文件与控制台规则。仅按函数名合并又会混淆交付文本对 False／零的保留、不同表格压缩、列表上限和百分位算法。部分内部回调与数据库参数使用 Any，刚构造的计数又重复按原始输入解析。

## Decision

完整签名、默认值、函数体和依赖全局绑定相同的规则直接复用现有 owner。mixed-RAG 与 golden evaluator 持有各自已加载调用链中的文本、UTC 和 case 规则；trace report 持有控制台 token、错误提示与进度规则；chunk evidence 持有相同的文件与表格规则。31 份重复定义退出，trace 接收其中两份实际共享定义，原调用名称继续由直接导入提供。

新引用 trace 或 chunk evidence 的独立 CLI 使用现有仓库根路径启动形式。这两个 owner 只有标准库初始化，不给产物脚本增加 app、SDK 或 httpx 初始化。既有 app 导入、warning 过滤和 lazy model 导入仍处于原阶段。交付的 None-only 文本和依赖它的表格、chunk report 的压缩表格与八项上限，以及本地三模型的独立百分位语义继续保留。

回调按真实角色标注 Callable：外部 probe、transport 与回填结果仍允许原始返回值；私有 worker 接收一个 case，snapshot 不接收参数。私有持久化与查询参数使用真实 Session／Message 类型，引用只在 TYPE_CHECKING 下导入，所有实际类、闭包、会话与事务仍由原位置持有。

仅消费实际构造者已保证的内部值：probe 行的长度与布尔值、完整 verdict／win 计数、字典容器列表及 golden loader 的字典列表。每个 case 的字典复制保留。float 解析之后的 round 已返回整数，因此只去掉最外层 int；空值、NaN／无穷异常、算法、排序、除法与舍入次序保持。eval pack 用显式可空 records 表达 resume 分支，三个摘要字段保持原来的 None／长度结果。

原始 JSON、HTTP、配置、模型与注入回调的转换、校验和失败策略仍留在原边界。两个独立缺陷分别由[生成 JSON 字面量](../bug-fix/2026-11-06-dify-generated-json-literals.md)与[主请求错误脱敏](../bug-fix/2026-11-06-benchmark-primary-error-redaction.md)记录；本篇的纯风格整理保持两项修复及 _safe_error 的既定策略。

## Alternatives considered

新建通用 CLI 模块能集中更多 helper，但会引入另一层归属并耦合脚本初始化。现有被调用 owner 已持有完全相同的规则，直接复用即可。

统一同名文本、HTTP 和统计函数可以继续减少重复，但它们的 False／零、body、代理、错误、重试与空结果规则不同。依据完整实现和实际全局绑定选择，保留这些真实差异。

按数字或字典注解批量去掉转换更整齐，却不能证明 SDK、原始文件或回调返回值。当前只退出明确生产者已保证的内部分支；不增加 Context、manager、兼容转发或第二套统计实现。

## Consequences

完整阅读 22 个原始 owner／15,309 行及实际生产者、调用链与九份既有测试源码。阶段化完整模块 AST 投影限定全部定义迁移、导入、类型和原生表达式；共享全局绑定、静态 Signature.bind、固定 Git 字节、Ruff、格式与笔记门禁提供有界证据。七个真实类、CLI／输出字段、HTTP／鉴权、SQL／资源、重试、排序、指纹和错误边界保持。

活跃历史按脚本名、共享规则和类型边界检索，没有同一纯风格决定。上述两篇独立修复保留；[诊断与回放](2026-11-05-evidence-replay-cli-owned-values.md)、[运维 CLI](2026-11-05-maintenance-cli-owned-values.md)和[服务端 Dify 规则](2026-11-04-dify-helper-ownership.md)分别持有其他 owner，其初始化与输入边界决定继续有效，本篇不替代它们。

共享函数的源码归属与 __module__ 随直接导入指向实际 owner，调用参数和结果契约保持；以后修改这些 owner 时需要同步检查所有脚本消费者。不新增、扩写或执行 Python 测试，不运行目标模块、CLI／help、生成代码、异常、回调、业务正则、应用、SDK、模型、数据库或真实数据。静态证据不代表 Dify、网络与持久化流程已完成运行验收。
