"""
Document folder tree schemas (derived from document.metadata.source_path).
"""


from uuid import UUID

from pydantic import BaseModel, Field


class DocumentFolderNode(BaseModel):
    name: str = Field(..., description="Folder name (single path segment)")
    path: str = Field(..., description="Folder path from root (slash-separated, no leading slash)")
    depth: int = Field(default=0, ge=0, le=50, description="Folder depth (root=0)")
    documents: int = Field(default=0, ge=0, description="Document count in this subtree")
    children: list["DocumentFolderNode"] = Field(default_factory=list)


class DocumentFolderTreeResponse(BaseModel):
    dataset_id: UUID
    total_documents: int = 0
    total_with_source_path: int = 0
    root: DocumentFolderNode


DocumentFolderNode.model_rebuild()

