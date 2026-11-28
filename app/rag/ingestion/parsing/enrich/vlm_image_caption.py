# Figure analysis includes adaptations from InfiniFlow DeepDoc (Apache-2.0); see NOTICE.
"""
VLM-backed inline image captioning.

Design constraints:
- Safe defaults: disabled unless explicitly enabled + API URL configured.
- No heavy model deps in-process: use external HTTP backend only.
- Best-effort: failures must not crash ingest/preview.
"""

import json
import logging
import re
import time
from contextlib import closing
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx
from PIL import Image

from app.infrastructure.config import settings
from app.infrastructure.runtime.async_bridge import run_coroutine_sync as _run_coroutine_sync
from app.rag.ingestion.parsing.enrich.image_caption import (
    _extract_line_images,
    _looks_like_table_row,
    _next_line_has_caption,
)
from app.rag.ingestion.parsing.enrich.image_references import normalize_local_image_ref as _normalize_local_image_ref
from app.rag.ingestion.parsing.enrich.image_references import read_local_image_bytes
from app.rag.ingestion.parsing.utils.markdown_response import strip_markdown_code_fence

logger = logging.getLogger("parsing.vlm_image_caption")
_IMAGE_CAPTION_PREFIX = "Image caption:"


_FENCE_RE = re.compile(r"^\s*(```+|~~~+)")

_GENERIC_ALT_RE = re.compile(r"^(image|figure|photo|picture|diagram|chart|page\s+\d+\s+image)\b", re.IGNORECASE)


def _clean_caption_text(s: str, *, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", s).strip()
    if not cleaned:
        return ""
    if max_chars > 0 and len(cleaned) > max_chars:
        cleaned = cleaned[: max(0, max_chars - 3)].rstrip() + "." * min(max_chars, 3)
    return cleaned


def _resolve_origin_image_path(*, src: str, origin_path: Path) -> Path | None:
    resolved_ref, reason = _normalize_local_image_ref(src)
    if reason:
        return None

    base_dir = origin_path.resolve(strict=False)
    if base_dir.is_file():
        base_dir = base_dir.parent

    base_dir_resolved = base_dir.resolve(strict=False)
    path_obj = Path(resolved_ref)
    if not path_obj.is_absolute():
        path_obj = (base_dir_resolved / path_obj).resolve(strict=False)
    else:
        path_obj = path_obj.resolve(strict=False)

    try:
        path_obj.relative_to(base_dir_resolved)
    except ValueError:
        return None
    if not path_obj.exists() or not path_obj.is_file():
        return None
    return path_obj


def _safe_read_local_image_bytes(*, src: str, origin_path: Path, max_bytes: int) -> bytes | None:
    raw = src.strip()
    if not raw:
        return None
    if raw.startswith("data:"):
        return None
    if urlparse(raw).scheme in {"http", "https"}:
        return None
    if "/api/v1/documents/image-url/" in raw:
        # Already rewritten to MinIO URL (no local file mapping here).
        return None
    path_obj = _resolve_origin_image_path(src=raw, origin_path=origin_path)
    if path_obj is None:
        return None
    image_bytes, _reason = read_local_image_bytes(path_obj, max_bytes=max_bytes)
    return image_bytes


async def _call_caption_backend_async(
    *,
    api_url: str,
    image_bytes: bytes,
    filename: str,
    timeout_sec: float,
) -> tuple[str, str]:
    """
    Best-effort caption backend call.

    Contract (flexible):
    - POST multipart form with file field "file"
    - Response:
      - JSON {"caption": "..."} OR {"text": "..."} OR
      - raw text body (treated as caption)
    """
    timeout = float(timeout_sec)
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.post(
                str(api_url).strip(),
                files={"file": (filename or "image", image_bytes, "application/octet-stream")},
            )
        except httpx.RequestError as exc:
            return "", f"http_failed:{exc.__class__.__name__}"

        if int(resp.status_code) >= 400:
            return "", f"http_{int(resp.status_code)}"

        content_type = str(resp.headers.get("content-type") or "").lower()
        try:
            if "application/json" in content_type:
                data = resp.json()
                if not isinstance(data, dict):
                    return "", "invalid_payload"
                has_text = False
                for key in ("caption", "text", "output"):
                    val = data.get(key)
                    if isinstance(val, str):
                        has_text = True
                        if val.strip():
                            return val, "ok_json"
                return "", "empty" if has_text else "invalid_payload"
            txt = resp.text
            if txt.strip():
                return txt, "ok_text"
        except json.JSONDecodeError as exc:
            return "", f"parse_failed:{exc.__class__.__name__}"

        return "", "empty"


def _call_caption_backend(*, api_url: str, image_bytes: bytes, filename: str, timeout_sec: float) -> tuple[str, str]:
    return _run_coroutine_sync(
        lambda: _call_caption_backend_async(
            api_url=api_url,
            image_bytes=image_bytes,
            filename=filename,
            timeout_sec=timeout_sec,
        )
    )


@dataclass(frozen=True, slots=True)
class VLMImageCaptionAudit:
    applied: bool
    captions_added: int
    images_attempted: int
    images_succeeded: int
    elapsed_ms: int
    backend: str
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "captions_added": self.captions_added,
            "images_attempted": self.images_attempted,
            "images_succeeded": self.images_succeeded,
            "elapsed_ms": self.elapsed_ms,
            "backend": self.backend,
            "error": (self.error[:200] if self.error else None),
        }


