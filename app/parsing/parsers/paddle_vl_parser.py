"""
PaddleOCR-VL parser (external service).

PaddleOCR-VL is an optional heavyweight OCR/layout pipeline. To avoid bloating
the main backend image, we integrate it as an external HTTP service.

Config via env/.env:
- PADDLE_VL_ENABLED=true
- PADDLE_VL_API_URL=http://localhost:9030/convert  (your service endpoint)
"""


import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

import requests
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.utils.artifact_normalizer import normalize_extracted_artifacts, rewrite_html_image_refs
from app.parsing.utils.zip_processor import ZipImageProcessor
from app.rag.core.logging import get_logger

from .service_url_fallback import build_docker_service_url_candidates

logger = get_logger("parsing.paddle_vl")


def _sanitize_run_id(value: str) -> str:
    text = (value or "").strip()
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)[:120] or "paddlevl"
    return text


class PaddleVLParser:
    """
    Call a PaddleOCR-VL-compatible HTTP API and return Markdown output.

    The service is expected to accept multipart/form-data with field name "file"
    and return either:
    - ZIP (recommended): a folder structure with page_* directories and Markdown,
      which will be normalized to a stable layout under `images/` + `result.md`.
    - JSON: with "markdown"/"text"/"content" fields.
    - text/*: markdown directly.
    """

    STANDARD_IMAGE_DIR = "images"
    STANDARD_MARKDOWN_NAME = "result.md"
    STANDARD_JSON_NAME = "result.json"

    def __init__(self) -> None:
        self._enabled = bool(getattr(settings, "PADDLE_VL_ENABLED", False))
        self._api_url = (getattr(settings, "PADDLE_VL_API_URL", "") or "").strip()
        self._timeout_sec = float(getattr(settings, "PADDLE_VL_TIMEOUT_SEC", 600) or 600)

        if not self._enabled:
            raise RuntimeError("PaddleOCR-VL is disabled (PADDLE_VL_ENABLED=false).")
        if not self._api_url:
            raise RuntimeError("PaddleOCR-VL requires PADDLE_VL_API_URL.")

        self._session = requests.Session()

    def _build_artifact_root(self, file_path: Path, document_id: str | None) -> Path:
        run_id = _sanitize_run_id(document_id or file_path.stem or "paddlevl")
        return (file_path.parent / ".paddlevl" / run_id).absolute()

    def _candidate_api_urls(self) -> list[str]:
        return build_docker_service_url_candidates(
            self._api_url,
            service_hostnames={"mimirq-paddlevl"},
        )

    def _post_multipart(self, *, file_path: Path) -> requests.Response:
        file_bytes = file_path.read_bytes()
        files = {"file": (file_path.name, file_bytes, "application/pdf")}
        data = {"output_format": "markdown"}
        candidate_urls = self._candidate_api_urls()
        last_error: Exception | None = None
        for index, url in enumerate(candidate_urls):
            try:
                return self._session.post(url, files=files, data=data, timeout=self._timeout_sec)
            except requests.RequestException as exc:
                last_error = exc
                if index == len(candidate_urls) - 1:
                    raise
                logger.warning(
                    "[paddle_vl] request to %s failed (%s); retrying fallback %s",
                    url,
                    exc.__class__.__name__,
                    candidate_urls[index + 1],
                )
        if last_error is not None:
            raise last_error
        raise RuntimeError("PaddleOCR-VL parser requires at least one candidate API URL.")

    @staticmethod
    def _looks_like_zip(resp: requests.Response) -> bool:
        ctype = str(resp.headers.get("content-type") or "").lower()
        if "application/zip" in ctype or "application/x-zip" in ctype:
            return True
        body = getattr(resp, "content", b"") or b""
        return len(body) >= 4 and body[:2] == b"PK"

    @staticmethod
    def _extract_markdown_from_json(data: Any) -> str:
        if isinstance(data, dict):
            for key in ("markdown", "md", "content", "text", "result"):
                val = data.get(key)
                if isinstance(val, str) and val.strip():
                    return val
        return ""

    @staticmethod
    def _pick_output_root(extract_root: Path) -> Path:
        """
        Some services zip a single top-level folder; normalize to the folder that
        contains page_* dirs / markdown.
        """
        root = extract_root
        try:
            has_pages = bool(list(root.glob("page_*")))
        except Exception:
            has_pages = False

        if has_pages:
            return root

        try:
            children = [p for p in root.iterdir() if p.is_dir()]
        except Exception:
            children = []

        if len(children) == 1:
            return children[0]
        return root

    @staticmethod
    def _page_dirs(output_dir: Path) -> list[Path]:
        return sorted([p for p in output_dir.glob("page_*") if p.is_dir()])

    @staticmethod
    def _page_number(page_dir: Path) -> int | None:
        try:
            return int(page_dir.name.split("_", 1)[1])
        except Exception:
            logger.warning("[paddle_vl] invalid page directory: %s", page_dir.name)
            return None

    def _move_page_images(self, *, page_dir: Path, standard_image_dir: Path, image_counter: int) -> tuple[int, dict[str, str]]:
        imgs_dir = page_dir / "imgs"
        if not imgs_dir.exists():
            return image_counter, {}

        page_mapping: dict[str, str] = {}
        for img_file in imgs_dir.iterdir():
            if not img_file.is_file():
                continue
            new_name = f"image_{image_counter:03d}{img_file.suffix}"
            new_path = standard_image_dir / new_name
            try:
                shutil.move(str(img_file), str(new_path))
            except Exception as exc:
                logger.warning("[paddle_vl] failed to move image %s: %s", img_file.name, str(exc)[:200])
                continue
            page_mapping[img_file.name] = new_name
            image_counter += 1

        try:
            imgs_dir.rmdir()
        except OSError:
            pass
        return image_counter, page_mapping

    def _collect_image_mapping(self, *, output_dir: Path, standard_image_dir: Path) -> tuple[dict[int, dict[str, str]], int, list[Path]]:
        image_mapping: dict[int, dict[str, str]] = {}
        image_counter = 1
        page_dirs = self._page_dirs(output_dir)
        for page_dir in page_dirs:
            page_num = self._page_number(page_dir)
            if page_num is None:
                continue
            image_counter, page_mapping = self._move_page_images(
                page_dir=page_dir,
                standard_image_dir=standard_image_dir,
                image_counter=image_counter,
            )
            image_mapping[page_num - 1] = page_mapping
        return image_mapping, image_counter, page_dirs

    def _inject_page_image_paths(self, *, page_data: dict[str, Any], page_img_mapping: dict[str, str]) -> None:
        parsing_list = page_data.get("parsing_res_list")
        if not (isinstance(parsing_list, list) and page_img_mapping):
            return
        for block in parsing_list:
            if not isinstance(block, dict):
                continue
            if str(block.get("block_label") or "").strip().lower() != "image":
                continue
            bbox = block.get("block_bbox", [])
            if not (isinstance(bbox, list) and len(bbox) == 4):
                continue
            candidates = [
                f"img_in_image_box_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}.jpg",
                f"img_in_image_box_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}.png",
                f"img_in_image_box_{bbox[0]}_{bbox[1]}_{bbox[2]}_{bbox[3]}.jpeg",
            ]
            for name in candidates:
                new_img_name = page_img_mapping.get(name)
                if new_img_name:
                    block["img_path"] = f"{self.STANDARD_IMAGE_DIR}/{new_img_name}"
                    break

    def _merge_page_jsons(self, *, page_dirs: list[Path], image_mapping: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
        all_pages_data: list[dict[str, Any]] = []
        for page_dir in page_dirs:
            json_files = list(page_dir.glob("*_res.json"))
            if not json_files:
                continue
            json_file = json_files[0]
            try:
                page_data = json.loads(json_file.read_text(encoding="utf-8", errors="ignore") or "{}")
                if not isinstance(page_data, dict):
                    continue
                page_idx = int(page_data.get("page_index", 0) or 0)
                self._inject_page_image_paths(
                    page_data=page_data,
                    page_img_mapping=image_mapping.get(page_idx, {}),
                )
                all_pages_data.append(page_data)
            except Exception as exc:
                logger.warning("[paddle_vl] failed to process %s: %s", str(json_file.name), str(exc)[:200])
        return all_pages_data

    @staticmethod
    def _write_combined_json(*, output_dir: Path, pages: list[dict[str, Any]]) -> Path | None:
        if not pages:
            return None
        standard_json = output_dir / PaddleVLParser.STANDARD_JSON_NAME
        combined = {
            "pages": pages,
            "total_pages": len(pages),
            "format": "paddleocr-vl",
        }
        try:
            standard_json.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            return None
        return standard_json

    @staticmethod
    def _full_image_mapping(image_mapping: dict[int, dict[str, str]]) -> dict[str, str]:
        merged: dict[str, str] = {}
        for page_mapping in image_mapping.values():
            merged.update(page_mapping)
        return merged

    def _normalize_markdown_file(self, *, output_dir: Path, image_mapping: dict[int, dict[str, str]]) -> Path | None:
        md_files = list(output_dir.rglob("*.md"))
        if not md_files:
            return None

        main_md = ZipImageProcessor._choose_markdown_file(md_files)
        standard_md = output_dir / self.STANDARD_MARKDOWN_NAME
        try:
            if main_md != standard_md:
                if main_md.parent != output_dir:
                    shutil.copy2(main_md, standard_md)
                else:
                    main_md.rename(standard_md)
                main_md = standard_md
        except Exception:
            standard_md = main_md

        try:
            content = main_md.read_text(encoding="utf-8", errors="ignore")
            full_image_mapping = self._full_image_mapping(image_mapping)
            new_content = re.sub(
                r"!\[([^\]]*)\]\(([^)]+)\)",
                lambda match: self._replace_markdown_image(match, full_image_mapping),
                content,
            )
            new_content = rewrite_html_image_refs(
                new_content,
                lambda img_path: self._resolve_html_image_src(img_path, full_image_mapping),
            )
            if new_content != content:
                main_md.write_text(new_content, encoding="utf-8")
        except Exception as exc:
            logger.warning("[paddle_vl] failed to update markdown image refs: %s", str(exc)[:200])
        return standard_md

    def _replace_markdown_image(self, match: re.Match, full_image_mapping: dict[str, str]) -> str:
        alt_text = match.group(1)
        img_filename = Path(match.group(2)).name
        new_name = full_image_mapping.get(img_filename)
        if new_name:
            return f"![{alt_text}]({self.STANDARD_IMAGE_DIR}/{new_name})"
        return match.group(0)

    def _resolve_html_image_src(self, img_path: str, full_image_mapping: dict[str, str]) -> str | None:
        new_name = full_image_mapping.get(Path(img_path).name)
        if new_name:
            return f"{self.STANDARD_IMAGE_DIR}/{new_name}"
        return None

    def _normalize_local_files(self, output_dir: Path) -> dict[str, Any]:
        """
        Normalize PaddleOCR-VL output directory layout.

        - Move/rename all page images into `images/` with sequential names.
        - Merge page JSON files into `result.json`, and inject img_path into image blocks.
        - Copy/rename the main markdown into `result.md` and rewrite image refs.
        """
        logger.info("[paddle_vl] normalizing output: %s", str(output_dir))

        standard_image_dir = output_dir / self.STANDARD_IMAGE_DIR
        standard_image_dir.mkdir(exist_ok=True)
        image_mapping, image_counter, page_dirs = self._collect_image_mapping(
            output_dir=output_dir,
            standard_image_dir=standard_image_dir,
        )
        all_pages_data = self._merge_page_jsons(page_dirs=page_dirs, image_mapping=image_mapping)
        standard_json = self._write_combined_json(output_dir=output_dir, pages=all_pages_data)
        standard_md = self._normalize_markdown_file(output_dir=output_dir, image_mapping=image_mapping)

        return {
            "markdown_file": standard_md,
            "json_file": standard_json,
            "image_dir": standard_image_dir,
            "image_count": image_counter - 1,
        }

    def _handle_zip_response(
        self,
        *,
        resp: requests.Response,
        artifact_root: Path,
        dataset_id: str | None,
        document_id: str | None,
        tenant_id: str | None,
    ) -> tuple[str, str | None]:
        artifact_root.mkdir(parents=True, exist_ok=True)

        zip_path = artifact_root / "paddlevl_output.zip"
        zip_path.write_bytes(resp.content or b"")

        # When object storage is enabled and we have stable identifiers, upload images to MinIO and
        # rewrite markdown refs to signed/public URLs (ZipImageProcessor handles both md + <img> tags).
        if settings.MINIO_ENABLED and dataset_id and document_id:
            out = ZipImageProcessor.process_zip_with_images(
                zip_path=zip_path,
                dataset_id=str(dataset_id),
                document_id=str(document_id),
                tenant_id=tenant_id,
            )
            markdown_text = str(out.get("markdown") or "")
            return markdown_text, None

        extract_root = artifact_root / "output"
        extract_root.mkdir(parents=True, exist_ok=True)

        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            ZipImageProcessor._safe_extract(zip_ref, extract_root)

        # Normalize extracted artifacts into a stable layout under extract_root:
        # - result.md at root
        # - images/ at root (optional)
        try:
            normalized = normalize_extracted_artifacts(extract_root)
        except Exception as exc:
            logger.warning("[paddle_vl] artifact normalize failed: %s", str(exc)[:200])
            normalized = {"markdown_file": None}

        md_path = normalized.get("markdown_file")
        if isinstance(md_path, Path) and md_path.exists():
            return md_path.read_text(encoding="utf-8", errors="ignore"), str(extract_root)

        return "", str(extract_root)

    def parse(
        self,
        file_path: Path,
        *,
        dataset_id: str | None = None,  # kept for interface parity
        document_id: str | None = None,
        tenant_id: str | None = None,  # noqa: ARG002 - reserved for future use
        pdf_quality: dict[str, Any] | None = None,  # noqa: ARG002 - reserved for future use
        **_kwargs,
    ) -> list[Document]:
        _ = (dataset_id, tenant_id, pdf_quality)
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        artifact_root = self._build_artifact_root(file_path, document_id)

        logger.info("[paddle_vl] parsing %s", file_path.name)
        resp = self._post_multipart(file_path=file_path)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise RuntimeError(f"PaddleOCR-VL API error {resp.status_code}: {(resp.text or '')[:500]}")

        markdown_text = ""
        asset_base_dir: str | None = None

        if self._looks_like_zip(resp):
            markdown_text, asset_base_dir = self._handle_zip_response(
                resp=resp,
                artifact_root=artifact_root,
                dataset_id=dataset_id,
                document_id=document_id,
                tenant_id=tenant_id,
            )
        else:
            ctype = str(resp.headers.get("content-type") or "").lower()
            if "application/json" in ctype:
                try:
                    data = resp.json()
                except Exception:
                    data = json.loads((resp.text or "").strip() or "{}")
                markdown_text = self._extract_markdown_from_json(data)
            else:
                markdown_text = resp.text or ""

        # If object storage is disabled, strip image references to avoid dead links after artifact cleanup.
        if not settings.MINIO_ENABLED and markdown_text:
            markdown_text = re.sub(r"!\[[^\]]*\]\(\s*[^)\s]+?\s*\)\s*", "", markdown_text)
            markdown_text = re.sub(r"<img[^>]*?>", "", markdown_text, flags=re.IGNORECASE)

        metadata: dict[str, Any] = {
            "source": str(file_path.name),
            "file_type": "pdf",
            "parser_backend": "paddle_vl",
            "element_kind": "paragraph",
            "element_text": markdown_text,
            "element_attributes": {
                "source_content_type": "text",
                "source_doc_type": "paragraph",
            },
            "artifact_dir": str(artifact_root),
        }
        if asset_base_dir:
            metadata["asset_base_dir"] = asset_base_dir
        if dataset_id:
            metadata["dataset_id"] = str(dataset_id)

        return [Document(page_content=markdown_text, metadata=metadata)]
