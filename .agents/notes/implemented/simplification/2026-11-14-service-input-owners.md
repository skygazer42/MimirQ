# Agent Note: 服务消费已建立的输入并直接依赖实际所有者

Status: implemented

## Problem

内部统计重复把已经由解析器、SQL 或 token 生产者构造的整数当成未知值转换，分位数重复防护已经排除的空数组。单次覆盖率、JSONL 和时间转发让调用方绕过实际所有者；另有无生产根的热重载 DTO 和跨数据集报告副本。

聊天代码还有未使用的入参、真实 TAG owner 前的签名猜测、只转发十五个同名字段的构造函数和无生产消费者的 facade 导出。它们增加阅读成本，没有增加独立业务责任。

## Decision

coverage 与 chunk stats 接收实际生产者已经构造的原生整数集合，直接裁剪或筛正值；percentile 只在已非空排序后调用，不再返回合成的零值。unit 声明实际 chars／tokens。版本差异直接接收 API 已构造的字符串列表，保重复权重、排序和 sample_limit=0。原始 JSON、nullable SQL／metadata、外部引用、真正可选字段和失败入口仍留在各自边界。

DB catalog 事件直接消费执行 wrapper 已经产生的字符串 ID、浮点耗时和字典结果；真正可空的 catalog 字段继续转换。embedding advisories 的模型 ID 组合直接接收唯一调用方已清理的字符串；工厂直导实际 adapter，声明真实返回类，不改变 lru8、凭证、空间指纹和客户端创建时点。

分类和预检 diff 删除已建立结果之后的重复判断与转换。raw JSON 数字转换仍保原 TypeError／ValueError／OverflowError 的 None／零语义，程序错误不伪装成成功解析。命中率统计保缺失／零时间戳、旁路日志错误隔离与真实读预算，直接调用 JSONL owner。

预览 API 和离线批量评估脚本直接导入 coverage owner，previewUtils 的同体纯转发退出，其余完整 AST 保持。初次作者冻结漏迁实际脚本，由独立复核发现后捕获脚本原文再修正；原报告保留，不以补兼容 alias 掩盖遗漏。脚本只调整 import 和唯一 callee，不给整文件完成额度，也不执行评估。

config_hot_reload 与 cross_dataset_dedup_report 两个无生产、脚本、配置或动态注册根的模块退出。原始源码保存在不可变基线，冻结测试仍有真实直接引用，不宣称全仓零引用。实际 ops snapshot 与 near-dup summary 所有者保留，不按文件名移除业务。

聊天调用方直接导入实际 bootstrap／cache 所有者，删除无根重导出、未读参数、同名字段构造包装和两处 TAG 签名适配。真实请求状态、缓存、Future、Session、事务、流式关闭和持久化默认值保留；六个已有 key-only Future 调用不在本篇改变协议。冻结测试的 facade 类型和旧关键字引用留待维护，不保生产壳。

索引清理直接解包查询固定投影的三列，通过实际 Query.yield_per 读取；不保留为人工行形状编写的六个适配函数。管线插件引用直接调用实际校验所有者，分块预览直接使用质量生产者已经裁剪的完整字段构造 DTO。外部缓存、解析器响应与历史 metadata 仍按原边界处理，提供的 Docling Session 以 None 区分所有权。

入库策略的规则、预处理步骤、列表和字符串由既有 Pydantic 模型建立，内部不再把它们重新当成未知对象。白名单、实际长度上限、历史读取降级和正则非匹配政策保持。FLS 的损坏配置单独执行[明确失败](../bug-fix/2026-11-14-field-policy-corruption-fails-closed.md)，不能把入库历史降级挪到权限判断。

parser_strategy_policy 和 phoenix_adapter 没有应用、脚本、配置或动态注册消费者，整模块退出；自身 __all__ 不算调用根。表格目录常量和单次转发、两个未调用的策略元数据包装也退出。SAML 删除未使用的内部 acs_url 参数并同步唯一真实调用方，请求字段保留，真正的接收地址仍由配置提供。初始化管理员仅清理多余括号，完整 AST 保持。

表格规划器直接使用图构造阶段提供的候选、分数和诊断，别名与样本集合在归一化后不再可空；未知行数继续为 None。四条 SQL 生成路径共用一个诊断投影，原模型生成与确定性降级各自保留失败边界。TAG 的同一模型工厂供语义过滤复用，未使用的内部策略参数和开关转发退出，真实 API 调用同步；外部请求字段保留。无消费者的 Excel 兼容包装与旧 SQL 便利入口删除，没有为冻结测试补壳。