def _invalid_vlm_result(
    raw: str,
    *,
    error: str | None,
) -> tuple[str, int, VLMImageCaptionAudit]:
    return (
        raw,
        0,
        VLMImageCaptionAudit(
            applied=False,
            captions_added=0,
            images_attempted=0,
            images_succeeded=0,
            elapsed_ms=0,
            backend="vlm_http",
            error=error,
        ),
    )


def _filename_caption(src: str, *, max_caption_chars: int) -> str:
    return _clean_caption_text(Path(unquote(src.strip())).name, max_chars=max_caption_chars)


def _resolve_vlm_caption(
    *,
    alt: str,
    src: str,
    origin_path: Path,
    api_url: str,
    timeout_sec: float,
    max_bytes: int,
    max_caption_chars: int,
) -> tuple[str, int, int, str | None]:
    alt0 = _clean_caption_text(alt, max_chars=max_caption_chars)
    if alt0 and not _GENERIC_ALT_RE.match(alt0):
        return alt0, 0, 0, None

    image_bytes = _safe_read_local_image_bytes(src=src, origin_path=origin_path, max_bytes=max_bytes)
    if not image_bytes:
        return _filename_caption(src, max_caption_chars=max_caption_chars), 0, 0, "image_unavailable"

    cap_raw, note = _call_caption_backend(
        api_url=api_url,
        image_bytes=image_bytes,
        filename=str(Path(unquote(src.strip())).name or "image"),
        timeout_sec=timeout_sec,
    )
    cap = _clean_caption_text(cap_raw, max_chars=max_caption_chars)
    if cap:
        return cap, 1, 1, None
    logger.debug("VLM caption empty (%s)", note)
    return "", 1, 0, None if note == "empty" else note


def _resolve_line_captions(
    line: str,
    *,
    lines: list[str],
    idx: int,
    remaining: int,
    origin_path: Path,
    api_url: str,
    timeout_sec: float,
    max_bytes: int,
    max_caption_chars: int,
) -> tuple[int, list[str], int, int, list[str]]:
    if remaining <= 0 or _looks_like_table_row(line) or not line.strip() or _next_line_has_caption(lines, idx):
        return -1, [], 0, 0, []

    token_start, images = _extract_line_images(line)
    if not images:
        return token_start, [], 0, 0, []

    captions: list[str] = []
    attempted = 0
    succeeded = 0
    errors: list[str] = []
    for alt, src in images:
        if len(captions) + attempted - succeeded >= remaining:
            break
        caption, attempted_inc, succeeded_inc, error = _resolve_vlm_caption(
            alt=alt,
            src=src,
            origin_path=origin_path,
            api_url=api_url,
            timeout_sec=timeout_sec,
            max_bytes=max_bytes,
            max_caption_chars=max_caption_chars,
        )
        attempted += attempted_inc
        succeeded += succeeded_inc
        if error is not None:
            errors.append(error)
        if caption:
            captions.append(caption)
    return token_start, captions, attempted, succeeded, errors


