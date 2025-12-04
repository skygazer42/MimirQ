import logging
import os
import uuid

# 第三方库
import fitz  # PyMuPDF
import numpy as np
from PIL import Image
from huggingface_hub import hf_hub_download
from langchain_community.document_loaders import PyPDFLoader
from rapidocr_onnxruntime import RapidOCR
from tqdm import tqdm
from configs.settings import *

# from argparse import ArgumentParser

# ======  绝对路径 ======

# 全局数据池
GLOBAL_DATA_POOL = {}


def get_global_state(identifier):
    """
    从全局数据池中获取对应标识符的状态信息
    """
    return GLOBAL_DATA_POOL.get(identifier, {})


def pdf_contains_text(pdf_path: str) -> bool:
    """
    检测 PDF 是否包含可复制文本。
    超过 50% 的页面有文字就返回 True。
    """
    doc = fitz.open(pdf_path)
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


def _extract_text_pdf(pdf_file_path: str) -> str:
    """
    如果 PDF 可以直接读取文字，则使用 langchain 的 PyPDFLoader 提取文本。
    """
    loader = PyPDFLoader(pdf_file_path)
    documents = loader.load()
    # 将每个页面的文本拼接后返回
    return "\n\n".join(doc.page_content for doc in documents)


def _plain_text_loader(file_path: str) -> str:
    """
    从普通文本文件中读取并返回其内容。
    """
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


class OCRHandler2:
    """
    使用 RapidOCR 对 PDF 或图像执行 OCR 的主要处理类。
    """

    def __init__(self, det_threshold=0.3):
        """
        初始化 OCR 对象，只保存阈值。真正的 OCR 加载在第一次使用时完成。
        """
        self._ocr_core = None
        self._threshold = det_threshold

    def _download_onnx_if_needed(self, engine_path: str):
        """
        若本地不存在 det/rec ONNX 文件，则从 Hugging Face SWHL/RapidOCR 自动下载。
        采用 subfolder="PP-OCRv4" 避免多余目录。
        """
        logging.info("本地模型文件不存在，开始从 Hugging Face 下载...")

        # 下载检测模型 det
        det_local_path = hf_hub_download(
            repo_id="SWHL/RapidOCR",
            subfolder="PP-OCRv4",  # 仓库子目录
            filename="ch_PP-OCRv4_det_infer.onnx",
            local_dir=engine_path,
        )

        # 下载识别模型 rec
        rec_local_path = hf_hub_download(
            repo_id="SWHL/RapidOCR",
            subfolder="PP-OCRv4",
            filename="ch_PP-OCRv4_rec_infer.onnx",
            local_dir=engine_path,
        )

        logging.info("模型文件已下载:\n%s\n%s", det_local_path, rec_local_path)

    def _lazy_load_ocr_engine(self):
        """
        延迟加载 OCR 模型，仅在第一次需要时执行，后续直接复用。
        """
        logging.info("正在初始化 OCR 引擎（首次调用）。")

        # 设置绝对路径，存放到 (MODEL_BASE)/SWHL/RapidOCR/PP-OCRv4
        engine_path = os.path.join(MODEL_OCR_PATH, "PP-OCRv4")
        os.makedirs(engine_path, exist_ok=True)

        det_path = os.path.join(engine_path, "ch_PP-OCRv4_det_infer.onnx")
        rec_path = os.path.join(engine_path, "ch_PP-OCRv4_rec_infer.onnx")

        # 如果本地不存在这两个文件，则执行下载
        if not os.path.exists(det_path) or not os.path.exists(rec_path):
            self._download_onnx_if_needed(engine_path)

        # 再次检查下载结果
        if not os.path.exists(det_path) or not os.path.exists(rec_path):
            raise FileNotFoundError(
                f"模型文件缺失，无法找到:\n{det_path}\n{rec_path}\n"
                "请检查自动下载或手动放置模型文件。"
            )

        self._ocr_core = RapidOCR(
            det_box_thresh=self._threshold,
            det_model_path=det_path,
            rec_model_path=rec_path
        )
        logging.info(f"OCR 引擎加载完毕，当前阈值: {self._threshold}")

    def single_image_ocr(self, input_data):
        """
        对单张图像执行 OCR。
        :param input_data: 图像文件路径、PIL.Image 或 numpy.ndarray
        :return: 识别到的纯文本
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
                logging.warning("OCR 引擎未检测到任何文本。")
            return text_output

        except Exception as ex:
            logging.error(f"OCR 识别失败: {str(ex)}")
            raise
        finally:
            if tmp_file_path and os.path.exists(tmp_file_path):
                os.remove(tmp_file_path)

    def pdf_ocr_pipeline(self, pdf_path: str) -> str:
        """
        对 PDF文件执行 OCR。若想先检查可选文字，可加上 pdf_contains_text 判断。
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"指定的 PDF 文件不存在: {pdf_path}")

        # 1,先检查是否有可选文字
        if pdf_contains_text(pdf_path):
            logging.info("PDF 有可选文字，直接读取（langchain）。")
            return _extract_text_pdf(pdf_path)

        # 2.逐页转换图像再 OCR
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
        将 PDF 的每一页转换为 PNG 并返回这些图像的路径列表。
        如果已转换过，则直接读取缓存文件。
        """
        img_dir = os.path.join(out_dir, 'page_imgs')
        results = []

        if not os.path.exists(img_dir):
            os.makedirs(img_dir)
            pdf_data = fitz.open(pdf_file)
            total_pages = pdf_data.page_count

            for idx in tqdm(range(total_pages), desc='Converting PDF to images', ncols=100):
                page_obj = pdf_data[idx]
                scale = fitz.Matrix(2, 2)
                pix = page_obj.get_pixmap(matrix=scale, alpha=False)
                img_name = os.path.join(img_dir, f'pg_{idx + 1}.png')
                pix.save(img_name)
                results.append(img_name)
        else:
            existing_imgs = sorted(os.listdir(img_dir))
            results = [os.path.join(img_dir, fn) for fn in existing_imgs]

        return results

    def _img_to_temp_file(self, img_data) -> str:
        """
        将 PIL.Image 或 numpy.ndarray 存成临时文件，并返回其路径。
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
            raise TypeError("不支持的图像类型：请提供路径、PIL.Image 或 numpy.ndarray。")

        return save_path


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    pdf_file = r"/data/Langagent/resources/data/example/test1.pdf"
    ocr_handler = OCRHandler2(det_threshold=0.3)
    recognized_text = ocr_handler.pdf_ocr_pipeline(pdf_file)
    print("=== OCR 结果如下 ===")
    print(recognized_text)
