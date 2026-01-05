"""
ZIP 图片处理器 - 从 ZIP 包中提取图片并上传到 MinIO

用于处理 MinerU/DeepDoc 等解析器返回的 Markdown + images 压缩包。
"""
from __future__ import annotations

import io
import re
import shutil
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.storage.object.minio import minio_service


class ZipImageProcessor:
    """处理 ZIP 包中的 Markdown 和图片"""

    _logger = get_logger("parsing.zip_processor")

    @staticmethod
    def _sanitize_zip_member(member_name: str) -> Path:
        """
        Convert a zip member name into a safe relative path.

        Rejects absolute paths and path traversal. Works cross-platform.
        """
        name = (member_name or "").replace("\\", "/").lstrip("/")
        posix = PurePosixPath(name)
        if not posix.parts:
            raise ValueError("Empty ZIP member name")
        if posix.is_absolute():
            raise ValueError(f"Absolute ZIP member path: {member_name}")
        if ".." in posix.parts:
            raise ValueError(f"Path traversal in ZIP member: {member_name}")
        # Windows drive letters like C:/
        first = posix.parts[0]
        if ":" in first:
            raise ValueError(f"Drive letter in ZIP member: {member_name}")
        return Path(*posix.parts)

    @classmethod
    def _safe_extract(cls, zip_ref: zipfile.ZipFile, dest_dir: Path) -> None:
        """
        Extract a zip safely (zip-slip + basic zip-bomb limits).
        """
        infos = zip_ref.infolist()
        max_files = int(getattr(settings, "ZIP_MAX_FILES", 2000))
        max_total = int(getattr(settings, "ZIP_MAX_TOTAL_UNCOMPRESSED_BYTES", 500_000_000))
        max_single = int(getattr(settings, "ZIP_MAX_SINGLE_UNCOMPRESSED_BYTES", 100_000_000))

        if len(infos) > max_files:
            raise ValueError(f"ZIP contains too many files: {len(infos)} > {max_files}")

        total_bytes = 0
        for info in infos:
            total_bytes += int(getattr(info, "file_size", 0) or 0)
            if info.file_size and info.file_size > max_single:
                raise ValueError(f"ZIP entry too large: {info.filename} ({info.file_size} bytes)")
        if total_bytes > max_total:
            raise ValueError(f"ZIP uncompressed size too large: {total_bytes} > {max_total}")

        dest_resolved = dest_dir.resolve()
        for info in infos:
            rel = cls._sanitize_zip_member(info.filename)
            out_path = (dest_dir / rel).resolve()
            if dest_resolved != out_path and dest_resolved not in out_path.parents:
                raise ValueError(f"ZIP member escapes destination: {info.filename}")
            if info.is_dir():
                out_path.mkdir(parents=True, exist_ok=True)
                continue
            out_path.parent.mkdir(parents=True, exist_ok=True)
            with zip_ref.open(info, "r") as src, open(out_path, "wb") as dst:
                shutil.copyfileobj(src, dst)

    @staticmethod
    def _choose_markdown_file(markdown_files: List[Path]) -> Path:
        preferred = {"output.md", "result.md", "index.md", "readme.md"}
        candidates = []
        for path in markdown_files:
            parts = [p.lower() for p in path.parts]
            if "__macosx" in parts:
                continue
            candidates.append(path)
        if not candidates:
            candidates = markdown_files

        for name in preferred:
            for path in candidates:
                if path.name.lower() == name:
                    return path

        def sort_key(p: Path) -> tuple[int, int]:
            try:
                size = p.stat().st_size
            except Exception:
                size = 0
            return (len(p.parts), -int(size))

        candidates.sort(key=sort_key)
        return candidates[0]

    @staticmethod
    def _normalize_ref_path(raw: str) -> str:
        """
        Normalize markdown/html image path for dictionary lookup.
        Strips quotes/title fragments and leading './'.
        """
        val = (raw or "").strip()
        if not val:
            return ""
        if val.startswith("<") and ">" in val:
            val = val[1:val.index(">")].strip()
        # Drop optional title: (path "title")
        if not (val.startswith("http://") or val.startswith("https://")):
            val = val.split()[0] if val.split() else val
        val = val.strip().strip('"').strip("'")
        val = val.split("#", 1)[0].split("?", 1)[0]
        val = val.replace("\\", "/")
        while val.startswith("./"):
            val = val[2:]
        return val

    @staticmethod
    def process_zip_with_images(
        zip_path: Path,
        dataset_id: str,
        document_id: str,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
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
            tenant_id: 租户 ID
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
                ZipImageProcessor._safe_extract(zip_ref, temp_path)

            ZipImageProcessor._logger.info("[zip] extracted to %s", temp_path)
            
            # 2. 查找 Markdown 文件
            markdown_files = list(temp_path.rglob("*.md"))
            if not markdown_files:
                ZipImageProcessor._logger.warning("[zip] no markdown found in archive")
                return {
                    "markdown": "",
                    "images": [],
                    "image_count": 0
                }
            
            # 使用第一个找到的 Markdown 文件
            md_file = ZipImageProcessor._choose_markdown_file(markdown_files)
            markdown_content = md_file.read_text(encoding="utf-8", errors="ignore")
            
            ZipImageProcessor._logger.info("[zip] markdown=%s", md_file)
            
            # 3. 查找所有图片文件
            # 统一转换为 JPEG 上传（节省存储，简化图片访问），因此仅处理常见栅格图片格式。
            image_extensions = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
            image_files: list[Path] = []
            for path in temp_path.rglob("*"):
                if not path.is_file():
                    continue
                parts_lower = [p.lower() for p in path.parts]
                if "__macosx" in parts_lower:
                    continue
                if path.suffix.lower() in image_extensions:
                    image_files.append(path)
            
            if not image_files:
                ZipImageProcessor._logger.info("[zip] no images found in archive")
                return {
                    "markdown": markdown_content,
                    "images": [],
                    "image_count": 0
                }
            
            ZipImageProcessor._logger.info("[zip] images=%s", len(image_files))
            
            # 4. 上传图片到 MinIO 并建立映射
            image_mapping = {}  # {原始相对路径: img_id}
            uploaded_images = []
            
            for idx, img_file in enumerate(image_files):
                # 计算相对路径：尽量匹配 Markdown 的引用习惯（根目录/Markdown 同目录/文件名）。
                rel_keys: list[str] = []

                try:
                    rel_root = img_file.relative_to(temp_path)
                    rel_root_str = rel_root.as_posix()
                    rel_keys.append(rel_root_str)
                except Exception:
                    rel_root_str = img_file.name

                try:
                    rel_md = img_file.relative_to(md_file.parent)
                    rel_md_str = rel_md.as_posix()
                    if rel_md_str not in rel_keys:
                        rel_keys.append(rel_md_str)
                except Exception:
                    pass

                if img_file.name not in rel_keys:
                    rel_keys.append(img_file.name)
                
                # 上传到 MinIO
                if settings.MINIO_ENABLED:
                    try:
                        from PIL import Image as PILImage

                        chunk_id = f"asset{idx}"
                        with open(img_file, 'rb') as f:
                            img_raw = f.read()

                        img = PILImage.open(io.BytesIO(img_raw))
                        if img.mode in ("RGBA", "P"):
                            img = img.convert("RGB")

                        out = io.BytesIO()
                        img.save(out, format="JPEG", quality=85, optimize=True)
                        img_data = out.getvalue()

                        img_id = minio_service.upload_image(
                            image_data=img_data,
                            tenant_id=tenant_id or dataset_id,
                            dataset_id=dataset_id,
                            document_id=document_id,
                            chunk_key=chunk_id,
                            extension="jpg",
                        )
                        
                        # 获取访问 URL
                        url = f"/api/v1/documents/image-url/{img_id}"
                        
                        for key in rel_keys:
                            normalized = ZipImageProcessor._normalize_ref_path(key)
                            if normalized:
                                image_mapping[normalized] = {"img_id": img_id, "url": url}
                        
                        uploaded_images.append({
                            "img_id": img_id,
                            "original_path": rel_root_str,
                            "url": url
                        })
                        
                        ZipImageProcessor._logger.debug("[zip] uploaded image %s -> %s", rel_root_str, img_id)
                    except Exception as e:
                        ZipImageProcessor._logger.warning("[zip] failed uploading image %s: %s", img_file, e)
            
            # 5. 替换 Markdown 中的图片引用
            if image_mapping:
                markdown_content = ZipImageProcessor._replace_image_refs(
                    markdown_content,
                    image_mapping
                )
                ZipImageProcessor._logger.info("[zip] replaced %s image refs", len(image_mapping))
            
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
            raw = match.group(2)
            normalized_path = ZipImageProcessor._normalize_ref_path(raw)

            if normalized_path and normalized_path in image_mapping:
                url = image_mapping[normalized_path].get("url")
                if not url:
                    return match.group(0)
                return f"![{alt_text}]({url})"
            return match.group(0)
        
        markdown = re.sub(
            r'!\[([^\]]*)\]\(([^)]+)\)',
            replace_md_image,
            markdown
        )
        
        # 替换 HTML img 标签：<img src="path">
        def replace_html_image(match):
            raw = match.group(1)
            normalized_path = ZipImageProcessor._normalize_ref_path(raw)

            if normalized_path and normalized_path in image_mapping:
                url = image_mapping[normalized_path].get("url")
                if not url:
                    return match.group(0)
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
