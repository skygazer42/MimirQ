import json
import math
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import onnxruntime as ort
from langchain_core.documents import Document
from PIL import Image as PILImage

from app.core.config import settings

_DEFAULT_ENGINE = "trocr_seal_onnx"
_DEFAULT_THRESHOLD = 0.88
_DEFAULT_MAX_LEN = 50
_DEFAULT_MODEL_DIR = (
    Path(__file__).resolve().parents[2] / "deepdoc" / "resources" / "models" / "seal" / "trocr_seal_384"
)


@dataclass(frozen=True)
class SealRegion:
    bbox: tuple[int, int, int, int]
    crop: PILImage.Image
    detection_score: float


@dataclass(frozen=True)
class SealRecognitionResult:
    present: bool
    text: str = ""
    score: float = 0.0
    bbox: tuple[int, int, int, int] | None = None
    detection_score: float = 0.0
    engine: str = _DEFAULT_ENGINE
    region_count: int = 0
    seal_kind: str = "unknown"
    rank: float = 0.0


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=-1, keepdims=True)
    exp = np.exp(shifted)
    denom = np.sum(exp, axis=-1, keepdims=True)
    denom = np.maximum(denom, 1e-12)
    return exp / denom


def _normalize_pixel_values(image: np.ndarray) -> np.ndarray:
    arr = image.astype(np.float32) / 255.0
    arr = (arr - 0.5) / 0.5
    arr = np.transpose(arr, (2, 0, 1))
    return np.expand_dims(arr, axis=0).astype(np.float32)


def _load_vocab(vocab_path: Path) -> tuple[dict[str, int], dict[int, str]]:
    vocab = json.loads(vocab_path.read_text(encoding="utf-8"))
    vocab_inv = {int(idx): str(token) for token, idx in vocab.items()}
    return {str(k): int(v) for k, v in vocab.items()}, vocab_inv


class OnnxSealRecognizer:
    def __init__(
        self, model_dir: Path, *, threshold: float = _DEFAULT_THRESHOLD, max_len: int = _DEFAULT_MAX_LEN
    ) -> None:
        self._model_dir = model_dir
        self._threshold = float(threshold)
        self._max_len = max(1, int(max_len))
        providers = ort.get_available_providers() or ["CPUExecutionProvider"]
        self._encoder = ort.InferenceSession(str(model_dir / "encoder_model.onnx"), providers=providers)
        self._decoder = ort.InferenceSession(str(model_dir / "decoder_model.onnx"), providers=providers)
        self._vocab, self._vocab_inv = _load_vocab(model_dir / "vocab.json")
        self._start_id = int(self._vocab.get("<s>", 0))
        self._end_id = int(self._vocab.get("</s>", 2))
        self._pad_id = int(self._vocab.get("<pad>", 1))
        self._unk_id = int(self._vocab.get("<unk>", 3))
        self._decoder_input_names = {item.name for item in self._decoder.get_inputs()}

    def recognize(self, image: PILImage.Image) -> tuple[str, float]:
        rgb = np.asarray(image.convert("RGB").resize((384, 384), PILImage.Resampling.BILINEAR))
        pixel_values = _normalize_pixel_values(rgb)
        encoder_hidden_states = self._encoder.run(None, {"pixel_values": pixel_values})[0]

        ids = [self._start_id]
        mask = [1]
        scores: list[float] = []
        for _ in range(self._max_len):
            input_ids = np.asarray([ids], dtype=np.int64)
            attention_mask = np.asarray([mask], dtype=np.int64)
            decoder_inputs = {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
                "encoder_hidden_states": encoder_hidden_states,
            }
            decoder_inputs = {k: v for k, v in decoder_inputs.items() if k in self._decoder_input_names}
            logits = self._decoder.run(["logits"], decoder_inputs)[0][0]
            probs = _softmax(logits)
            next_id = int(np.argmax(probs[-1]))
            next_score = float(probs[-1, next_id])
            if next_id == self._end_id:
                break
            ids.append(next_id)
            mask.append(1)
            scores.append(next_score)

        avg_score = float(sum(scores) / len(scores)) if scores else 0.0
        if avg_score < self._threshold:
            return "", avg_score

        chars: list[str] = []
        for token_id in ids:
            if token_id in {self._start_id, self._end_id, self._pad_id, self._unk_id}:
                continue
            token = self._vocab_inv.get(int(token_id), "")
            if token:
                chars.append(token)
        return "".join(chars).strip(), avg_score


@lru_cache(maxsize=4)
def _get_recognizer(model_dir: str, threshold: float) -> OnnxSealRecognizer:
    return OnnxSealRecognizer(Path(model_dir), threshold=threshold)


def _has_required_model_files(path: Path) -> bool:
    required = [path / "encoder_model.onnx", path / "decoder_model.onnx", path / "vocab.json"]
    return all(p.exists() for p in required)


