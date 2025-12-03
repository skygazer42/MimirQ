"""
MinerU 在线文档解析服务

支持通过 MinerU 在线 API 进行高级 PDF 解析（表格、图片、公式等）
官网：https://mineru.net
"""
import requests
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document

from app.config import settings


class MinerUService:
    """MinerU 在线解析服务"""

    def __init__(self):
        self.api_base = settings.MINERU_API_BASE
        self.api_token = settings.MINERU_API_TOKEN
        self.model_version = settings.MINERU_MODEL_VERSION
        self.enabled = settings.MINERU_ENABLED and bool(self.api_token)

        if not self.enabled:
            print("⚠️  MinerU is disabled. Set MINERU_ENABLED=True and configure MINERU_API_TOKEN to enable.")

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
            print(f"❌ Upload file failed: {str(e)}")
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

            print(f"📊 Task {batch_id} status: {task_status}")

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
        print(f"📤 Applying upload URL for {file_path.name}...")
        upload_info = self.apply_upload_url(file_path.name, data_id)

        batch_id = upload_info["batch_id"]
        upload_url = upload_info["upload_url"]

        # 2. 上传文件
        print(f"⬆️  Uploading {file_path.name}...")
        success = self.upload_file(file_path, upload_url)
        if not success:
            raise Exception(f"Failed to upload {file_path.name}")

        print(f"✅ Upload complete. Batch ID: {batch_id}")

        # 3. 等待解析完成
        print(f"⏳ Waiting for parsing completion...")
        result = self.wait_for_completion(batch_id, timeout=600, poll_interval=5)

        # 4. 下载解析结果
        result_url = result.get("result_url")
        if not result_url:
            raise Exception("No result URL in response")

        print(f"📥 Downloading result...")
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

        print(f"✅ Parse complete. Content length: {len(markdown_content)} chars")

        return [Document(page_content=markdown_content, metadata=metadata)]


# 全局实例
mineru_service = MinerUService()
