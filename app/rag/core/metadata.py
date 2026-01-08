"""
元数据规范化工具

目标：
- 在不同解析器/切块器输出的 metadata 之间做兼容归一
- 避免业务逻辑分散在多个模块里各自“补丁式处理”
"""


from typing import Any, Dict


def normalize_image_metadata(meta: Dict[str, Any]) -> Dict[str, Any]:
    """
    归一化图片相关字段：
    - img_id / image_id
    - img_url / image_url

    约定：
    - 保留原字段（不强制删除），仅补齐缺失的标准字段
    - 标准字段优先级：image_* 优先，其次 img_*
    """
    if not isinstance(meta, dict):
        return {}

    img_id = meta.get("img_id")
    image_id = meta.get("image_id")
    if not image_id and img_id:
        meta["image_id"] = img_id
    if not img_id and image_id:
        meta["img_id"] = image_id

    img_url = meta.get("img_url")
    image_url = meta.get("image_url")
    if not image_url and img_url:
        meta["image_url"] = img_url
    if not img_url and image_url:
        meta["img_url"] = image_url

    return meta


__all__ = ["normalize_image_metadata"]