def add_vlm_image_captions(
    markdown: str,
    *,
    origin_path: Path,
    api_url: str,
    timeout_sec: float = 60.0,
    max_images: int = 20,
    max_image_bytes: int | None = None,
    prefix: str = _IMAGE_CAPTION_PREFIX,
    max_caption_chars: int = 200,
) -> tuple[str, int, VLMImageCaptionAudit]:
    """
    Insert VLM captions after inline images in markdown (best-effort).
    """
    raw = markdown
    if not raw:
        return _invalid_vlm_result("", error=None)

    url = api_url.strip()
    if not url:
        return _invalid_vlm_result(raw, error="missing_api_url")

    max_images_i = max(0, int(max_images or 0))
    if max_images_i <= 0:
        return _invalid_vlm_result(raw, error="max_images_zero")

    max_bytes = max(0, settings.MAX_INLINE_IMAGE_BYTES if max_image_bytes is None else max_image_bytes)

    lines = raw.splitlines()
    ends_with_newline = raw.endswith("\n")

    out: list[str] = []
    added = 0
    attempted = 0
    succeeded = 0
    in_fence = False
    t0 = time.perf_counter()
    errors: list[str] = []

    for idx, line in enumerate(lines):
        out.append(line)

        if _FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if added + attempted - succeeded >= max_images_i:
            continue
        token_start, captions, attempted_inc, succeeded_inc, line_errors = _resolve_line_captions(
            line,
            lines=lines,
            idx=idx,
            remaining=max_images_i - (added + attempted - succeeded),
            origin_path=origin_path,
            api_url=url,
            timeout_sec=float(timeout_sec),
            max_bytes=max_bytes,
            max_caption_chars=int(max_caption_chars or 0),
        )
        attempted += attempted_inc
        succeeded += succeeded_inc
        errors.extend(line_errors)

        if not captions:
            continue

        added += len(captions)
        prefix0 = str(prefix or _IMAGE_CAPTION_PREFIX).strip() or _IMAGE_CAPTION_PREFIX
        lead = line[:token_start]
        caption_text = _clean_caption_text("; ".join(captions), max_chars=max_caption_chars)
        if caption_text:
            out.append(f"{lead}{prefix0} {caption_text}")

    result = "\n".join(out) if added else raw
    if ends_with_newline and not result.endswith("\n"):
        result += "\n"

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000))
    audit = VLMImageCaptionAudit(
        applied=added > 0 or attempted > 0,
        captions_added=added,
        images_attempted=attempted,
        images_succeeded=succeeded,
        elapsed_ms=elapsed_ms,
        backend="vlm_http",
        error="; ".join(dict.fromkeys(errors))[:200] or None,
    )
    return result, added, audit


__all__ = [
    "VLMImageCaptionAudit",
    "add_vlm_image_captions",
    "describe_image_with_model",
    "enrich_figures",
    "VisionFigureParser",
    "page_transcription_prompt",
]


def page_transcription_prompt(page=None) -> str:
    prompt_en = """
INSTRUCTION:
Transcribe the content from the provided PDF page image into clean Markdown format.
- Only output the content transcribed from the image.
- Do NOT output this instruction or any other explanation.
- If the content is missing or you do not understand the input, return an empty string.

RULES:
1. Do NOT generate examples, demonstrations, or templates.
2. Do NOT output any extra text such as 'Example', 'Example Output', or similar.
3. Do NOT generate any tables, headings, or content that is not explicitly present in the image.
4. Transcribe content word-for-word. Do NOT modify, translate, or omit any content.
5. Do NOT explain Markdown or mention that you are using Markdown.
6. Do NOT wrap the output in ```markdown or ``` blocks.
7. Only apply Markdown structure to headings, paragraphs, lists, and tables, \
strictly based on the layout of the image. Do NOT create tables unless an actual table exists in the image.
8. Preserve the original language, information, and order exactly as shown in the image.
"""

    if page is not None:
        prompt_en += f"\nAt the end of the transcription, add the page divider: `--- Page {page} ---`."

    prompt_en += """
FAILURE HANDLING:
- If you do not detect valid content in the image, return an empty string.
"""
    return prompt_en


def figure_description_prompt() -> str:
    prompt = """
You are an expert visual data analyst. Analyze the image and provide a comprehensive description of its content. \
Focus on identifying the type of visual data representation (e.g., bar chart, pie chart, line graph, table, \
flowchart), its structure, and any text captions or labels included in the image.

Tasks:
1. Describe the overall structure of the visual representation. Specify if it is a chart, graph, table, or \
diagram.
2. Identify and extract any axes, legends, titles, or labels present in the image. Provide the exact text \
where available.
3. Extract the data points from the visual elements (e.g., bar heights, line graph coordinates, pie chart \
segments, table rows and columns).
4. Analyze and explain any trends, comparisons, or patterns shown in the data.
5. Capture any annotations, captions, or footnotes, and explain their relevance to the image.
6. Only include details that are explicitly present in the image. If an element (e.g., axis, legend, or \
caption) does not exist or is not visible, do not mention it.

Output format (include only sections relevant to the image content):
- Visual Type: [Type]
- Title: [Title text, if available]
- Axes / Legends / Labels: [Details, if available]
- Data Points: [Extracted data]
- Trends / Insights: [Analysis and interpretation]
- Captions / Annotations: [Text and relevance, if available]

Ensure high accuracy, clarity, and completeness in your analysis, and includes only the information present \
in the image. Avoid unnecessary statements about missing elements.
"""
    return prompt


