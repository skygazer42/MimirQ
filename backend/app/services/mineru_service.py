"""
MinerU 文档解析服务

支持两种模式：
1. MinerU 在线 API：https://mineru.net（返回 Markdown URL）
2. MinerU 本地服务：返回 ZIP 包（Markdown + images）

两种模式都支持高级 PDF 解析（表格、图片、公式等）
"""
import requests
import time
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.utils.zip_processor import zip_image_processor
from app.rag.core.logging import get_logger


logger = get_logger("services.mineru")


class MinerUService:
    """MinerU 在线解析服务"""

    def __init__(self):
        self.api_base = settings.MINERU_API_BASE
        self.api_token = settings.MINERU_API_TOKEN
        self.model_version = settings.MINERU_MODEL_VERSION
        self.local_server_url = (getattr(settings, "MINERU_LOCAL_SERVER_URL", "") or "").strip() or None
        # MinerU 本地服务不需要 API Token；在线 API 需要。
        self.enabled = bool(settings.MINERU_ENABLED) and (bool(self.api_token) or bool(self.local_server_url))

        if not self.enabled:
            logger.warning(
                "MinerU is disabled. Set MINERU_ENABLED=True and configure "
                "MINERU_API_TOKEN (online) or MINERU_LOCAL_SERVER_URL (local) to enable."
            )

    def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "*/*"
        }

    def apply_upload_url(self, filename: str, data_id: str) -> Dict[str, Any]:
        """
        申请单个文件上传 URL

        Args:
            filename: 文件名
            data_id: 自定义数据 ID（用于标识文件）

        Returns:
            {
                "batch_id": "xxx",
                "upload_url": "https://...",
                "data_id": "xxx"
            }
        """
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")

        url = f"{self.api_base}/file-urls/batch"
        data = {
            "files": [{"name": filename, "data_id": data_id}],
            "model_version": self.model_version
        }

        try:
            response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("code") == 0:
                batch_id = result["data"]["batch_id"]
                upload_url = result["data"]["file_urls"][0]
                return {
                    "batch_id": batch_id,
                    "upload_url": upload_url,
                    "data_id": data_id
                }
            else:
                raise Exception(f"Apply upload URL failed: {result.get('msg', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error when applying upload URL: {str(e)}")

    def apply_batch_upload_urls(
        self,
        files: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        批量申请文件上传 URL

        Args:
            files: 文件列表，格式: [{"name": "file1.pdf", "data_id": "id1"}, ...]
                   最多 200 个文件

        Returns:
            {
                "batch_id": "xxx",
                "file_urls": ["https://...", "https://..."],
                "files": [{"name": "...", "data_id": "..."}, ...]
            }
        """
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")

        if len(files) > 200:
            raise ValueError("Maximum 200 files per batch")

        url = f"{self.api_base}/file-urls/batch"
        data = {
            "files": files,
            "model_version": self.model_version
        }

        try:
            response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("code") == 0:
                return {
                    "batch_id": result["data"]["batch_id"],
                    "file_urls": result["data"]["file_urls"],
                    "files": files
                }
            else:
                raise Exception(f"Apply batch upload URLs failed: {result.get('msg', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error when applying batch upload URLs: {str(e)}")

    def upload_file(self, file_path: Path, upload_url: str) -> bool:
        """
        上传文件到 MinerU

        Args:
            file_path: 本地文件路径
            upload_url: 申请到的上传 URL

        Returns:
            上传是否成功
        """
        try:
            with open(file_path, 'rb') as f:
                # 注意：MinerU 上传不需要设置 Content-Type
                response = requests.put(upload_url, data=f, timeout=300)
                response.raise_for_status()
                return response.status_code == 200

        except Exception as e:
            logger.error("Upload file failed: %s", e)
            return False

    def get_task_status(self, batch_id: str) -> Dict[str, Any]:
        """
        查询解析任务状态

        Args:
            batch_id: 批次 ID

        Returns:
            任务状态信息
        """
        if not self.enabled:
            raise Exception("MinerU is not enabled.")

        url = f"{self.api_base}/extract/task/{batch_id}"

        try:
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            result = response.json()

            if result.get("code") == 0:
                return result["data"]
            else:
                raise Exception(f"Get task status failed: {result.get('msg', 'Unknown error')}")

        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error when getting task status: {str(e)}")

    def wait_for_completion(
        self,
        batch_id: str,
        timeout: int = 600,
        poll_interval: int = 5
    ) -> Dict[str, Any]:
        """
        等待解析任务完成

        Args:
            batch_id: 批次 ID
            timeout: 超时时间（秒）
            poll_interval: 轮询间隔（秒）

        Returns:
            完成后的任务状态
        """
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Task {batch_id} timeout after {timeout} seconds")

            status = self.get_task_status(batch_id)
            task_status = status.get("status")

            logger.info("Task %s status: %s", batch_id, task_status)

            if task_status == "completed":
                return status
            elif task_status == "failed":
                raise Exception(f"Task {batch_id} failed: {status.get('error', 'Unknown error')}")

            time.sleep(poll_interval)

    def download_result(self, result_url: str) -> str:
        """
        下载解析结果（Markdown 格式）

        Args:
            result_url: 结果下载 URL

        Returns:
            Markdown 内容
        """
        try:
            response = requests.get(result_url, timeout=60)
            response.raise_for_status()
            return response.text

        except requests.exceptions.RequestException as e:
            raise Exception(f"Download result failed: {str(e)}")

    def parse_file(
        self,
        file_path: Path,
        data_id: Optional[str] = None
    ) -> List[Document]:
        """
        完整的文件解析流程（上传 → 等待 → 下载结果）

        Args:
            file_path: 本地文件路径
            data_id: 自定义数据 ID（可选）

        Returns:
            解析后的 LangChain Document 列表
        """
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")

        # 1. 申请上传 URL
        data_id = data_id or str(file_path.stem)
        logger.info("Applying upload URL for %s...", file_path.name)
        upload_info = self.apply_upload_url(file_path.name, data_id)

        batch_id = upload_info["batch_id"]
        upload_url = upload_info["upload_url"]

        # 2. 上传文件
        logger.info("Uploading %s...", file_path.name)
        success = self.upload_file(file_path, upload_url)
        if not success:
            raise Exception(f"Failed to upload {file_path.name}")

        logger.info("Upload complete. Batch ID: %s", batch_id)

        # 3. 等待解析完成
        logger.info("Waiting for parsing completion...")
        result = self.wait_for_completion(batch_id, timeout=600, poll_interval=5)

        # 4. 下载解析结果
        result_url = result.get("result_url")
        if not result_url:
            raise Exception("No result URL in response")

        logger.info("Downloading result...")
        markdown_content = self.download_result(result_url)

        # 5. 转换为 LangChain Document
        metadata = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser": "mineru",
            "batch_id": batch_id,
            "data_id": data_id,
            "model_version": self.model_version
        }

        logger.info("Parse complete. Content length: %s chars", len(markdown_content))

        return [Document(page_content=markdown_content, metadata=metadata)]

    def parse_file_local(
        self,
        file_path: Path,
        dataset_id: str,
        document_id: str,
        params: Optional[Dict[str, Any]] = None
    ) -> List[Document]:
        """
        使用本地 MinerU 服务解析文件（返回 ZIP 包含 Markdown + images）。
        
        Args:
            file_path: 本地文件路径
            dataset_id: 知识库 ID
            document_id: 文档 ID  
            params: 解析参数
        
        Returns:
            解析后的 LangChain Document 列表（图片已上传到 MinIO）
        """
        if not self.local_server_url:
            raise Exception(
                "MinerU 本地服务未配置。请设置 MINERU_LOCAL_SERVER_URL，"
                "例如：http://localhost:30001"
            )
        
        parse_endpoint = f"{self.local_server_url}/file_parse"
        params = params or {}
        
        # 构建请求参数
        data = {
            "lang_list": params.get("lang_list", ["ch"]),
            "backend": params.get("backend", "vlm-http-client"),
            "parse_method": params.get("parse_method", "auto"),
            "return_md": True,
            "response_format_zip": True,
            "return_images": True,
        }
        
        # vlm-http-client 后端需要 server_url
        if data["backend"] == "vlm-http-client":
            mineru_vl_server = getattr(settings, 'MINERU_VL_SERVER', None)
            if mineru_vl_server:
                data["server_url"] = mineru_vl_server
        
        logger.info("MinerU local parsing started: %s", file_path.name)
        
        try:
            # 发送文件
            with open(file_path, "rb") as f:
                files = {"files": (file_path.name, f, "application/octet-stream")}
                response = requests.post(
                    parse_endpoint,
                    files=files,
                    data=data,
                    timeout=300
                )
            
            response.raise_for_status()
            
            # 检查响应是否为 ZIP
            content_type = response.headers.get('Content-Type', '')
            if 'zip' not in content_type.lower() and 'application/octet-stream' not in content_type.lower():
                # 尝试解析为 JSON 错误
                try:
                    error_data = response.json()
                    raise Exception(f"MinerU 解析失败: {error_data}")
                except (ValueError, TypeError) as json_err:
                    raise Exception(f"MinerU 返回非预期格式: {content_type}") from json_err
            
            # 保存 ZIP 到临时文件
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip.write(response.content)
                tmp_zip_path = Path(tmp_zip.name)
            
            try:
                # 处理 ZIP：提取图片并上传到 MinIO
                result = zip_image_processor.process_zip_with_images(
                    zip_path=tmp_zip_path,
                    dataset_id=dataset_id,
                    document_id=document_id
                )
                
                markdown_content = result["markdown"]
                images = result["images"]
                
                logger.info(
                    "MinerU local parse done: %s chars, %s images",
                    len(markdown_content),
                    len(images),
                )
                
                # 构建 metadata
                metadata = {
                    "source": file_path.name,
                    "file_type": file_path.suffix.lstrip('.'),
                    "parser": "mineru_local",
                    "image_count": len(images),
                    "images": images,  # [{img_id, original_path, url}]
                }
                
                return [Document(page_content=markdown_content, metadata=metadata)]
                
            finally:
                # 清理临时 ZIP 文件
                if tmp_zip_path.exists():
                    tmp_zip_path.unlink()
        
        except Exception as e:
            logger.error("MinerU local parsing failed: %s", e)
            raise Exception(f"MinerU 本地解析失败: {str(e)}")


# 全局实例
mineru_service = MinerUService()
