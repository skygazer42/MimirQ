"""
API 请求/响应数据模型

定义 API 接口的 Pydantic 验证模型。

注意：
- 内部服务编排使用的 dataclass/Enum 已迁移至 `app/types/`
- 请在业务代码中直接 import `app.api.schemas.<xxx>`（Pydantic）或 `app.types.<xxx>`（内部类型）
"""
