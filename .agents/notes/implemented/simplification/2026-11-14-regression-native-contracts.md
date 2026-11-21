# Agent Note: 回归比较消费模型与数据库已经建立的契约

Status: implemented

## Problem

回归导出重新探测真实 ORM 的 UUID／datetime，用 getattr 和默认值容忍任意对象；trace diff 给必填 Pydantic 模型合成空对象。case import 在已验证 BundleItem 之后再次猜测 dict、模型或普通对象，内部 score／Counter／固定键也重复转型。

## Decision

实际 API 与 KG 查询已经提供原生 UUID 和 nullable dataset 投影，case-scope 直接 set／dict 校验，保持 Missing 先于 DatasetMismatch 及原 404／400 转换。导出直接使用持久 ORM 的必有 UUID、可空 datetime 和已解析整数预算；nullable dataset、JSON 列、PII 默认、include_text／contexts 门控与实际 sanitizer 调用保持。

case import 直接接收现有 RagasRegressionCaseBundleItem，并按原 JSON 模式 model_dump。无用的 dataset_id 内部入参退出，唯一真实调用方同步迁移；租户、授权和持久化仍由原 importer 持有，其余完整 AST 保持，不能算 importer 全文完成。

RagTrace 模型、citations 列表和整数计数直接消费；真正可空 elapsed 使用明确的 None 语义。已构造 metric_value、regressed、fingerprint map 和 Counter 的键直接读取，固定正权重与已配对 float 不二次转换；保原 raw JSON、缺失分数、NaN／inf／bool 差异和实际缺省政策，不把不同 numeric parser 合成一个 safe 工具。

统计公式、近似方法、bootstrap／BH、权重数据、舍入、排序与限额保持。没有借“规范”修正统计学方法或添加运行时模型层；真实状态与资源对象仍保留。

core 的 formula_calculator、command 和 interrupt 三份无生产根模块连同六个 lazy 转出退出。原 app／scripts／配置／star／importlib 闭包只有相互引用与包转出，既有源码保存在不可变基线；不为了未知仓库外调用者保留空壳，不删除有真实根的 logging、errors、http、vision 和 verifier 所有者。

本篇沿用[模型评测边界](2026-11-05-model-evaluation-owned-boundaries.md)的“证明实际生产者后简化”原则；其 evaluator、多态、SDK、raw score 和引用优先级仍独立保留。

## Alternatives considered

- 保留任意对象的 getattr 兼容能容纳更多手写替身，却会掩盖模型已经保证的必需字段；同步真实调用方并表达具体类型。
- 把所有原始 JSON 变成一个新的通用 adapter 可以集中判断，但不同字段有不同缺省与错误含义；只删内部重复，保实际边界。
- 仅隐藏 command 转出而保留整套旧实现可减少删除量，但没有生产消费者，仍留下未维护的第二套流程控制；一起退出完整闭包。

## Consequences

顺着函数签名与实际 owner 能判断数据从哪里进入，重复 UUID、None 和多态探测减少。无契约的 dict／空对象／字符串 UUID 内部调用不再保留；HTTP 请求、真实 nullable 与原始数据边界保持。

有界验证使用实际 Pydantic 数据声明、ORM 形状、标准库统计、固定时钟与受控 hash／citation 端口，核对真实数据和原错误顺序；整个未改业务 AST 另外绑定。没有运行应用测试、真实 DB／SDK、模型、网络、业务文件或线程，不声称统计准确性、生产性能或仓库外兼容性已验证。
