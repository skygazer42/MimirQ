"""
MinerU PDF 解析器（高级）

支持两种模式：
1. MinerU 在线 API：https://mineru.net（需要 MINERU_API_TOKEN）
2. MinerU 本地服务：返回 ZIP 包含 Markdown + images（需要 MINERU_LOCAL_SERVER_URL）

支持：
- 表格识别和提取
- 图片识别和描述（自动上传到 MinIO）
- 公式识别
- 复杂版面分析
"""
from pathlib import Path
from typing import List, Optional
from uuid import UUID

from langchain_core.documents import Document

from app.services.mineru_service import mineru_service
from app.core.config import settings


class MinerUParser:
    """
    MinerU 高级 PDF 解析器

    使用 MinerU 进行 PDF 解析，相比 PyMuPDF 提供更强大的功能：
    - 表格结构化提取
    - 图片内容理解
    - 数学公式识别
    - 复杂排版处理
    """

    def __init__(self):
        self.dataset_id: Optional[str] = None
        self.document_id: Optional[str] = None

    def parse(
        self,
        file_path: Path,
        dataset_id: Optional[str] = None,
        document_id: Optional[str] = None
    ) -> List[Document]:
        """
        使用 MinerU 解析 PDF 文档。
        
        自动检测模式：
        - 如果配置了 MINERU_LOCAL_SERVER_URL → 使用本地服务（返回 ZIP）
        - 否则使用在线 API（需要 MINERU_API_TOKEN）

        Args:
            file_path: PDF 文件路径
            dataset_id: 知识库 ID（本地模式需要，用于 MinIO 上传）
            document_id: 文档 ID（本地模式需要，用于 MinIO 上传）

        Returns:
            LangChain Document 列表（通常返回单个文档，内容为 Markdown 格式）
        """
        if not mineru_service.enabled:
            raise Exception(
                "MinerU parser is not enabled. "
                "Please set MINERU_ENABLED=True and configure MINERU_API_TOKEN (online) "
                "or MINERU_LOCAL_SERVER_URL (local ZIP mode) in .env file."
            )

        # 检测模式：本地服务优先
        if mineru_service.local_server_url:
            print("[MinerU] 使用本地服务模式（ZIP + MinIO）")
            
            # 本地模式需要 dataset_id 和 document_id 用于 MinIO 上传
            if not dataset_id or not document_id:
                # 使用默认值
                dataset_id = dataset_id or str(UUID('00000000-0000-0000-0000-000000000000'))
                document_id = document_id or file_path.stem
            
            return mineru_service.parse_file_local(
                file_path=file_path,
                dataset_id=dataset_id,
                document_id=document_id
            )
        else:
            print("[MinerU] 使用在线 API 模式")
            return mineru_service.parse_file(file_path)
