"""
MinerU document parsing service.
Supports two modes:
1. MinerU online API: https://mineru.net (returns Markdown URL)
2. MinerU local service: returns ZIP (Markdown + images)
Both modes support advanced PDF parsing (tables, images, formulas, etc.)
"""
import asyncio
import time
import tempfile
from pathlib import Path
from typing import List, Dict, Any, Optional
from langchain_core.documents import Document
from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.parsing.utils.zip_processor import zip_image_processor
from app.rag.core.logging import get_logger


logger = get_logger("services.mineru")


class MinerUService:
    """MinerU parsing service."""

    def __init__(self):
        self.api_base = settings.MINERU_API_BASE
        self.api_token = settings.MINERU_API_TOKEN
        self.model_version = settings.MINERU_MODEL_VERSION
        self.local_server_url = (getattr(settings, "MINERU_LOCAL_SERVER_URL", "") or "").strip() or None
        # Local MinerU does not require API token; online API does.
        self.enabled = bool(settings.MINERU_ENABLED) and (bool(self.api_token) or bool(self.local_server_url))

        if not self.enabled:
            logger.warning(
                "MinerU is disabled. Set MINERU_ENABLED=True and configure "
                "MINERU_API_TOKEN (online) or MINERU_LOCAL_SERVER_URL (local) to enable."
            )

    def _get_headers(self) -> Dict[str, str]:
        """Get request headers."""
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "*/*"
        }

    async def _arequest_json(
        self,
        method: str,
        url: str,
        *,
        headers: Optional[Dict[str, str]] = None,
        timeout: Optional[float] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """
        Send an HTTP request and parse JSON (async with retries).

        NOTE: Reuse the global HTTPClientPool to avoid blocking the event loop.
        """
        pool = get_http_client_pool()
        resp = await pool.request_with_retry(method, url, headers=headers, timeout=timeout, **kwargs)
        try:
            return resp.json()
        finally:
            # Ensure response is closed to release connection back to pool.
            try:
                await resp.aclose()
            except Exception:
                pass

    async def aapply_upload_url(self, filename: str, data_id: str) -> Dict[str, Any]:
        """Request a single file upload URL (async)."""
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")

        url = f"{self.api_base}/file-urls/batch"
        data = {"files": [{"name": filename, "data_id": data_id}], "model_version": self.model_version}

        result = await self._arequest_json("POST", url, headers=self._get_headers(), json=data, timeout=30.0)
        if result.get("code") == 0:
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            return {"batch_id": batch_id, "upload_url": upload_url, "data_id": data_id}
        raise Exception(f"Apply upload URL failed: {result.get('msg', 'Unknown error')}")

    def apply_upload_url(self, filename: str, data_id: str) -> Dict[str, Any]:
        """
        Request a single file upload URL.

        Args:
            filename: File name.
            data_id: Custom data ID (identifier).

        Returns:
            {
                "batch_id": "xxx",
                "upload_url": "https://...",
                "data_id": "xxx"
            }
        """
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")
        import requests  # local import to avoid blocking deps in async paths

        url = f"{self.api_base}/file-urls/batch"
        data = {"files": [{"name": filename, "data_id": data_id}], "model_version": self.model_version}

        try:
            response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error when applying upload URL: {str(e)}") from e

        if result.get("code") == 0:
            batch_id = result["data"]["batch_id"]
            upload_url = result["data"]["file_urls"][0]
            return {"batch_id": batch_id, "upload_url": upload_url, "data_id": data_id}
        raise Exception(f"Apply upload URL failed: {result.get('msg', 'Unknown error')}")

    async def aapply_batch_upload_urls(self, files: List[Dict[str, str]]) -> Dict[str, Any]:
        """Request batch upload URLs (async)."""
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")
        if len(files) > 200:
            raise ValueError("Maximum 200 files per batch")

        url = f"{self.api_base}/file-urls/batch"
        data = {"files": files, "model_version": self.model_version}

        result = await self._arequest_json("POST", url, headers=self._get_headers(), json=data, timeout=30.0)
        if result.get("code") == 0:
            return {"batch_id": result["data"]["batch_id"], "file_urls": result["data"]["file_urls"], "files": files}
        raise Exception(f"Apply batch upload URLs failed: {result.get('msg', 'Unknown error')}")

    def apply_batch_upload_urls(
        self,
        files: List[Dict[str, str]]
    ) -> Dict[str, Any]:
        """
        Request batch upload URLs.

        Args:
            files: File list, format: [{"name": "file1.pdf", "data_id": "id1"}, ...]
                   Up to 200 files.

        Returns:
            {
                "batch_id": "xxx",
                "file_urls": ["https://...", "https://..."],
                "files": [{"name": "...", "data_id": "..."}, ...]
            }
        """
        import requests  # local import to avoid blocking deps in async paths

        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")

        if len(files) > 200:
            raise ValueError("Maximum 200 files per batch")

        url = f"{self.api_base}/file-urls/batch"
        data = {"files": files, "model_version": self.model_version}

        try:
            response = requests.post(url, headers=self._get_headers(), json=data, timeout=30)
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error when applying batch upload URLs: {str(e)}") from e

        if result.get("code") == 0:
            return {"batch_id": result["data"]["batch_id"], "file_urls": result["data"]["file_urls"], "files": files}
        raise Exception(f"Apply batch upload URLs failed: {result.get('msg', 'Unknown error')}")

    async def aupload_file(self, file_path: Path, upload_url: str) -> bool:
        """
        Upload file to MinerU.

        Args:
            file_path: Local file path.
            upload_url: Issued upload URL.

        Returns:
            Whether upload succeeded.
        """
        pool = get_http_client_pool()
        try:
            # MinerU upload does not require Content-Type.
            with open(file_path, "rb") as f:
                resp = await pool.put(upload_url, content=f, timeout=300.0)
                ok = int(getattr(resp, "status_code", 0) or 0) == 200
                try:
                    await resp.aclose()
                except Exception:
                    pass
                return ok
        except Exception as exc:  # noqa: BLE001
            logger.error("Upload file failed: %s", str(exc)[:200])
            return False

    def upload_file(self, file_path: Path, upload_url: str) -> bool:
        import requests  # local import to avoid blocking deps in async paths

        try:
            with open(file_path, "rb") as f:
                response = requests.put(upload_url, data=f, timeout=300)
                response.raise_for_status()
                return response.status_code == 200
        except Exception as e:  # noqa: BLE001
            logger.error("Upload file failed: %s", str(e)[:200])
            return False

    async def aget_task_status(self, batch_id: str) -> Dict[str, Any]:
        """Query parsing task status (async)."""
        if not self.enabled:
            raise Exception("MinerU is not enabled.")

        url = f"{self.api_base}/extract/task/{batch_id}"
        result = await self._arequest_json("GET", url, headers=self._get_headers(), timeout=30.0)
        if result.get("code") == 0:
            return result["data"]
        raise Exception(f"Get task status failed: {result.get('msg', 'Unknown error')}")

    def get_task_status(self, batch_id: str) -> Dict[str, Any]:
        """
        Query parsing task status.

        Args:
            batch_id: Batch ID.

        Returns:
            Task status info.
        """
        import requests  # local import to avoid blocking deps in async paths

        if not self.enabled:
            raise Exception("MinerU is not enabled.")

        url = f"{self.api_base}/extract/task/{batch_id}"

        try:
            response = requests.get(url, headers=self._get_headers(), timeout=30)
            response.raise_for_status()
            result = response.json()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Network error when getting task status: {str(e)}") from e

        if result.get("code") == 0:
            return result["data"]
        raise Exception(f"Get task status failed: {result.get('msg', 'Unknown error')}")

    async def await_for_completion(
        self,
        batch_id: str,
        timeout: int = 600,
        poll_interval: int = 5,
        max_interval: int = 30,
        backoff_factor: float = 1.5,
        jitter: float = 0.2,
    ) -> Dict[str, Any]:
        """
        Wait for parsing task completion.

        Args:
            batch_id: Batch ID.
            timeout: Timeout (seconds).
            poll_interval: Poll interval (seconds).

        Returns:
            Final task status.
        """
        start_time = time.monotonic()
        current_interval = max(1, int(poll_interval))

        while True:
            if time.monotonic() - start_time > timeout:
                raise TimeoutError(f"Task {batch_id} timeout after {timeout} seconds")

            status = await self.aget_task_status(batch_id)
            task_status = status.get("status")

            logger.info("Task %s status: %s", batch_id, task_status)

            if task_status == "completed":
                return status
            elif task_status == "failed":
                raise Exception(f"Task {batch_id} failed: {status.get('error', 'Unknown error')}")

            # Exponential backoff with jitter (best-effort)
            sleep_for = float(current_interval)
            if jitter and jitter > 0:
                # add +/- jitter
                delta = sleep_for * float(jitter)
                sleep_for = max(0.5, sleep_for - delta)  # lower bound
            await asyncio.sleep(sleep_for)
            current_interval = min(int(max_interval), int(current_interval * float(backoff_factor)))

    def wait_for_completion(self, batch_id: str, timeout: int = 600, poll_interval: int = 5) -> Dict[str, Any]:
        start_time = time.time()

        while True:
            if time.time() - start_time > timeout:
                raise TimeoutError(f"Task {batch_id} timeout after {timeout} seconds")

            status = self.get_task_status(batch_id)
            task_status = status.get("status")

            logger.info("Task %s status: %s", batch_id, task_status)

            if task_status == "completed":
                return status
            if task_status == "failed":
                raise Exception(f"Task {batch_id} failed: {status.get('error', 'Unknown error')}")

            time.sleep(poll_interval)

    async def adownload_result(self, result_url: str) -> str:
        """Download parse result (Markdown, async)."""
        pool = get_http_client_pool()
        resp = await pool.get(result_url, timeout=60.0)
        try:
            return resp.text
        finally:
            try:
                await resp.aclose()
            except Exception:
                pass

    def download_result(self, result_url: str) -> str:
        """
        Download parse result (Markdown).

        Args:
            result_url: Result download URL.

        Returns:
            Markdown content.
        """
        import requests  # local import to avoid blocking deps in async paths

        try:
            response = requests.get(result_url, timeout=60)
            response.raise_for_status()
            return response.text
        except requests.exceptions.RequestException as e:
            raise Exception(f"Download result failed: {str(e)}") from e

    async def aparse_file(self, file_path: Path, data_id: Optional[str] = None) -> List[Document]:
        """
        End-to-end parsing flow (upload → wait → download result), async version.
        """
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")

        file_path = Path(file_path)
        data_id = data_id or str(file_path.stem)
        logger.info("Applying upload URL for %s...", file_path.name)
        upload_info = await self.aapply_upload_url(file_path.name, data_id)

        batch_id = upload_info["batch_id"]
        upload_url = upload_info["upload_url"]

        logger.info("Uploading %s...", file_path.name)
        success = await self.aupload_file(file_path, upload_url)
        if not success:
            raise Exception(f"Failed to upload {file_path.name}")

        logger.info("Upload complete. Batch ID: %s", batch_id)
        logger.info("Waiting for parsing completion...")
        result = await self.await_for_completion(batch_id, timeout=600, poll_interval=5)

        result_url = result.get("result_url")
        if not result_url:
            raise Exception("No result URL in response")

        logger.info("Downloading result...")
        markdown_content = await self.adownload_result(result_url)

        metadata = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser": "mineru",
            "batch_id": batch_id,
            "data_id": data_id,
            "model_version": self.model_version,
        }
        logger.info("Parse complete. Content length: %s chars", len(markdown_content))
        return [Document(page_content=markdown_content, metadata=metadata)]

    async def aparse_file_local(
        self,
        *,
        file_path: Path,
        dataset_id: str,
        document_id: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Parse with local MinerU (returns ZIP with Markdown + images), async version.

        - Upload multipart file to local MinerU
        - Download ZIP bytes
        - Write ZIP to temp file, then in to_thread:
          ZIP -> Markdown + image extraction + MinIO upload
        """
        if not self.local_server_url:
            raise Exception(
                "MinerU 本地服务未配置。请设置 MINERU_LOCAL_SERVER_URL，例如：http://localhost:30001"
            )

        parse_endpoint = f"{self.local_server_url}/file_parse"
        params = params or {}

        data: Dict[str, Any] = {
            "lang_list": params.get("lang_list", ["ch"]),
            "backend": params.get("backend", "vlm-http-client"),
            "parse_method": params.get("parse_method", "auto"),
            "return_md": True,
            "response_format_zip": True,
            "return_images": True,
        }

        if data["backend"] == "vlm-http-client":
            mineru_vl_server = getattr(settings, "MINERU_VL_SERVER", None)
            if mineru_vl_server:
                data["server_url"] = mineru_vl_server

        logger.info("MinerU local parsing started (async): %s", file_path.name)

        pool = get_http_client_pool()
        tmp_zip_path: Optional[Path] = None
        try:
            # multipart upload (keep file open until request finishes)
            with open(file_path, "rb") as f:
                files = {"files": (file_path.name, f, "application/octet-stream")}
                resp = await pool.request_with_retry(
                    "POST",
                    parse_endpoint,
                    files=files,
                    data=data,
                    timeout=300.0,
                )

            try:
                content_type = str(resp.headers.get("Content-Type", "") or "")
                body = resp.content
            finally:
                try:
                    await resp.aclose()
                except Exception:
                    pass

            if ("zip" not in content_type.lower()) and ("application/octet-stream" not in content_type.lower()):
                raise Exception(f"MinerU returned unexpected content type: {content_type}")

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip.write(body)
                tmp_zip_path = Path(tmp_zip.name)

            # Process ZIP in a thread (includes MinIO uploads)
            result = await asyncio.to_thread(
                zip_image_processor.process_zip_with_images,
                zip_path=tmp_zip_path,
                dataset_id=dataset_id,
                document_id=document_id,
            )

            markdown_content = result["markdown"]
            images = result["images"]

            logger.info(
                "MinerU local parse done (async): %s chars, %s images",
                len(markdown_content),
                len(images),
            )

            metadata = {
                "source": file_path.name,
                "file_type": file_path.suffix.lstrip("."),
                "parser": "mineru_local",
                "image_count": len(images),
                "images": images,
            }
            return [Document(page_content=markdown_content, metadata=metadata)]
        except Exception as e:  # noqa: BLE001
            logger.error("MinerU local parsing failed (async): %s", str(e)[:200])
            raise Exception(f"MinerU local parsing failed: {str(e)}") from e
        finally:
            if tmp_zip_path and tmp_zip_path.exists():
                try:
                    tmp_zip_path.unlink()
                except Exception:
                    pass

    def parse_file(
        self,
        file_path: Path,
        data_id: Optional[str] = None
    ) -> List[Document]:
        """
        End-to-end parsing flow (upload → wait → download result).

        Args:
            file_path: Local file path.
            data_id: Custom data ID (optional).

        Returns:
            Parsed LangChain Document list.
        """
        if not self.enabled:
            raise Exception("MinerU is not enabled. Please configure MINERU_API_TOKEN.")

        # 1. Request upload URL.
        data_id = data_id or str(file_path.stem)
        logger.info("Applying upload URL for %s...", file_path.name)
        upload_info = self.apply_upload_url(file_path.name, data_id)

        batch_id = upload_info["batch_id"]
        upload_url = upload_info["upload_url"]

        # 2. Upload file.
        logger.info("Uploading %s...", file_path.name)
        success = self.upload_file(file_path, upload_url)
        if not success:
            raise Exception(f"Failed to upload {file_path.name}")

        logger.info("Upload complete. Batch ID: %s", batch_id)

        # 3. Wait for parsing completion.
        logger.info("Waiting for parsing completion...")
        result = self.wait_for_completion(batch_id, timeout=600, poll_interval=5)

        # 4. Download parse result.
        result_url = result.get("result_url")
        if not result_url:
            raise Exception("No result URL in response")

        logger.info("Downloading result...")
        markdown_content = self.download_result(result_url)

        # 5. Convert to LangChain Document.
        metadata = {
            "source": file_path.name,
            "file_type": "pdf",
            "parser": "mineru",
            "batch_id": batch_id,
            "data_id": data_id,
            "model_version": self.model_version,
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
        Parse with local MinerU (returns ZIP with Markdown + images).

        Args:
            file_path: Local file path.
            dataset_id: Dataset ID.
            document_id: Document ID.
            params: Parse params.

        Returns:
            Parsed LangChain Documents (images uploaded to MinIO).
        """
        if not self.local_server_url:
            raise Exception(
                "MinerU 本地服务未配置。请设置 MINERU_LOCAL_SERVER_URL，"
                "例如：http://localhost:30001"
            )
        
        parse_endpoint = f"{self.local_server_url}/file_parse"
        params = params or {}
        
        # Build request parameters.
        data = {
            "lang_list": params.get("lang_list", ["ch"]),
            "backend": params.get("backend", "vlm-http-client"),
            "parse_method": params.get("parse_method", "auto"),
            "return_md": True,
            "response_format_zip": True,
            "return_images": True,
        }
        
        # vlm-http-client backend requires server_url.
        if data["backend"] == "vlm-http-client":
            mineru_vl_server = getattr(settings, 'MINERU_VL_SERVER', None)
            if mineru_vl_server:
                data["server_url"] = mineru_vl_server
        
        logger.info("MinerU local parsing started: %s", file_path.name)
        
        try:
            # Send file.
            with open(file_path, "rb") as f:
                files = {"files": (file_path.name, f, "application/octet-stream")}
                # NOTE: Local ZIP parsing path is currently sync-only; for async,
                # wrap with asyncio.to_thread or add an async version to avoid blocking.
                import requests  # local import to avoid global dependency in async paths

                response = requests.post(parse_endpoint, files=files, data=data, timeout=300)
            
            response.raise_for_status()
            
            # Check response is ZIP.
            content_type = response.headers.get('Content-Type', '')
            if 'zip' not in content_type.lower() and 'application/octet-stream' not in content_type.lower():
                # Try parsing JSON error.
                try:
                    error_data = response.json()
                    raise Exception(f"MinerU parsing failed: {error_data}")
                except (ValueError, TypeError) as json_err:
                    raise Exception(f"MinerU returned unexpected content type: {content_type}") from json_err
            
            # Save ZIP to temp file.
            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp_zip:
                tmp_zip.write(response.content)
                tmp_zip_path = Path(tmp_zip.name)
            
            try:
                # Process ZIP: extract images and upload to MinIO.
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
                
                # Build metadata.
                metadata = {
                    "source": file_path.name,
                    "file_type": file_path.suffix.lstrip('.'),
                    "parser": "mineru_local",
                    "image_count": len(images),
                    "images": images,  # [{img_id, original_path, url}]
                }
                
                return [Document(page_content=markdown_content, metadata=metadata)]
                
            finally:
                # Clean up temp ZIP file.
                if tmp_zip_path.exists():
                    tmp_zip_path.unlink()
        
        except Exception as e:
            logger.error("MinerU local parsing failed: %s", e)
            raise Exception(f"MinerU local parsing failed: {str(e)}")


# Global instance
mineru_service = MinerUService()
