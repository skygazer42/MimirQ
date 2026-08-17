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
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from io import BytesIO
from os import PathLike
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pdfplumber
from PIL import Image

from app.deepdoc.parser.pdf_parser import IntegratedPipelinePdfParser
from app.parsing.utils.zip_processor import ZipImageProcessor

LOCK_KEY_pdfplumber = "global_shared_lock_pdfplumber"
if LOCK_KEY_pdfplumber not in sys.modules:
    sys.modules[LOCK_KEY_pdfplumber] = threading.Lock()

VALID_MINERU_BACKENDS = (
    "pipeline",
    "vlm-http-client",
    "vlm-transformers",
    "vlm-vllm-engine",
    "vlm-mlx-engine",
    "vlm-vllm-async-engine",
    "vlm-lmdeploy-engine",
)


class MinerUContentType(StrEnum):
    IMAGE = "image"
    TABLE = "table"
    TEXT = "text"
    EQUATION = "equation"
    CODE = "code"
    LIST = "list"
    DISCARDED = "discarded"


# Mapping from language names to MinerU language codes
LANGUAGE_TO_MINERU_MAP = {
    "English": "en",
    "Chinese": "ch",
    "Traditional Chinese": "chinese_cht",
    "Russian": "east_slavic",
    "Ukrainian": "east_slavic",
    "Indonesian": "latin",
    "Spanish": "latin",
    "Vietnamese": "latin",
    "Japanese": "japan",
    "Korean": "korean",
    "Portuguese BR": "latin",
    "German": "latin",
    "French": "latin",
    "Italian": "latin",
    "Tamil": "ta",
    "Telugu": "te",
    "Kannada": "ka",
    "Thai": "th",
    "Greek": "el",
    "Hindi": "devanagari",
}


class MinerUBackend(StrEnum):
    """MinerU processing backend options."""

    PIPELINE = "pipeline"  # Traditional multimodel pipeline (default)
    VLM_TRANSFORMERS = "vlm-transformers"  # Vision-language model using HuggingFace Transformers
    VLM_MLX_ENGINE = "vlm-mlx-engine"  # Faster, requires Apple Silicon and macOS 13.5+
    VLM_VLLM_ENGINE = "vlm-vllm-engine"  # Local vLLM engine, requires local GPU
    VLM_VLLM_ASYNC_ENGINE = "vlm-vllm-async-engine"  # Asynchronous vLLM engine, new in MinerU API
    VLM_LMDEPLOY_ENGINE = "vlm-lmdeploy-engine"  # LMDeploy engine
    VLM_HTTP_CLIENT = "vlm-http-client"  # HTTP client for remote vLLM server (CPU only)


class MinerULanguage(StrEnum):
    """MinerU supported languages for OCR (pipeline backend only)."""

    CH = "ch"  # Chinese
    CH_SERVER = "ch_server"  # Chinese (server)
    CH_LITE = "ch_lite"  # Chinese (lite)
    EN = "en"  # English
    KOREAN = "korean"  # Korean
    JAPAN = "japan"  # Japanese
    CHINESE_CHT = "chinese_cht"  # Chinese Traditional
    TA = "ta"  # Tamil
    TE = "te"  # Telugu
    KA = "ka"  # Kannada
    TH = "th"  # Thai
    EL = "el"  # Greek
    LATIN = "latin"  # Latin
    ARABIC = "arabic"  # Arabic
    EAST_SLAVIC = "east_slavic"  # East Slavic
    CYRILLIC = "cyrillic"  # Cyrillic
    DEVANAGARI = "devanagari"  # Devanagari


class MinerUParseMethod(StrEnum):
    """MinerU PDF parsing methods (pipeline backend only)."""

    AUTO = "auto"  # Automatically determine the method based on the file type
    TXT = "txt"  # Use text extraction method
    OCR = "ocr"  # Use OCR method for image-based PDFs


@dataclass
class MinerUParseOptions:
    """Options for MinerU PDF parsing."""

    backend: MinerUBackend = MinerUBackend.PIPELINE
    lang: MinerULanguage | None = None  # language for OCR (pipeline backend only)
    method: MinerUParseMethod = MinerUParseMethod.AUTO
    server_url: str | None = None
    delete_output: bool = True
    parse_method: str = "raw"
    formula_enable: bool = True
    table_enable: bool = True


