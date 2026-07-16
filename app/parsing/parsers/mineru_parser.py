"""
MinerU PDF parser (business layer wrapper)

Wraps the underlying implementation in deepdoc/parser/mineru_parser.py,
providing LangChain Document format output.

Supports:
- Table recognition and extraction
- Image recognition and description
- Formula recognition
- Complex layout analysis
"""
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.deepdoc.parser.mineru_parser import MinerUParser as DeepDocMinerUParser
from app.services.mineru_service import mineru_service

from .base_parser import BaseAdvancedParser


class MinerUParser(BaseAdvancedParser):
    """
    MinerU advanced PDF parser (business layer wrapper)

    Calls the underlying implementation in deepdoc/parser/mineru_parser.py,
    converting sections/tables to LangChain Document format.
    """

    def __init__(self):
        api = settings.MINERU_LOCAL_SERVER_URL.strip()
        self._api = api.rstrip("/") if api else ""

        server_url = settings.MINERU_VL_SERVER.strip()
        self._server_url = server_url.rstrip("/") if server_url else ""
        super().__init__()

    def _get_parser_name(self) -> str:
        return "mineru"

    def _create_parser(self) -> Any:

        return DeepDocMinerUParser(
            mineru_api=self._api,
            mineru_server_url=self._server_url
        )

    def _check_parser_installation(self, parser: Any) -> tuple[bool, str]:
        return parser.check_installation()

    def _call_parse_method(
        self,
        parser: Any,
        file_path: Path,
        binary: bytes | None,
        callback: Callable[[float, str], None],
        **kwargs
    ) -> tuple[list, list]:
        return parser.parse_pdf(
            filepath=str(file_path),
            binary=binary,
            callback=callback,
            backend=settings.MINERU_BACKEND,
            server_url=self._server_url,
            delete_output=True,
            **kwargs
        )

    def parse(self, file_path: Path, **kwargs) -> list:
        """
        Prefer the project's MinerU integrations when configured:
        - Local ZIP mode: MINERU_LOCAL_SERVER_URL (+ optional MINERU_VL_SERVER). When dataset/document ids
          are provided, we parse via `MinerUService.parse_file_local()` so images can be uploaded to MinIO.
        - Online API mode: MINERU_API_TOKEN. When no local API server is configured, we parse via
          `MinerUService.parse_file()`.

        Fallback to DeepDoc's MinerU adapter when a local API server is configured but we cannot use the
        ZIP->MinIO path (e.g. preview endpoints without ids).
        """
        file_path = Path(file_path)
        self._validate_file(file_path)

        dataset_id = kwargs.get("dataset_id")
        document_id = kwargs.get("document_id")
        tenant_id = kwargs.get("tenant_id")

        # 1) Prefer local ZIP mode whenever a local MinerU service is configured.
        # When dataset/document ids are unavailable (preview flows), the service
        # still returns markdown and preview-local images without requiring MinIO.
        if getattr(settings, "MINERU_LOCAL_SERVER_URL", ""):
            try:
                return mineru_service.parse_file_local(
                    file_path=file_path,
                    dataset_id=str(dataset_id) if dataset_id else None,
                    document_id=str(document_id) if document_id else None,
                    tenant_id=str(tenant_id) if tenant_id else None,
                )
            except Exception as exc:
                # Best-effort: fall back to DeepDoc adapter below.
                self._logger.debug("Local MinerU preview parse failed; falling back to DeepDoc adapter: %s", exc)

        # 2) If we don't have a local API server configured, fall back to online MinerU API when possible.
        if not self._api and getattr(settings, "MINERU_API_TOKEN", ""):
            data_id = str(document_id) if document_id else file_path.stem
            return mineru_service.parse_file(
                file_path=file_path,
                data_id=data_id,
                tenant_id=str(tenant_id) if tenant_id else None,
                dataset_id=str(dataset_id) if dataset_id else None,
                document_id=str(document_id) if document_id else None,
            )

        # 3) Default: DeepDoc adapter (local MinerU API server).
        return super().parse(file_path, **kwargs)
