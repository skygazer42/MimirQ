# Agent Note: 评测批处理使用固定内部记录与原生值

Status: implemented

## Problem

批处理、benchmark 和报表重复转换已经由本地 len、整数计数、浮点计算与固定字典构造保证的值。embedding、shadow 和 hybrid 的字段仍由 Any 字典表达，阅读排名和摘要时需要反复追踪上游类型。

## Decision

已有模块内的固定 embedding case／row／summary、shadow sample／delta、hybrid run config 和 recall row 使用 TypedDict，运行时继续返回原字典。shadow sample 的 sample_id 在既有组装阶段才写入，仍在进入 eligible 前完成；原始 replay row 的 str／默认／strip 解析保持。

只消费实际本地计数、排序前已转换的浮点数、已完成构造的配置和 round 结果，保留所有 raw/provider/JSON 字段解析、bool 与 NaN／inf 政策、整数转浮点分母、公式、舍入、top-k／去重先后、排序和平局。embedding 空集合的 cost 原来可为整数零，仍保留该类型；不为了类型统一改变 JSON 数值。

build_runner_result 的 kwargs 已是原生 dict，既有结果规范化函数自己创建 payload 副本，因此退出调用前的额外一次 dict copy，保留规范化所有者的副本。capture 的原 allowlist 已含 chunk_id，正常 JSON dict 上的后置回退不会增加字段，因此退出这一不可达写入；allowlist、PII 字段、指纹 JSON 与顺序保持。

AgenticRAGRunner 的缓存与资源、现有 route registry、文件写入和异常路径保持。同步 batch 与 async registry 的既有契约事实按 Root 指示保持，不在本组引入执行桥。没有新增 wrapper、Manager、Context、微模块、依赖或语言升级。

## Alternatives considered

把固定记录改成 dataclass 可以用属性访问字段，但会改变当前字典协议和 JSON 路径，所以只增加 TypedDict。统一清理所有数值与字符串转换更省代码，却会破坏 raw 输入、可注入 provider、empty／NaN 及 integer-to-float 计算边界，因此只移除源码生产者已保证的重复转换。

为 registry 添加同步／异步兼容桥可以扩大执行能力，但会改变既有 route 与 callback 策略，本组不增加这种行为。

## Consequences

评测内部字段与数值来源更直接，公开参数、返回形状、资源和业务政策保持。验证使用完整源码、实际生产者与 caller、82 个完整函数 AST、公开契约及静态绑定；没有执行评测、模型、SDK、数据集、regex、CLI、callbacks 或 Python 测试。

既有[评测协议记录](2026-11-05-evaluation-contract-native-values.md)属于已接受的 metrics／datasets／results owner，保持原代码与决定；本篇只记录 batch／benchmark／reporting 的内部构造边界和其规范化函数消费者，不替代或重计那 13 个 owner。
