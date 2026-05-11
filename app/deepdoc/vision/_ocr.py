import logging
import os
import uuid

# Third-party libraries
import fitz  # PyMuPDF
import numpy as np
from huggingface_hub import hf_hub_download
from langchain_community.document_loaders import PyPDFLoader
from PIL import Image
from rapidocr_onnxruntime import RapidOCR
from tqdm import tqdm

from ..configs.settings import DATA_PARSER_DATA, MODEL_OCR_PATH

# from argparse import ArgumentParser

# ====== Absolute paths ======

# Global data pool
GLOBAL_DATA_POOL = {}


def get_global_state(identifier):
    """
    Fetch state information for the identifier from the global data pool.
    """
    return GLOBAL_DATA_POOL.get(identifier, {})


def pdf_contains_text(pdf_path: str) -> bool:
    """
    Detect whether a PDF contains selectable text.
    Returns True if more than 50% of pages contain text.
    """
    doc = fitz.open(pdf_path)
    try:
        total_pages = len(doc)
        if total_pages == 0:
            return False

        text_pages = 0
        for page_num in range(total_pages):
            page = doc.load_page(page_num)
            text = page.get_text()
            if text.strip():
                text_pages += 1

        text_ratio = text_pages / total_pages
        return text_ratio > 0.5
    finally:
        doc.close()


def _extract_text_pdf(pdf_file_path: str) -> str:
    """
    If the PDF is text-readable, use PyPDFLoader to extract text.
    """
    loader = PyPDFLoader(pdf_file_path)
    documents = loader.load()
    # Concatenate page text and return.
    return "\n\n".join(doc.page_content for doc in documents)


