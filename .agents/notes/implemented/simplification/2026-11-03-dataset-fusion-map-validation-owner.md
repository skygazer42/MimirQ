# Agent Note: Dataset fusion map validation owner

Status: implemented

## Problem

`DatasetRAGDefaults` declares fusion maps as `dict[str, int]` or `dict[str, float]`, but its after-model validator repeated dictionary checks and cast each value only to discard the converted result. Pydantic already owns the external shape and value-type boundary.

## Decision

Pydantic validates the declared fusion map shape and numeric types. The `DatasetRAGDefaults` model validator retains its dataset-specific fusion channel allowlist. Nonnegative and upper bounds remain in `ChatRAGConfig` after dataset defaults merge, where the effective request is normalized.

`ChatRAGConfig` 将字段集中声明，融合预算与最小分数的单次 helper、参数规则 dataclass 合回模型校验器。保留原 after-model 顺序、错误文案、通道去空白／小写、重名键覆盖及空映射规则；两个可空映射仍在原位置写回，避免改变 `model_fields_set` 对数据集默认值合并的影响。权重归一化继续发生在预设应用之前。

预设应用直接读取同一生产者返回的字段。必需数值与布尔值不再转型，层级预设一次应用其完整字段组，fast 预设保留显式 `sparse_retrieval_enabled=False`。生产者没有产生 sparse provider 覆盖，因此不保留猜测性的赋值分支；输入的 provider 字段继续保留。默认预设的判断沿用实际值比较，显式提供与默认相同的值仍保持原政策。

## Alternatives considered

- Keep checking and converting every value in the after-validator: this appears defensive, but duplicates field validation and can accept behavior outside the declared type when internal model construction bypasses normal validation.
- Move effective fusion bounds into dataset metadata validation: this would change where invalid stored defaults fail and risks rejecting legacy values before a chat request applies its effective contract.

## Consequences

Normal API and metadata parsing has one owner for map/value typing, while channel allowlisting and effective request bounds remain explicit. Unsupported channel names still fail schema validation. Python tests were not run per user instruction.

## Verification

Ruff check, Ruff format --check, `git diff --check`, and stale-helper scanning passed. Dataset route and `rag_defaults` service call sites were reviewed. Python tests and runtime validation were not run.

聊天 schema 增量对照修改前的完整源码：59 个 RAG 字段的顺序、注解、默认值与约束不变；17 个其他公开模型在配置声明位置归一后 AST 相同，TokenUsage 的推导不变。静态核对真实预设生产者的固定键、层级字段组和输入值类型，未执行预设、Pydantic 模型或业务函数。无生产调用或注册的 StreamEvent 退出，不新增替代类型或兼容壳；Python 测试按用户要求不修改、不运行。限定 Ruff／格式、Python 3.11 AST／编译通过。149 篇 Note 的格式与归档检查通过，目录链接门禁仍因既有的十处缺失笔记引用失败；静态结果不视为请求或检索运行验收。
