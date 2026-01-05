"""
内部类型定义（非 API Schema）

- 放置服务层/流程编排使用的 dataclass、Enum 等轻量类型
- 避免放在 app/api/schemas 里造成“导入 API schema 触发 ORM/Settings 初始化”的耦合
"""

__all__ = []


