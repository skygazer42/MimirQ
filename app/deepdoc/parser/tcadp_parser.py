#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""
Tencent Cloud ADP (Advanced Document Processing) Parser.
"""

import base64
import json
import logging
import os
import shutil
import tempfile
import time
import traceback
import types
import zipfile
from collections.abc import Callable
from datetime import UTC, datetime
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import Any

import httpx
from tencentcloud.common import credential
from tencentcloud.common.profile.client_profile import ClientProfile
from tencentcloud.common.profile.http_profile import HttpProfile
from tencentcloud.lkeap.v20240522 import lkeap_client, models  # type: ignore[import]

from app.core.config import settings
from app.deepdoc.parser.pdf_parser import IntegratedPipelinePdfParser


class TencentCloudAPIClient:
    """Tencent Cloud API client using official SDK"""

    def __init__(self, secret_id, secret_key, region):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.region = region
        self.outlines = []

        # Create credentials
        self.cred = credential.Credential(secret_id, secret_key)

        # Instantiate an http option
        self.http_profile = HttpProfile()
        self.http_profile.endpoint = "lkeap.tencentcloudapi.com"

        # Instantiate a client option
        self.client_profile = ClientProfile()
        setattr(self.client_profile, "httpProfile", self.http_profile)

        # Instantiate the client object
        self.client = lkeap_client.LkeapClient(self.cred, region, self.client_profile)

    def reconstruct_document_sse(
        self,
        file_type,
        file_url=None,
        file_base64=None,
        file_start_page=1,
        file_end_page=1000,
        config=None,
    ):
        """Call document parsing API using official SDK"""
        try:
            req = self._build_reconstruct_request(
                file_type=file_type,
                file_url=file_url,
                file_base64=file_base64,
                file_start_page=file_start_page,
                file_end_page=file_end_page,
                config=config,
            )
            resp = self.client.ReconstructDocumentSSE(req)

            if isinstance(resp, types.GeneratorType):
                return self._consume_stream_response(resp)

            return self._consume_non_stream_response(resp)

        except Exception as err:
            logging.exception(f"[TCADP] API error: {err}")
            logging.exception(f"[TCADP] Error stack trace: {traceback.format_exc()}")
            return None

    def _build_reconstruct_request(
        self,
        *,
        file_type,
        file_url,
        file_base64,
        file_start_page,
        file_end_page,
        config,
    ):
        req = models.ReconstructDocumentSSERequest()
        req.from_json_string(
            json.dumps(
                self._build_reconstruct_params(
                    file_type=file_type,
                    file_url=file_url,
                    file_base64=file_base64,
                    file_start_page=file_start_page,
                    file_end_page=file_end_page,
                    config=config,
                )
            )
        )
        return req

    @staticmethod
    def _build_reconstruct_params(
        *,
        file_type,
        file_url,
        file_base64,
        file_start_page,
        file_end_page,
        config,
    ) -> dict[str, Any]:
        params = {
            "FileType": file_type,
            "FileStartPageNumber": file_start_page,
            "FileEndPageNumber": file_end_page,
        }

        if file_url:
            params["FileUrl"] = file_url
            logging.info("[TCADP] Using file URL: %s", file_url)
        elif file_base64:
            params["FileBase64"] = file_base64
            logging.info("[TCADP] Using Base64 data, length: %s characters", len(file_base64))
        else:
            raise ValueError("Must provide either FileUrl or FileBase64 parameter")

        if config:
            params["Config"] = config

        return params

    def _consume_stream_response(self, response) -> dict[str, Any]:
        logging.info("[TCADP] Detected streaming response")
        parser_result: dict[str, Any] = {}

        for event in response:
            logging.info("[TCADP] Received event: %s", event)
            event_data = event.get("data")
            if not event_data:
                logging.info("[TCADP] Event without data: %s", event)
                continue

            data_dict = self._parse_event_data(event_data)
            if data_dict is None:
                continue

            if data_dict.get("Progress") == "100":
                self._log_completed_result(data_dict)
                return data_dict

            logging.info("[TCADP] Progress: %s%%", data_dict.get("Progress", "0"))

        return parser_result

    @staticmethod
    def _parse_event_data(event_data: str) -> dict[str, Any] | None:
        try:
            data_dict = json.loads(event_data)
            logging.info("[TCADP] Parsed data: %s", data_dict)
            return data_dict
        except json.JSONDecodeError as err:
            logging.exception(f"[TCADP] Failed to parse JSON data: {err}")
            logging.error("[TCADP] Raw data: %s", event_data)
            return None

    @staticmethod
    def _log_completed_result(data_dict: dict[str, Any]) -> None:
        logging.info("[TCADP] Document parsing completed!")
        logging.info("[TCADP] Task ID: %s", data_dict.get("TaskId"))
        logging.info("[TCADP] Success pages: %s", data_dict.get("SuccessPageNum"))
        logging.info("[TCADP] Failed pages: %s", data_dict.get("FailPageNum"))

        failed_pages = data_dict.get("FailedPages", [])
        if failed_pages:
            logging.warning("[TCADP] Failed parsing pages:")
            for page in failed_pages:
                logging.warning(
                    "[TCADP]   Page number: %s, Error: %s",
                    page.get("PageNumber"),
                    page.get("ErrorMsg"),
                )

        download_url = data_dict.get("DocumentRecognizeResultUrl")
        if download_url:
            logging.info("[TCADP] Got download link: %s", download_url)
            return

        logging.warning("[TCADP] No download link obtained")

    @staticmethod
    def _consume_non_stream_response(resp) -> dict[str, Any] | None:
        logging.info("[TCADP] Detected non-streaming response")
        response_data = getattr(resp, "data", None)
        if not response_data:
            logging.error("[TCADP] No data in response")
            return None

        try:
            parser_result = json.loads(response_data)
            logging.info("[TCADP] JSON parsing successful: %s", parser_result)
            return parser_result
        except json.JSONDecodeError as err:
            logging.exception(f"[TCADP] JSON parsing failed: {err}")
            return None

    def download_result_file(self, download_url, output_dir):
        """Download parsing result file"""
        if not download_url:
            logging.warning("[TCADP] No downloadable result file")
            return None

        try:
            with httpx.Client(follow_redirects=True, timeout=60.0) as client:
                response = client.get(download_url)
            response.raise_for_status()

            os.makedirs(output_dir, exist_ok=True)

            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
            filename = f"tcadp_result_{timestamp}.zip"
            file_path = os.path.join(output_dir, filename)

            with open(file_path, "wb") as f:
                f.write(response.content)

            logging.info(f"[TCADP] Document parsing result downloaded to: {os.path.basename(file_path)}")
            return file_path

        except httpx.HTTPError as e:
            logging.exception(f"[TCADP] Failed to download file: {e}")
            return None


class TCADPParser(IntegratedPipelinePdfParser):
    def __init__(
        self,
        secret_id: str = None,
        secret_key: str = None,
        region: str = "ap-guangzhou",
        table_result_type: str = None,
        markdown_image_response_type: str = None,
    ):
        super().__init__()

        self.logger = logging.getLogger(self.__class__.__name__)

        self.logger.info(
            "[TCADP] Initializing with parameters - table_result_type: %s, markdown_image_response_type: %s",
            table_result_type,
            markdown_image_response_type,
        )

        # Read from MimirQ settings
        self.secret_id = secret_id or settings.TCADP_SECRET_ID
        self.secret_key = secret_key or settings.TCADP_SECRET_KEY
        self.region = region or settings.TCADP_REGION
        self.table_result_type = table_result_type or settings.TCADP_TABLE_RESULT_TYPE
        self.markdown_image_response_type = markdown_image_response_type or settings.TCADP_MARKDOWN_IMAGE_RESPONSE_TYPE

        self.logger.info(
            "[TCADP] Final values - table_result_type: %s, markdown_image_response_type: %s",
            self.table_result_type,
            self.markdown_image_response_type,
        )

    def check_installation(self) -> bool:
        """Check if Tencent Cloud API configuration is correct"""
        try:
            if not self.secret_id or not self.secret_key:
                self.logger.error("[TCADP] Tencent Cloud API configuration incomplete")
                return False

            TencentCloudAPIClient(self.secret_id, self.secret_key, self.region)
            self.logger.info("[TCADP] Tencent Cloud API configuration check passed")
            return True
        except Exception as e:
            self.logger.error(f"[TCADP] Tencent Cloud API configuration check failed: {e}")
            return False

    def _file_to_base64(self, file_path: str, binary: bytes = None) -> str:
        """Convert file to Base64 format"""
        if binary:
            return base64.b64encode(binary).decode("utf-8")
        else:
            with open(file_path, "rb") as f:
                file_data = f.read()
                return base64.b64encode(file_data).decode("utf-8")

    def _extract_content_from_zip(self, zip_path: str) -> list[dict[str, Any]]:
        """Extract parsing results from downloaded ZIP file"""
        results = []

        try:
            with zipfile.ZipFile(zip_path, "r") as zip_file:
                json_files = [f for f in zip_file.namelist() if f.endswith(".json")]

                for json_file in json_files:
                    with zip_file.open(json_file) as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            results.extend(data)
                        else:
                            results.append(data)

                md_files = [f for f in zip_file.namelist() if f.endswith(".md")]
                for md_file in md_files:
                    with zip_file.open(md_file) as f:
                        content = f.read().decode("utf-8")
                        results.append({"type": "text", "content": content, "file": md_file})

        except Exception as e:
            self.logger.error(f"[TCADP] Failed to extract ZIP file content: {e}")

        return results

    def _parse_content_to_sections(self, content_data: list[dict[str, Any]]) -> list[tuple[str, str]]:
        """Convert parsing results to sections format"""
        sections = []

        for item in content_data:
            content_type = item.get("type", "text")
            content = item.get("content", "")

            if not content:
                continue

            if content_type == "text" or content_type == "paragraph":
                section_text = content
            elif content_type == "table":
                table_data = item.get("table_data", {})
                if isinstance(table_data, dict):
                    rows = table_data.get("rows", [])
                    section_text = "\n".join([" | ".join(row) for row in rows])
                else:
                    section_text = str(table_data)
            elif content_type == "image":
                caption = item.get("caption", "")
                section_text = f"[Image] {caption}" if caption else "[Image]"
            elif content_type == "equation":
                section_text = f"$${content}$$"
            else:
                section_text = content

            if section_text.strip():
                position_tag = "@@1\t0.0\t1000.0\t0.0\t100.0##"
                sections.append((section_text, position_tag))

        return sections

    def _parse_content_to_tables(self, content_data: list[dict[str, Any]]) -> list:
        """Convert parsing results to tables format"""
        tables = []

        for item in content_data:
            if item.get("type") == "table":
                table_data = item.get("table_data", {})
                if isinstance(table_data, dict):
                    rows = table_data.get("rows", [])
                    if rows:
                        table_html = "<table>\n"
                        for i, row in enumerate(rows):
                            table_html += "  <tr>\n"
                            for cell in row:
                                tag = "th" if i == 0 else "td"
                                table_html += f"    <{tag}>{cell}</{tag}>\n"
                            table_html += "  </tr>\n"
                        table_html += "</table>"
                        tables.append(table_html)

        return tables

    @staticmethod
    def _notify(callback: Callable | None, progress: float | int, message: str) -> None:
        if callback:
            callback(progress, message)

    def _resolve_pdf_input(
        self,
        filepath: str | PathLike[str],
        binary: BytesIO | bytes,
        callback: Callable | None,
    ) -> tuple[str, Any | None]:
        if binary:
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
            temp_file.write(binary if isinstance(binary, bytes) else binary.read())
            temp_file.close()
            file_path = temp_file.name
            message = f"[TCADP] Received binary PDF -> {os.path.basename(file_path)}"
            self.logger.info(message)
            self._notify(callback, 0.1, message)
            return file_path, temp_file

        file_path = str(filepath)
        if os.path.exists(file_path):
            return file_path, None

        error_msg = f"[TCADP] PDF file does not exist: {file_path}"
        self._notify(callback, -1, error_msg)
        raise FileNotFoundError(error_msg)

    def _build_request_config(self) -> dict[str, str]:
        return {
            "TableResultType": self.table_result_type,
            "MarkdownImageResponseType": self.markdown_image_response_type,
        }

    def _log_request_config(self) -> None:
        self.logger.info(
            "[TCADP] API request config - TableResultType: %s, MarkdownImageResponseType: %s",
            self.table_result_type,
            self.markdown_image_response_type,
        )

    def _request_parse_result(
        self,
        *,
        client: Any,
        file_type: str,
        file_base64: str,
        file_start_page: int | None,
        file_end_page: int | None,
        max_retries: int | None,
        callback: Callable | None,
    ) -> dict[str, Any]:
        result = None
        config = self._build_request_config()

        for attempt in range(max_retries):
            try:
                self._handle_retry(attempt, callback)
                self._log_request_config()
                result = client.reconstruct_document_sse(
                    file_type=file_type,
                    file_base64=file_base64,
                    file_start_page=file_start_page,
                    file_end_page=file_end_page,
                    config=config,
                )
                if result:
                    self.logger.info("[TCADP] Attempt %s successful", attempt + 1)
                    return result
                self.logger.warning("[TCADP] Attempt %s failed, result is None", attempt + 1)
            except Exception as exc:
                self.logger.error("[TCADP] Attempt %s exception: %s", attempt + 1, exc)
                if attempt == max_retries - 1:
                    raise

        error_msg = f"[TCADP] Document parsing failed, retried {max_retries} times"
        self.logger.error(error_msg)
        self._notify(callback, -1, error_msg)
        raise RuntimeError(error_msg)

    def _handle_retry(self, attempt: int, callback: Callable | None) -> None:
        if attempt <= 0:
            return

        message = f"[TCADP] Retry attempt {attempt + 1}"
        self.logger.info(message)
        self._notify(callback, 0.3 + attempt * 0.1, message)
        time.sleep(2**attempt)

    @staticmethod
    def _prepare_output_dir(output_dir: str | None) -> tuple[Path, bool]:
        if output_dir:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            return out_dir, False

        return Path(tempfile.mkdtemp(prefix="adp_pdf_")), True

    def _download_result_zip(
        self,
        *,
        client: Any,
        result: dict[str, Any],
        out_dir: Path,
        callback: Callable | None,
    ) -> str:
        download_url = result.get("DocumentRecognizeResultUrl")
        if not download_url:
            error_msg = "[TCADP] No parsing result download link obtained"
            self._notify(callback, -1, error_msg)
            raise RuntimeError(error_msg)

        self._notify(callback, 0.6, "[TCADP] Parsing result download link obtained")
        zip_path = client.download_result_file(download_url, str(out_dir))
        if not zip_path:
            error_msg = "[TCADP] Failed to download parsing result"
            self._notify(callback, -1, error_msg)
            raise RuntimeError(error_msg)

        self._notify(
            callback,
            0.8,
            f"[TCADP] Parsing result downloaded: {os.path.basename(zip_path)}",
        )
        return zip_path

    def _cleanup_temp_file(self, temp_file: Any | None) -> None:
        if temp_file and os.path.exists(temp_file.name):
            try:
                os.unlink(temp_file.name)
            except Exception as exc:
                self.logger.debug("[TCADP] Failed to remove temporary file %s: %s", temp_file.name, exc)

    def _cleanup_output_dir(
        self,
        *,
        delete_output: bool | None,
        created_tmp_dir: bool,
        out_dir: Path | None,
    ) -> None:
        if delete_output and created_tmp_dir and out_dir and out_dir.exists():
            try:
                shutil.rmtree(out_dir)
            except Exception as exc:
                self.logger.debug("[TCADP] Failed to remove temporary output %s: %s", out_dir, exc)

    def parse_pdf(
        self,
        filepath: str | PathLike[str],
        binary: BytesIO | bytes,
        callback: Callable | None = None,
        *,
        output_dir: str | None = None,
        file_type: str = "PDF",
        file_start_page: int | None = 1,
        file_end_page: int | None = 1000,
        delete_output: bool | None = True,
        max_retries: int | None = 1,
    ) -> tuple:
        """Parse PDF document"""

        temp_file = None
        created_tmp_dir = False
        out_dir = None

        try:
            file_path, temp_file = self._resolve_pdf_input(filepath, binary, callback)
            self._notify(callback, 0.2, "[TCADP] Converting file to Base64 format")
            file_base64 = self._file_to_base64(file_path, binary if isinstance(binary, bytes) else None)
            self._notify(
                callback,
                0.25,
                f"[TCADP] File converted to Base64, size: {len(file_base64)} characters",
            )

            client = TencentCloudAPIClient(self.secret_id, self.secret_key, self.region)
            self._notify(callback, 0.3, "[TCADP] Starting to call Tencent Cloud document parsing API")
            result = self._request_parse_result(
                client=client,
                file_type=file_type,
                file_base64=file_base64,
                file_start_page=file_start_page,
                file_end_page=file_end_page,
                max_retries=max_retries,
                callback=callback,
            )
            out_dir, created_tmp_dir = self._prepare_output_dir(output_dir)
            zip_path = self._download_result_zip(
                client=client,
                result=result,
                out_dir=out_dir,
                callback=callback,
            )

            content_data = self._extract_content_from_zip(zip_path)
            self.logger.info("[TCADP] Extracted %s content blocks", len(content_data))
            self._notify(callback, 0.9, f"[TCADP] Extracted {len(content_data)} content blocks")

            sections = self._parse_content_to_sections(content_data)
            tables = self._parse_content_to_tables(content_data)

            self.logger.info(
                "[TCADP] Parsing completed: %s sections, %s tables",
                len(sections),
                len(tables),
            )
            self._notify(
                callback,
                1.0,
                f"[TCADP] Parsing completed: {len(sections)} sections, {len(tables)} tables",
            )

            return sections, tables

        finally:
            self._cleanup_temp_file(temp_file)
            self._cleanup_output_dir(
                delete_output=delete_output,
                created_tmp_dir=created_tmp_dir,
                out_dir=out_dir,
            )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = TCADPParser()
    logging.info("ADP available: %s", parser.check_installation())