def _resolve_model_dir(model_dir: str | None = None) -> Path | None:
    explicit = str(model_dir or "").strip()
    if explicit:
        path = Path(explicit)
        return path if _has_required_model_files(path) else None

    configured = str(getattr(settings, "SEAL_RECOGNITION_MODEL_DIR", "") or "").strip()
    if configured:
        path = Path(configured)
        return path if _has_required_model_files(path) else None

    return _DEFAULT_MODEL_DIR if _has_required_model_files(_DEFAULT_MODEL_DIR) else None


def _expand_bbox(
    bbox: tuple[int, int, int, int], *, width: int, height: int, margin_ratio: float = 0.12
) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox
    bw = max(1, x1 - x0)
    bh = max(1, y1 - y0)
    mx = int(round(bw * margin_ratio))
    my = int(round(bh * margin_ratio))
    return (
        max(0, x0 - mx),
        max(0, y0 - my),
        min(width, x1 + mx),
        min(height, y1 + my),
    )


def _infer_seal_kind(bbox: tuple[int, int, int, int] | None) -> str:
    if bbox is None:
        return "unknown"
    x0, y0, x1, y1 = bbox
    width = max(1, int(x1) - int(x0))
    height = max(1, int(y1) - int(y0))
    aspect = width / float(height)
    if aspect >= 1.6 or aspect <= 0.6:
        return "seam_stamp"
    if 0.82 <= aspect <= 1.22:
        return "round_stamp"
    if 1.22 < aspect < 1.6:
        return "oval_stamp"
    return "unknown"


def _bbox_to_payload(bbox: tuple[int, int, int, int] | None) -> dict[str, int] | None:
    if bbox is None:
        return None
    x0, y0, x1, y1 = bbox
    return {
        "x0": int(x0),
        "y0": int(y0),
        "x1": int(x1),
        "y1": int(y1),
    }


def _serialize_seal_candidate(result: SealRecognitionResult) -> dict[str, Any]:
    return {
        "text": result.text,
        "score": float(result.score),
        "detection_score": float(result.detection_score),
        "engine": result.engine,
        "region_count": int(result.region_count),
        "seal_kind": result.seal_kind,
        "rank": float(result.rank),
        "bbox": _bbox_to_payload(result.bbox),
    }


def detect_seal_regions(image: PILImage.Image, *, max_regions: int | None = None) -> list[SealRegion]:
    rgb = np.asarray(image.convert("RGB"))
    if rgb.size == 0:
        return []

    height, width = rgb.shape[:2]
    image_area = max(1, width * height)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    lower_red_1 = np.array([0, 70, 40], dtype=np.uint8)
    upper_red_1 = np.array([15, 255, 255], dtype=np.uint8)
    lower_red_2 = np.array([160, 70, 40], dtype=np.uint8)
    upper_red_2 = np.array([180, 255, 255], dtype=np.uint8)
    mask = cv2.inRange(hsv, lower_red_1, upper_red_1) | cv2.inRange(hsv, lower_red_2, upper_red_2)
    kernel = np.ones((5, 5), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    regions: list[SealRegion] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= 0:
            continue
        area_ratio = area / float(image_area)
        if area_ratio < 0.0008 or area_ratio > 0.35:
            continue

        x, y, w, h = cv2.boundingRect(contour)
        if w <= 0 or h <= 0:
            continue
        aspect = w / float(h)
        if aspect < 0.45 or aspect > 2.2:
            continue

        rect_area = float(max(1, w * h))
        fill_ratio = area / rect_area
        perimeter = float(cv2.arcLength(contour, True))
        circularity = 0.0 if perimeter <= 0 else float(4.0 * math.pi * area / (perimeter * perimeter))
        if fill_ratio < 0.08 and circularity < 0.15:
            continue

        detection_score = max(
            0.0,
            min(
                1.0,
                0.45 * min(fill_ratio / 0.35, 1.0)
                + 0.35 * min(max(circularity, 0.0) / 0.75, 1.0)
                + 0.20 * min(area_ratio / 0.01, 1.0),
            ),
        )
        if detection_score <= 0.0:
            continue

        bbox = _expand_bbox((x, y, x + w, y + h), width=width, height=height)
        crop = image.crop(bbox)
        regions.append(SealRegion(bbox=bbox, crop=crop, detection_score=float(detection_score)))

    regions.sort(
        key=lambda item: (item.detection_score, (item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])),
        reverse=True,
    )
    limit = max(1, int(max_regions or getattr(settings, "SEAL_RECOGNITION_MAX_REGIONS_PER_PAGE", 3) or 3))
    return regions[:limit]