class MinerUParser(IntegratedPipelinePdfParser):
    def __init__(self, mineru_path: str = "mineru", mineru_api: str = "", mineru_server_url: str = ""):
        super().__init__()
        self.mineru_api = mineru_api.rstrip("/")
        self.mineru_server_url = mineru_server_url.rstrip("/")
        self.outlines = []
        self.logger = logging.getLogger(self.__class__.__name__)

    def _extract_zip_no_root(self, zip_path, extract_to, root_dir):
        self.logger.info(f"[MinerU] Extract zip: zip_path={zip_path}, extract_to={extract_to}, root_hint={root_dir}")
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            with tempfile.TemporaryDirectory() as temp_dir:
                temp_path = Path(temp_dir)
                ZipImageProcessor._safe_extract(zip_ref, temp_path)
                source = temp_path
                if root_dir:
                    candidate = temp_path / ZipImageProcessor._sanitize_zip_member(root_dir.rstrip("/"))
                    if candidate.is_dir():
                        source = candidate
                Path(extract_to).mkdir(parents=True, exist_ok=True)
                for child in source.iterdir():
                    target = Path(extract_to) / child.name
                    if child.is_dir():
                        shutil.copytree(child, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(child, target)

    @staticmethod
    def _is_http_endpoint_valid(url, timeout=5):
        try:
            with httpx.Client(follow_redirects=True, timeout=float(timeout)) as client:
                response = client.head(url)
            return int(response.status_code) in {200, 301, 302, 307, 308}
        except (httpx.HTTPError, ValueError):
            return False

    def check_installation(self, backend: str = "pipeline", server_url: str | None = None) -> tuple[bool, str]:
        reason = ""
        if backend not in VALID_MINERU_BACKENDS:
            reason = f"[MinerU] Invalid backend '{backend}'. Valid backends are: {list(VALID_MINERU_BACKENDS)}"
            self.logger.warning(reason)
            return False, reason

        if not self.mineru_api:
            reason = "[MinerU] MINERU_APISERVER not configured."
            self.logger.warning(reason)
            return False, reason

        api_openapi = f"{self.mineru_api}/openapi.json"
        try:
            api_ok = self._is_http_endpoint_valid(api_openapi)
            self.logger.info(f"[MinerU] API openapi.json reachable={api_ok} url={api_openapi}")
            if not api_ok:
                reason = f"[MinerU] MinerU API not accessible: {api_openapi}"
                return False, reason
        except Exception as exc:
            reason = f"[MinerU] MinerU API check failed: {exc}"
            self.logger.warning(reason)
            return False, reason

        if backend == "vlm-http-client":
            resolved_server = server_url or self.mineru_server_url
            if not resolved_server:
                reason = "[MinerU] MINERU_SERVER_URL required for vlm-http-client backend."
                self.logger.warning(reason)
                return False, reason
            try:
                server_ok = self._is_http_endpoint_valid(resolved_server)
                self.logger.info(f"[MinerU] vlm-http-client server check reachable={server_ok} url={resolved_server}")
            except Exception as exc:
                self.logger.warning(f"[MinerU] vlm-http-client server probe failed: {resolved_server}: {exc}")

        return True, reason

    def _run_mineru(
        self, input_path: Path, output_dir: Path, options: MinerUParseOptions, callback: Callable | None = None
    ) -> Path:
        return self._run_mineru_api(input_path, output_dir, options, callback)

    def _run_mineru_api(
        self, input_path: Path, output_dir: Path, options: MinerUParseOptions, callback: Callable | None = None
    ) -> Path:
        pdf_file_path = str(input_path)

        if not os.path.exists(pdf_file_path):
            raise RuntimeError(f"[MinerU] PDF file not exists: {pdf_file_path}")

        pdf_file_name = Path(pdf_file_path).stem.strip()
        output_path = tempfile.mkdtemp(prefix=f"{pdf_file_name}_{options.method}_", dir=str(output_dir))
        output_zip_path = os.path.join(str(output_dir), f"{Path(output_path).name}.zip")

        data = {
            "output_dir": "./output",
            "lang_list": options.lang,
            "backend": options.backend,
            "parse_method": options.method,
            "formula_enable": options.formula_enable,
            "table_enable": options.table_enable,
            "server_url": None,
            "return_md": True,
            "return_middle_json": True,
            "return_model_output": True,
            "return_content_list": True,
            "return_images": True,
            "response_format_zip": True,
            "start_page_id": 0,
            "end_page_id": 99999,
        }

        if options.server_url:
            data["server_url"] = options.server_url
        elif self.mineru_server_url:
            data["server_url"] = self.mineru_server_url

        self.logger.info(f"[MinerU] request {data=}")
        self.logger.info(f"[MinerU] request {options=}")

        headers = {"Accept": "application/json"}
        try:
            self.logger.info(
                "[MinerU] invoke api: %s/file_parse backend=%s server_url=%s",
                self.mineru_api,
                options.backend,
                data.get("server_url"),
            )
            if callback:
                callback(0.20, f"[MinerU] invoke api: {self.mineru_api}/file_parse")
            with open(pdf_file_path, "rb") as fh:
                files = {"files": (pdf_file_name + ".pdf", fh, "application/pdf")}
                with httpx.Client(timeout=1800.0) as client:
                    response = client.post(
                        url=f"{self.mineru_api}/file_parse",
                        files=files,
                        data=data,
                        headers=headers,
                    )

            response.raise_for_status()
            if response.headers.get("Content-Type") == "application/zip":
                self.logger.info(f"[MinerU] zip file returned, saving to {output_zip_path}...")

                if callback:
                    callback(0.30, f"[MinerU] zip file returned, saving to {output_zip_path}...")

                with open(output_zip_path, "wb") as f:
                    f.write(response.content)

                self.logger.info(f"[MinerU] Unzip to {output_path}...")
                self._extract_zip_no_root(output_zip_path, output_path, pdf_file_name + "/")

                if callback:
                    callback(0.40, f"[MinerU] Unzip to {output_path}...")
            else:
                self.logger.warning(f"[MinerU] not zip returned from api: {response.headers.get('Content-Type')}")
        except Exception as e:
            raise RuntimeError(f"[MinerU] api failed with exception {e}")
        self.logger.info("[MinerU] Api completed successfully.")
        return Path(output_path)

    def __images__(self, fnm, zoomin: int = 1, page_from=0, page_to=600, callback=None):
        self.page_from = page_from
        self.page_to = page_to
        pdf = None
        try:
            pdf = pdfplumber.open(fnm) if isinstance(fnm, (str, PathLike)) else pdfplumber.open(BytesIO(fnm))
            self.pdf = pdf
            self.page_images = [
                p.to_image(resolution=72 * zoomin, antialias=True).original
                for _, p in enumerate(self.pdf.pages[page_from:page_to])
            ]
        except Exception as e:
            self.page_images = None
            self.total_page = 0
            self.logger.exception(e)
        finally:
            if pdf is not None:
                pdf.close()

    def _line_tag(self, bx, zoom=1):
        pn = [bx["page_idx"] + 1]
        positions = bx.get("bbox", (0, 0, 0, 0))
        x0, top, x1, bott = positions

        if hasattr(self, "page_images") and self.page_images and len(self.page_images) > bx["page_idx"]:
            page_width, page_height = self.page_images[bx["page_idx"]].size
            x0 = (x0 / 1000.0) * page_width
            x1 = (x1 / 1000.0) * page_width
            top = (top / 1000.0) * page_height
            bott = (bott / 1000.0) * page_height

        return "@@{}\t{:.1f}\t{:.1f}\t{:.1f}\t{:.1f}##".format("-".join([str(p) for p in pn]), x0, x1, top, bott)

    @staticmethod
    def _empty_crop_result(need_position: bool):
        return (None, None) if need_position else None

    def _filter_valid_crop_positions(self, poss, page_count: int):
        filtered_poss = []
        for pns, left, right, top, bottom in poss:
            if not pns:
                self.logger.warning("[MinerU] Empty page index list in crop; skipping this position.")
                continue
            valid_pns = [p for p in pns if 0 <= p < page_count]
            if not valid_pns:
                self.logger.warning(
                    "[MinerU] All page indices %s out of range for %s pages; skipping.",
                    pns,
                    page_count,
                )
                continue
            filtered_poss.append((valid_pns, left, right, top, bottom))
        return filtered_poss

    def _expand_crop_positions(self, poss, page_count: int):
        gap = 6
        expanded = list(poss)
        first_pos = expanded[0]
        expanded.insert(
            0,
            (
                [first_pos[0][0]],
                first_pos[1],
                first_pos[2],
                max(0, first_pos[3] - 120),
                max(first_pos[3] - gap, 0),
            ),
        )
        last_pos = expanded[-1]
        last_page_idx = last_pos[0][-1]
        if not (0 <= last_page_idx < page_count):
            self.logger.warning(
                "[MinerU] Last page index %s out of range for %s pages; skipping crop.",
                last_page_idx,
                page_count,
            )
            return None

        last_page_height = self.page_images[last_page_idx].size[1]
        expanded.append(
            (
                [last_page_idx],
                last_pos[1],
                last_pos[2],
                min(last_page_height, last_pos[4] + gap),
                min(last_page_height, last_pos[4] + 120),
            )
        )
        return expanded

    def _append_previous_page_heights(self, pns, bottom: float | int, page_count: int):
        for pn in pns[1:]:
            if 0 <= pn - 1 < page_count:
                bottom += self.page_images[pn - 1].size[1]
            else:
                self.logger.warning(
                    "[MinerU] Page index %s-1 out of range for %s pages during crop; skipping height accumulation.",
                    pn,
                    page_count,
                )
        return bottom

    @staticmethod
    def _crop_box(
        left: float,
        right: float,
        top: float | int,
        bottom: float | int,
        page_height: int,
    ):
        return int(left), int(top), int(right), int(min(bottom, page_height))

    def _collect_crop_images(self, poss, max_width: float, page_count: int):
        imgs = []
        positions = []
        for ii, (pns, left, _right, top, bottom) in enumerate(poss):
            right = left + max_width
            if bottom <= top:
                bottom = top + 2
            bottom = self._append_previous_page_heights(pns, bottom, page_count)

            if not (0 <= pns[0] < page_count):
                self.logger.warning(
                    "[MinerU] Base page index %s out of range for %s pages during crop; skipping this segment.",
                    pns[0],
                    page_count,
                )
                continue

            img0 = self.page_images[pns[0]]
            x0, y0, x1, y1 = self._crop_box(left, right, top, bottom, img0.size[1])
            imgs.append(img0.crop((x0, y0, x1, y1)))
            if 0 < ii < len(poss) - 1:
                positions.append((pns[0] + self.page_from, x0, x1, y0, y1))

            bottom -= img0.size[1]
            for pn in pns[1:]:
                if not (0 <= pn < page_count):
                    self.logger.warning(
                        "[MinerU] Page index %s out of range for %s pages during crop; skipping this page.",
                        pn,
                        page_count,
                    )
                    continue
                page = self.page_images[pn]
                x0, y0, x1, y1 = self._crop_box(left, right, 0, bottom, page.size[1])
                imgs.append(page.crop((x0, y0, x1, y1)))
                if 0 < ii < len(poss) - 1:
                    positions.append((pn + self.page_from, x0, x1, y0, y1))
                bottom -= page.size[1]
        return imgs, positions

    @staticmethod
    def _compose_crop_image(imgs):
        gap = 6
        height = sum(img.size[1] + gap for img in imgs)
        width = int(np.max([img.size[0] for img in imgs]))
        pic = Image.new("RGB", (width, int(height)), (245, 245, 245))
        pasted_height = 0
        for ii, img in enumerate(imgs):
            if ii == 0 or ii + 1 == len(imgs):
                img = img.convert("RGBA")
                overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
                overlay.putalpha(128)
                img = Image.alpha_composite(img, overlay).convert("RGB")
            pic.paste(img, (0, int(pasted_height)))
            pasted_height += img.size[1] + gap
        return pic

    def crop(self, text, _zoom=1, need_position=False):
        poss = self.extract_positions(text)
        if not poss:
            return self._empty_crop_result(need_position)

        if not getattr(self, "page_images", None):
            self.logger.warning("[MinerU] crop called without page images; skipping image generation.")
            return self._empty_crop_result(need_position)

        page_count = len(self.page_images)
        poss = self._filter_valid_crop_positions(poss, page_count)
        if not poss:
            self.logger.warning("[MinerU] No valid positions after filtering; skip cropping.")
            return self._empty_crop_result(need_position)

        max_width = max(np.max([right - left for (_, left, right, _, _) in poss]), 6)
        poss = self._expand_crop_positions(poss, page_count)
        if not poss:
            return self._empty_crop_result(need_position)

        imgs, positions = self._collect_crop_images(poss, max_width, page_count)

        if not imgs:
            return self._empty_crop_result(need_position)

        pic = self._compose_crop_image(imgs)
        if need_position:
            return pic, positions
        return pic

    @staticmethod
    def extract_positions(txt: str):
        poss = []
        for tag in re.findall(r"@@[0-9-]+\t[0-9.\t]+##", txt):
            pn, left, right, top, bottom = tag.strip("#").strip("@").split("\t")
            left, right, top, bottom = float(left), float(right), float(top), float(bottom)
            poss.append(([int(p) - 1 for p in pn.split("-")], left, right, top, bottom))
        return poss

    @staticmethod
    def _sanitize_filename(name: str) -> str:
        sanitized = name.replace("/", "").replace("\\", "")
        while ".." in sanitized:
            sanitized = sanitized.replace("..", "")
        sanitized = re.sub(r"[^\w.-]", "_", sanitized, flags=re.UNICODE)
        if sanitized.startswith("."):
            sanitized = "_" + sanitized[1:]
        return sanitized or "unnamed"

    def _resolve_output_json_file(self, output_dir: Path, file_stem: str):
        safe_stem = self._sanitize_filename(file_stem)
        allowed_names = {
            f"{file_stem}_content_list.json",
            f"{safe_stem}_content_list.json",
        }
        self.logger.info(f"[MinerU] Expected output files: {', '.join(sorted(allowed_names))}")
        self.logger.info(f"[MinerU] Searching output in: {output_dir}")

        candidates = [
            output_dir / f"{file_stem}_content_list.json",
            output_dir / f"{safe_stem}_content_list.json",
            output_dir / safe_stem / f"{safe_stem}_content_list.json",
        ]
        descriptions = [
            "original path",
            "sanitized filename",
            "sanitized nested path",
        ]
        attempted = []
        for candidate, description in zip(candidates, descriptions):
            self.logger.info(f"[MinerU] Trying {description}: {candidate}")
            attempted.append(candidate)
            if candidate.exists():
                return candidate, candidate.parent, attempted

        raise FileNotFoundError(f"[MinerU] Missing output file, tried: {', '.join(str(path) for path in attempted)}")

    @staticmethod
    def _rewrite_output_asset_paths(data: list[dict[str, Any]], subdir: Path):
        for item in data:
            for key in ("img_path", "table_img_path", "equation_img_path"):
                if key in item and item[key]:
                    item[key] = str((subdir / item[key]).resolve())
        return data

    def _read_output(
        self,
        output_dir: Path,
        file_stem: str,
        method: str = "auto",
        backend: str = "pipeline",
    ) -> list[dict[str, Any]]:
        _ = (method, backend)
        json_file, subdir, _attempted = self._resolve_output_json_file(output_dir, file_stem)
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return self._rewrite_output_asset_paths(data, subdir)

    @staticmethod
    def _section_from_output(output: dict[str, Any]):
        match output["type"]:
            case MinerUContentType.TEXT:
                return output.get("text", "")
            case MinerUContentType.TABLE:
                section = (
                    output.get("table_body", "")
                    + "\n".join(output.get("table_caption", []))
                    + "\n".join(output.get("table_footnote", []))
                )
                return section.strip() or "FAILED TO PARSE TABLE"
            case MinerUContentType.IMAGE:
                return "".join(output.get("image_caption", [])) + "\n" + "".join(output.get("image_footnote", []))
            case MinerUContentType.EQUATION:
                return output.get("text", "")
            case MinerUContentType.CODE:
                return output.get("code_body", "") + "\n".join(output.get("code_caption", []))
            case MinerUContentType.LIST:
                return "\n".join(output.get("list_items", []))
            case MinerUContentType.DISCARDED:
                return None
        return ""

    def _section_entry(self, output: dict[str, Any], section: str, parse_method: str | None):
        if parse_method == "manual":
            return section, output["type"], self._line_tag(output)
        if parse_method == "paper":
            return section + self._line_tag(output), output["type"]
        return section, self._line_tag(output)

    def _transfer_to_sections(self, outputs: list[dict[str, Any]], parse_method: str = None):
        sections = []
        for output in outputs:
            section = self._section_from_output(output)
            if section is None:
                continue
            sections.append(self._section_entry(output, section, parse_method))
        return sections

    def _transfer_to_tables(self, outputs: list[dict[str, Any]]):
        _ = outputs
        return []

    @staticmethod
    def _parser_settings(kwargs: dict[str, Any]):
        parser_cfg = kwargs.get("parser_config", {})
        lang = parser_cfg.get("mineru_lang") or kwargs.get("lang", "English")
        return (
            LANGUAGE_TO_MINERU_MAP.get(lang, "ch"),
            parser_cfg.get("mineru_parse_method", "auto"),
            parser_cfg.get("mineru_formula_enable", True),
            parser_cfg.get("mineru_table_enable", True),
        )

    def _prepare_pdf_input(self, filepath: str | PathLike[str], binary: BytesIO | bytes, callback):
        file_path = Path(filepath)
        pdf_file_name = file_path.stem.replace(" ", "") + ".pdf"
        pdf_file_path_valid = os.path.join(file_path.parent, pdf_file_name)

        if binary:
            temp_dir = Path(tempfile.mkdtemp(prefix="mineru_bin_pdf_"))
            temp_pdf = temp_dir / pdf_file_name
            with open(temp_pdf, "wb") as f:
                f.write(binary)
            self.logger.info(f"[MinerU] Received binary PDF -> {temp_pdf}")
            if callback:
                callback(0.15, f"[MinerU] Received binary PDF -> {temp_pdf}")
            return temp_pdf, temp_pdf

        if pdf_file_path_valid != filepath:
            self.logger.info(f"[MinerU] Remove all space in file name: {pdf_file_path_valid}")
            shutil.move(filepath, pdf_file_path_valid)
        pdf = Path(pdf_file_path_valid)
        if not pdf.exists():
            if callback:
                callback(-1, f"[MinerU] PDF not found: {pdf}")
            raise FileNotFoundError(f"[MinerU] PDF not found: {pdf}")
        return pdf, None

    @staticmethod
    def _prepare_output_dir(output_dir: str | None):
        if output_dir:
            out_dir = Path(output_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            return out_dir, False
        return Path(tempfile.mkdtemp(prefix="mineru_pdf_")), True

    def _cleanup_temp_pdf(self, temp_pdf: Path | None):
        if temp_pdf and temp_pdf.exists():
            try:
                temp_pdf.unlink()
                temp_pdf.parent.rmdir()
            except Exception as exc:
                self.logger.debug("[MinerU] Failed to clean temporary PDF %s: %s", temp_pdf, exc)

    def _cleanup_output_dir(self, delete_output: bool, created_tmp_dir: bool, out_dir: Path):
        if delete_output and created_tmp_dir and out_dir.exists():
            try:
                shutil.rmtree(out_dir)
            except Exception as exc:
                self.logger.debug("[MinerU] Failed to remove temporary output %s: %s", out_dir, exc)

    def parse_pdf(
        self,
        filepath: str | PathLike[str],
        binary: BytesIO | bytes,
        callback: Callable | None = None,
        *,
        output_dir: str | None = None,
        backend: str = "pipeline",
        server_url: str | None = None,
        delete_output: bool = True,
        parse_method: str = "raw",
        **kwargs,
    ) -> tuple:
        mineru_lang_code, mineru_method_raw_str, enable_formula, enable_table = self._parser_settings(kwargs)
        pdf, temp_pdf = self._prepare_pdf_input(filepath, binary, callback)
        out_dir, created_tmp_dir = self._prepare_output_dir(output_dir)

        self.logger.info(
            "[MinerU] Output directory: %s backend=%s api=%s server_url=%s",
            out_dir,
            backend,
            self.mineru_api,
            server_url or self.mineru_server_url,
        )
        if callback:
            callback(0.15, f"[MinerU] Output directory: {out_dir}")

        self.__images__(pdf, zoomin=1)

        try:
            options = MinerUParseOptions(
                backend=MinerUBackend(backend),
                lang=MinerULanguage(mineru_lang_code),
                method=MinerUParseMethod(mineru_method_raw_str),
                server_url=server_url,
                delete_output=delete_output,
                parse_method=parse_method,
                formula_enable=enable_formula,
                table_enable=enable_table,
            )
            final_out_dir = self._run_mineru(pdf, out_dir, options, callback=callback)
            outputs = self._read_output(final_out_dir, pdf.stem, method=mineru_method_raw_str, backend=backend)
            self.logger.info(f"[MinerU] Parsed {len(outputs)} blocks from PDF.")
            if callback:
                callback(0.75, f"[MinerU] Parsed {len(outputs)} blocks from PDF.")

            return self._transfer_to_sections(outputs, parse_method), self._transfer_to_tables(outputs)
        finally:
            self._cleanup_temp_pdf(temp_pdf)
            self._cleanup_output_dir(delete_output, created_tmp_dir, out_dir)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    parser = MinerUParser("mineru")
    ok, reason = parser.check_installation()
    logging.info("MinerU available: %s", ok)

    filepath = ""
    with open(filepath, "rb") as file:
        outputs = parser.parse_pdf(filepath=filepath, binary=file.read())
        for output in outputs:
            logging.info("%s", output)