def describe_image_with_model(image, vision_model, prompt=None, callback=None):
    """Describe one image using the supplied model and its existing failure policy."""
    try:
        with BytesIO() as buffer, closing(image.convert("RGB")) as converted:
            converted.save(buffer, format="JPEG")
            answer = vision_model.describe_with_prompt(buffer.getvalue(), prompt)
        if not isinstance(answer, str):
            raise TypeError("Vision image description must be text")
        text = strip_markdown_code_fence(answer)
        return "\n" + text if text else ""
    except Exception as exc:
        if callback:
            callback(-1, str(exc))
        else:
            logger.warning("Vision image description failed: %s", exc)
        return ""


def _has_image_table(tbls):
    for item in tbls:
        if not isinstance(item, tuple) or not item:
            continue
        head = item[0]
        if isinstance(head, Image.Image):
            return True
        if isinstance(head, tuple) and head and isinstance(head[0], Image.Image):
            return True
    return False


def _load_vision_runtime():
    from app.rag.llm.vision_client import VisionCaptionClient

    return VisionCaptionClient


def _build_vision_model(vision_client, callback):
    try:
        return vision_client()
    except NotImplementedError as exc:
        if callback:
            callback(-1, f"Vision enrichment unavailable; using parsed tables unchanged. ({exc})")
        else:
            logger.warning("Vision enrichment unavailable: %s", exc)
        return None


class VisionFigureParser:
    def __init__(self, vision_model, figures_data):
        self.vision_model = vision_model
        self._extract_figures_info(figures_data)
        if len(self.figures) != len(self.descriptions):
            raise ValueError("Figure and description counts must match")

    def _extract_figures_info(self, figures_data):
        self.figures = []
        self.descriptions = []
        self.positions = []

        for item in figures_data:
            if not isinstance(item, tuple):
                raise ValueError("Figure entries must be tuples")
            # position
            if (
                len(item) == 2
                and isinstance(item[1], list)
                and len(item[1]) == 1
                and isinstance(item[1][0], tuple)
                and len(item[1][0]) == 5
            ):
                img_desc = item[0]
                if not (len(img_desc) == 2 and isinstance(img_desc[0], Image.Image) and isinstance(img_desc[1], list)):
                    raise ValueError("Should be (figure, [description])")
                self.figures.append(img_desc[0])
                self.descriptions.append(list(img_desc[1]))
                self.positions.append(item[1])
            else:
                if not (len(item) == 2 and isinstance(item, tuple) and isinstance(item[1], list)):
                    raise ValueError(f"get {len(item)=}, {item=}")
                self.figures.append(item[0])
                self.descriptions.append(list(item[1]))
                self.positions.append(None)

    def __call__(self, **kwargs):
        callback = kwargs.get("callback", lambda _prog, _msg: None)

        assembled = []
        for image, descriptions, positions in zip(self.figures, self.descriptions, self.positions, strict=True):
            txt = describe_image_with_model(
                image=image,
                vision_model=self.vision_model,
                prompt=figure_description_prompt(),
                callback=callback,
            )

            description = txt + "\n".join(descriptions) if txt else list(descriptions)
            figure_desc = (image, description)
            assembled.append((figure_desc, positions) if positions is not None else (figure_desc,))
        return assembled


def enrich_figures(tbls, *, callback=None):
    """Enrich parsed figure data with the configured optional vision model."""
    if not tbls or not isinstance(tbls, list):
        return tbls
    if not _has_image_table(tbls):
        return tbls
    vision_client = _load_vision_runtime()
    vision_model = _build_vision_model(vision_client, callback)
    if vision_model is None:
        return tbls
    try:
        try:
            parser = VisionFigureParser(vision_model, tbls)
        except ValueError as exc:
            if callback:
                callback(-1, f"Vision enrichment failed; using parsed tables unchanged. ({exc})")
            else:
                logger.warning("Vision figure enrichment failed: %s", exc)
            return tbls
        return parser(callback=callback)
    finally:
        vision_model.close()