def _detect_and_recognize_seal_candidates(
    image: PILImage.Image,
    *,
    model_dir: str | None = None,
    threshold: float | None = None,
) -> tuple[list[SealRecognitionResult], int]:
    resolved_model_dir = _resolve_model_dir(model_dir)
    if resolved_model_dir is None:
        return [], 0

    threshold_value = float(
        threshold
        if threshold is not None
        else getattr(settings, "SEAL_RECOGNITION_THRESHOLD", _DEFAULT_THRESHOLD) or _DEFAULT_THRESHOLD
    )
    regions = detect_seal_regions(image)
    region_count = len(regions)
    if not regions:
        return [], 0

    recognizer = _get_recognizer(str(resolved_model_dir), threshold_value)
    matches: list[SealRecognitionResult] = []
    for region in regions:
        text, score = recognizer.recognize(region.crop)
        rank = float(score) * 0.7 + float(region.detection_score) * 0.3
        if not text:
            continue
        matches.append(
            SealRecognitionResult(
                present=True,
                text=text,
                score=float(score),
                bbox=region.bbox,
                detection_score=float(region.detection_score),
                engine=_DEFAULT_ENGINE,
                region_count=region_count,
                seal_kind=_infer_seal_kind(region.bbox),
                rank=float(rank),
            )
        )

    matches.sort(
        key=lambda item: (
            float(item.rank),
            float(item.score),
            float(item.detection_score),
            float((item.bbox[2] - item.bbox[0]) * (item.bbox[3] - item.bbox[1])) if item.bbox is not None else 0.0,
        ),
        reverse=True,
    )
    return matches, region_count


def detect_and_recognize_seal_candidates(
    image: PILImage.Image,
    *,
    model_dir: str | None = None,
    threshold: float | None = None,
) -> list[SealRecognitionResult]:
    matches, _region_count = _detect_and_recognize_seal_candidates(
        image,
        model_dir=model_dir,
        threshold=threshold,
    )
    return matches


def detect_and_recognize_seal(
    image: PILImage.Image,
    *,
    model_dir: str | None = None,
    threshold: float | None = None,
) -> SealRecognitionResult:
    matches, region_count = _detect_and_recognize_seal_candidates(
        image,
        model_dir=model_dir,
        threshold=threshold,
    )
    if matches:
        return matches[0]
    return SealRecognitionResult(present=False, region_count=region_count)


def extract_seal_documents_from_pdf(
    *,
    file_path: Path,
    source: str,
    parser_backend: str = "deepdoc",
) -> list[Document]:
    if not bool(getattr(settings, "SEAL_RECOGNITION_ENABLED", False)):
        return []
    if _resolve_model_dir() is None:
        return []

    try:
        import fitz  # PyMuPDF
    except Exception:
        return []

    dpi = max(72, int(getattr(settings, "SEAL_RECOGNITION_PDF_DPI", 144) or 144))
    max_pages = max(0, int(getattr(settings, "SEAL_RECOGNITION_MAX_PAGES", 0) or 0))
    scale = float(dpi) / 72.0
    docs: list[Document] = []

    pdf = fitz.open(str(file_path))
    try:
        page_count = int(getattr(pdf, "page_count", 0) or 0)
        limit = page_count if max_pages == 0 else min(page_count, max_pages)
        for page_index in range(limit):
            page = pdf.load_page(page_index)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            if pix.n not in (3, 4):
                pix = fitz.Pixmap(fitz.csRGB, pix)
            mode = "RGB" if pix.n == 3 else "RGBA"
            image = PILImage.frombytes(mode, [pix.width, pix.height], pix.samples)
            if mode == "RGBA":
                image = image.convert("RGB")
            candidates = detect_and_recognize_seal_candidates(image)
            if not candidates:
                continue
            result = candidates[0]
            bbox_list = [bbox for bbox in (_bbox_to_payload(item.bbox) for item in candidates) if bbox is not None]

            metadata: dict[str, Any] = {
                "source": source,
                "file_type": "pdf",
                "parser_backend": parser_backend,
                "doc_type_kwd": "seal",
                "element_kind": "seal",
                "element_text": result.text,
                "element_confidence": float(result.score),
                "content_type": "seal",
                "chunk_role": "seal",
                "page": page_index + 1,
                "page_number": page_index + 1,
                "seal_present": True,
                "seal_text": result.text,
                "seal_score": float(result.score),
                "seal_detection_score": float(result.detection_score),
                "seal_engine": result.engine,
                "seal_region_count": int(result.region_count),
                "seal_candidate_count": int(len(candidates)),
                "seal_kind": result.seal_kind,
                "seal_page_index": int(page_index),
                "element_page": int(page_index + 1),
                "seal_primary": _serialize_seal_candidate(result),
                "seal_candidates": [_serialize_seal_candidate(item) for item in candidates],
                "seal_bbox_list": bbox_list,
                "element_attributes": {
                    "source_content_type": "seal",
                    "source_doc_type": "seal",
                },
            }
            bbox_payload = _bbox_to_payload(result.bbox)
            if bbox_payload is not None:
                metadata["seal_bbox"] = bbox_payload
                metadata["element_bbox"] = dict(bbox_payload)
                metadata["element_attributes"]["bbox"] = dict(bbox_payload)
            metadata["element_attributes"]["page"] = int(page_index + 1)
            docs.append(Document(page_content=f"印章识别：{result.text}", metadata=metadata))
    finally:
        pdf.close()

    return docs


__all__ = [
    "SealRecognitionResult",
    "SealRegion",
    "detect_and_recognize_seal",
    "detect_and_recognize_seal_candidates",
    "detect_seal_regions",
    "extract_seal_documents_from_pdf",
]
