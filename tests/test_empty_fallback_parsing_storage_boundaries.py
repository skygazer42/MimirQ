import sys
from types import SimpleNamespace

import pytest
from PIL import Image

from app.parsing.enrich.image_understanding import _decode_with_opencv_qr
from app.parsing.utils.document_elements import normalize_document_elements
from app.storage.object.runtime import object_store_backend_config
from app.storage.vector.milvus import MilvusVectorStore


def test_embedding_space_failure_does_not_become_an_unscoped_hash(monkeypatch):
    import app.rag.embedding.utils as embedding_utils

    def unavailable_space_hash():
        raise RuntimeError("embedding space unavailable")

    monkeypatch.setattr(embedding_utils, "current_embedding_space_hash", unavailable_space_hash)

    with pytest.raises(RuntimeError, match="embedding space unavailable"):
        MilvusVectorStore._current_embedding_space_hash()


def test_object_store_description_failure_remains_observable():
    class BrokenStore:
        def describe_backend(self):
            raise RuntimeError("backend configuration unavailable")

    with pytest.raises(RuntimeError, match="backend configuration unavailable"):
        object_store_backend_config(BrokenStore())


def test_normalized_document_elements_require_page_content():
    with pytest.raises(KeyError, match="page_content"):
        normalize_document_elements([{"metadata": {}}])


@pytest.mark.parametrize("value", [0, False, None])
def test_normalized_document_elements_reject_non_text_page_content(value):
    with pytest.raises((AttributeError, TypeError)):
        normalize_document_elements([{"page_content": value, "metadata": {}}])


def test_normalized_image_keeps_text_when_optional_code_text_is_none():
    elements = normalize_document_elements([
        {"page_content": "QR image", "metadata": {"element_kind": "image", "element_attributes": {"visual_kind": "qr", "image_code_text": None}}}
    ])

    assert elements[0]["text"] == "QR image"


def test_qr_decoder_keeps_the_native_decoded_text(monkeypatch):
    detector = SimpleNamespace(detectAndDecode=lambda _image: ("decoded value", None, None))
    cv2 = SimpleNamespace(
        QRCodeDetector=lambda: detector,
        resize=lambda image, *args, **kwargs: image,
        INTER_NEAREST=0,
    )
    monkeypatch.setitem(sys.modules, "cv2", cv2)
    image = Image.new("RGB", (2, 2), "white")
    try:
        assert _decode_with_opencv_qr(image) == (["decoded value"], "qr")
    finally:
        image.close()
