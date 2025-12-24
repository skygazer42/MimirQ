"""
ZIP 图片处理器 - 从 ZIP 包中提取图片并上传到 MinIO

用于处理 MinerU/DeepDoc 等解析器返回的 Markdown + images 压缩包。
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import tempfile
import shutil

from app.services.minio_service import minio_service
from app.core.config import settings


class ZipImageProcessor:
    """处理 ZIP 包中的 Markdown 和图片"""

    @staticmethod
    def process_zip_with_images(
        zip_path: Path,
        dataset_id: str,
        document_id: str
    ) -> Dict[str, any]:
        """
        处理包含 Markdown 和图片的 ZIP 文件。
        
        流程：
        1. 解压 ZIP 到临时目录
        2. 查找 Markdown 文件
        3. 提取所有图片并上传到 MinIO
        4. 替换 Markdown 中的图片引用为 MinIO URL
        5. 返回处理后的 Markdown 和图片映射
        
        Args:
            zip_path: ZIP 文件路径
            dataset_id: 知识库 ID
            document_id: 文档 ID
        
        Returns:
            {
                "markdown": "处理后的 Markdown 内容",
                "images": [{"img_id": "...", "original_path": "...", "url": "..."}],
                "image_count": 数量
            }
        """
        temp_dir = None
        try:
            # 1. 创建临时目录并解压
            temp_dir = tempfile.mkdtemp(prefix="zip_extract_")
            temp_path = Path(temp_dir)
            
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_path)
            
            print(f"[ZIP处理] 已解压到: {temp_path}")
            
            # 2. 查找 Markdown 文件
            markdown_files = list(temp_path.rglob("*.md"))
            if not markdown_files:
                print("[WARN] ZIP 包中未找到 Markdown 文件")
                return {
                    "markdown": "",
                    "images": [],
                    "image_count": 0
                }
            
            # 使用第一个找到的 Markdown 文件
            md_file = markdown_files[0]
            markdown_content = md_file.read_text(encoding="utf-8")
            
            print(f"[ZIP处理] 找到 Markdown: {md_file.name}")
            
            # 3. 查找所有图片文件
            image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'}
            image_files = []
            for ext in image_extensions:
                image_files.extend(temp_path.rglob(f"*{ext}"))
            
            if not image_files:
                print("[ZIP处理] ZIP 包中未找到图片文件")
                return {
                    "markdown": markdown_content,
                    "images": [],
                    "image_count": 0
                }
            
            print(f"[ZIP处理] 找到 {len(image_files)} 张图片")
            
            # 4. 上传图片到 MinIO 并建立映射
            image_mapping = {}  # {原始相对路径: img_id}
            uploaded_images = []
            
            for idx, img_file in enumerate(image_files):
                # 计算相对路径（相对于 ZIP 根目录或 Markdown 所在目录）
                try:
                    rel_path = img_file.relative_to(temp_path)
                except ValueError:
                    rel_path = img_file.relative_to(md_file.parent)
                
                rel_path_str = str(rel_path).replace("\\", "/")
                
                # 上传到 MinIO
                if settings.MINIO_ENABLED:
                    try:
                        chunk_id = f"{document_id}-img{idx}"
                        with open(img_file, 'rb') as f:
                            img_data = f.read()
                        
                        img_id = minio_service.upload_image(
                            image_data=img_data,
                            dataset_id=dataset_id,
                            chunk_id=chunk_id,
                            extension=img_file.suffix.lstrip('.')
                        )
                        
                        # 获取访问 URL
                        url = f"/api/v1/documents/image-url/{img_id}"
                        
                        image_mapping[rel_path_str] = {
                            "img_id": img_id,
                            "url": url
                        }
                        
                        uploaded_images.append({
                            "img_id": img_id,
                            "original_path": rel_path_str,
                            "url": url
                        })
                        
                        print(f"[ZIP处理] 上传图片: {rel_path_str} -> {img_id}")
                    except Exception as e:
                        print(f"[WARN] 图片上传失败 {rel_path_str}: {e}")
            
            # 5. 替换 Markdown 中的图片引用
            if image_mapping:
                markdown_content = ZipImageProcessor._replace_image_refs(
                    markdown_content,
                    image_mapping
                )
                print(f"[ZIP处理] 已替换 {len(image_mapping)} 处图片引用")
            
            return {
                "markdown": markdown_content,
                "images": uploaded_images,
                "image_count": len(uploaded_images)
            }
            
        finally:
            # 清理临时目录
            if temp_dir and Path(temp_dir).exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _replace_image_refs(
        markdown: str,
        image_mapping: Dict[str, Dict[str, str]]
    ) -> str:
        """
        替换 Markdown 中的图片引用。
        
        支持的格式：
        - ![alt](path/to/image.png)
        - ![](./images/pic.jpg)
        - <img src="path/to/image.png">
        """
        # 替换 Markdown 语法：![alt](path)
        def replace_md_image(match):
            alt_text = match.group(1)
            img_path = match.group(2)
            
            # 规范化路径（移除 ./ 前缀）
            normalized_path = img_path.lstrip("./")
            
            if normalized_path in image_mapping:
                url = image_mapping[normalized_path]["url"]
                return f"![{alt_text}]({url})"
            return match.group(0)
        
        markdown = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            replace_md_image,
            markdown
        )
        
        # 替换 HTML img 标签：<img src="path">
        def replace_html_image(match):
            img_path = match.group(1)
            normalized_path = img_path.lstrip("./")
            
            if normalized_path in image_mapping:
                url = image_mapping[normalized_path]["url"]
                return f'<img src="{url}"'
            return match.group(0)
        
        markdown = re.sub(
            r'<img\s+src="([^"]+)"',
            replace_html_image,
            markdown
        )
        
        return markdown


# 全局实例
zip_image_processor = ZipImageProcessor()