def _plain_text_loader(file_path: str) -> str:
    """
    Read and return contents from a plain text file.
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class OCRHandler2:
    """
    Main handler that runs OCR on PDFs or images using RapidOCR.
    """

    def __init__(self, det_threshold=0.3):
        """
        Initialize the OCR handler and store the threshold.
        The actual OCR engine loads on first use.
        """
        self._ocr_core = None
        self._threshold = det_threshold

    def _download_onnx_if_needed(self, engine_path: str):
        """
        Download det/rec ONNX models from Hugging Face if they are missing locally.
        Use subfolder="PP-OCRv4" to avoid extra directories.
        """
        logging.info("Local model files do not exist, starting download from Hugging Face...")

        # Download detection model (det)
        det_local_path = hf_hub_download(
            repo_id="SWHL/RapidOCR",
            subfolder="PP-OCRv4",  # Repository subfolder
            filename="ch_PP-OCRv4_det_infer.onnx",
            local_dir=engine_path,
        )

        # Download recognition model (rec)
        rec_local_path = hf_hub_download(
            repo_id="SWHL/RapidOCR",
            subfolder="PP-OCRv4",
            filename="ch_PP-OCRv4_rec_infer.onnx",
            local_dir=engine_path,
        )

        logging.info("Model files downloaded:\n%s\n%s", det_local_path, rec_local_path)

    def _lazy_load_ocr_engine(self):
        """
        Lazily load the OCR engine on first use.
        """
        logging.info("Initializing OCR engine (first call).")

        # Set absolute path to store under (MODEL_BASE)/SWHL/RapidOCR/PP-OCRv4.
        engine_path = os.path.join(MODEL_OCR_PATH, "PP-OCRv4")
        os.makedirs(engine_path, exist_ok=True)

        det_path = os.path.join(engine_path, "ch_PP-OCRv4_det_infer.onnx")
        rec_path = os.path.join(engine_path, "ch_PP-OCRv4_rec_infer.onnx")

        # Download if the local files are missing.
        if not os.path.exists(det_path) or not os.path.exists(rec_path):
            self._download_onnx_if_needed(engine_path)

        # Re-check download results.
        if not os.path.exists(det_path) or not os.path.exists(rec_path):
            raise FileNotFoundError(
                f"Model files missing, cannot find:\n{det_path}\n{rec_path}\n"
                "Please check automatic download or manually place model files."
            )

        self._ocr_core = RapidOCR(
            det_box_thresh=self._threshold,
            det_model_path=det_path,
            rec_model_path=rec_path
        )
        logging.info(f"OCR engine loaded, current threshold: {self._threshold}")

    def single_image_ocr(self, input_data):
        """
        Run OCR on a single image.

        :param input_data: image path, PIL.Image, or numpy.ndarray
        :return: recognized plain text
        """
        if self._ocr_core is None:
            self._lazy_load_ocr_engine()

        tmp_file_path = None
        try:
            if isinstance(input_data, str):
                img_path = input_data
            else:
                img_path = self._img_to_temp_file(input_data)
                tmp_file_path = img_path

            results, _ = self._ocr_core(img_path)
            if results:
                text_output = "\n".join([seg[1] for seg in results])
            else:
                text_output = ""
                logging.warning("OCR engine did not detect any text.")
            return text_output

        except Exception as ex:
            logging.error(f"OCR recognition failed: {str(ex)}")
            raise
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    def pdf_ocr_pipeline(self, pdf_path: str) -> str:
        """
        Run OCR on a PDF file. Optionally check for selectable text via pdf_contains_text.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Specified PDF file does not exist: {pdf_path}")

        # 1) Check whether selectable text exists.
        if pdf_contains_text(pdf_path):
            logging.info("PDF has selectable text, reading directly (langchain).")
            return _extract_text_pdf(pdf_path)

        # 2) Convert pages to images and OCR.
        pdf_filename = os.path.splitext(os.path.basename(pdf_path))[0]
        storage_dir = os.path.join(DATA_PARSER_DATA, 'pdf2txt', pdf_filename)
        os.makedirs(storage_dir, exist_ok=True)

        images_for_ocr = self._pdf_2_imgs(pdf_path, storage_dir)
        text_results = []
        for img in tqdm(images_for_ocr, desc='OCR on PDF pages', ncols=100):
            recognized = self.single_image_ocr(img)
            text_results.append(recognized)

        return "\n\n".join(text_results)

    def _pdf_2_imgs(self, pdf_file: str, out_dir: str):
        """
        Convert each PDF page to PNG and return the image paths.
        If already converted, read cached files.
        """
        img_dir = os.path.join(out_dir, 'page_imgs')
        results = []

        if not os.path.exists(img_dir):
            os.makedirs(img_dir)
            pdf_data = fitz.open(pdf_file)
            try:
                total_pages = pdf_data.page_count

                for idx in tqdm(range(total_pages), desc='Converting PDF to images', ncols=100):
                    page_obj = pdf_data[idx]
                    scale = fitz.Matrix(2, 2)
                    pix = page_obj.get_pixmap(matrix=scale, alpha=False)
                    img_name = os.path.join(img_dir, f'pg_{idx + 1}.png')
                    pix.save(img_name)
                    results.append(img_name)
            finally:
                pdf_data.close()
        else:
            existing_imgs = sorted(os.listdir(img_dir))
            results = [os.path.join(img_dir, fn) for fn in existing_imgs]

        return results

    def _img_to_temp_file(self, img_data) -> str:
        """
        Save a PIL.Image or numpy.ndarray to a temp file and return its path.
        """
        temp_dir = os.path.join(os.getcwd(), 'temp_imgs')
        os.makedirs(temp_dir, exist_ok=True)

        random_name = f"temp_img_{uuid.uuid4().hex[:8]}.png"
        save_path = os.path.join(temp_dir, random_name)

        if isinstance(img_data, Image.Image):
            img_data.save(save_path)
        elif isinstance(img_data, np.ndarray):
            Image.fromarray(img_data).save(save_path)
        else:
            raise TypeError("Unsupported image type: please provide path, PIL.Image, or numpy.ndarray.")

        return save_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pdf_file = r"/data/Langagent/resources/data/example/test1.pdf"
    ocr_handler = OCRHandler2(det_threshold=0.3)
    recognized_text = ocr_handler.pdf_ocr_pipeline(pdf_file)
    logging.info("=== OCR Results ===")
    logging.info("%s", recognized_text)