缓存与运行服务直接使用已捕获的正 TTL、原生 Pydantic 字段集、计数和诊断结果；trace 的同体字符串清理归现有实现。真实 Cache、Lease、Session、心跳、取消、队列、范围和观测降级保持。工作簿的 chartsheet 或只读工作表确实可能没有行列维度，保留其实际缺省，不能按普通非空整数删除。

证据与反馈内部计数、完整构造结果和已成立的类型直接消费；输入文件、外部引文、时间及追踪 ID 的真实边界由[导入与反馈规则](../bug-fix/2026-11-14-import-and-feedback-input-boundaries.md)持有。无消费者的 CoverageHeatmap 声明与融合权重学习 service 退出，真实 API heatmap schema、离线学习脚本、运行融合与租户配置保持。

评估标识清洗复用已有 telemetry 所有者，SourceBuilder 的原 255 长度在每个真实调用显式保留，其他领域的 2000 缺省不混用。只删 normalizer 已经保证的固定 schema／route／列表重复校验；缺失／重复样本、标注状态、manifest、原始模型输出、科学指标与绘图模板的实际政策保持。小文件按真实公共库、CLI、公式和资源职责保留，不为了数量把不同指标硬合成一层。

入库看板、评估运行、查询集健康、报告和 RTBF 直接使用本地 Counter／字典／Pydantic 计数，必需 Callable 与实际执行返回类型在原签名表达。KG 社区、合并顺序、快照索引及词法排名使用其生产者已经建立的浮点数、列表和必需键；原始 JSON、nullable ORM、ACL、范围、排序、预算、事务、任务中止及可选审计保持。HTML 报告只统一 Python 3.11 可用的引号与排版，模板字符串及 f-string 表达式原值不变，不宣称实际渲染通过。

最后的评估工具保留真实公共算法、模块 CLI、科学计算与资源边界，不按应用直接调用数量删除库能力。重复 gold chunk 的 DCG／AP 收益由[独立缺陷修复](../bug-fix/2026-11-14-kg-diagnostic-duplicate-gain.md)持有，不计作等价风格调整。

本篇部分更新[运维审计记录](2026-11-05-service-operations-owned-values.md)的已知输入边界和[运维 CLI](2026-11-05-maintenance-cli-owned-values.md)的实际依赖现状；原资源、持久化及参数政策仍成立。瞬时文档统计和持久元数据写入仍是[不同责任](2026-11-04-document-user-metadata-owner.md)，不为了少文件混合。

## Alternatives considered

- 保留所有转型可兼容人工构造的未知对象，但会模糊实际输入和内部结果；在真实生产者处建立一次契约。
- 将所有 safe-int、raw JSON 和可空字段合成一个工具会混合不同缺失、负值和失败规则；只合并已证明同一业务规则的实现。
- 为少 import 新建 Context、依赖字典或全局聚合入口仍会隐藏实际依赖；用具名实际所有者，真实状态与资源对象继续保留。
- 恢复旧 helper 可让遗漏脚本暂时导入，但会留下第二个维护位置；同步真实脚本后删除转发。

## Consequences

主流程能直接看见数据和调用来源，已确认的闲置模块及若干同体转发退出，没有新增 app 模块。内部无契约的字符串／None 整数集合或缺失版本集合不再被容忍；实际 API 生产者和外部 JSON／nullable 边界保持，不声称所有 None 或异常捕获都应消失。

Path 的 fail-closed 和 quota 的既定故障放行分别保留，原始 metadata 与安全旧预览引用也保留。这些是不同业务责任，不能只看判断数量归为多余。

表格导入和查询的[实际错误边界](../bug-fix/2026-11-14-table-store-boundaries.md)另行记录。LOTUS 原有的大提示词半块裁减与响应补 False 策略保持，本次不增加模型调用或宣称已修复该旧策略；DOCX 标题规则的旧字面量也没有凭猜测改写。静态风格复核不代表这些功能已通过真实 SDK 或业务集成。

验证包括限定的完整 AST 变换、实际 producer／caller、原生 histogram／token 数据计算和受控日志／读取／配置端口。独立复核闭合脚本根遗漏；没有运行应用测试、离线 CLI、SDK／模型、真实文件、数据库、网络或锁线程。previewUtils 的前次局部增量现已完成全文复核，全文结论与每个文件的当前哈希由逐文件清单单独记录。
