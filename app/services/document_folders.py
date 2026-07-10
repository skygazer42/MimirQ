"""
Folder-tree builder for document libraries.

This derives a folder hierarchy from document metadata `source_path` values
(directory-preserving upload keys like "folder/sub/file.pdf").
"""


from collections.abc import Iterable

from app.api.schemas.document_folders import DocumentFolderNode


def build_document_folder_tree(
    source_paths: Iterable[str | None],
    *,
    total_documents: int,
    max_depth: int = 20,
) -> DocumentFolderNode:
    """
    Build a folder tree with subtree document counts.

    Notes:
    - `total_documents` may include documents without `source_path`; those still count in the root.
    - Folder counts only include documents whose `source_path` contains at least one "/" segment.
    """
    max_depth_eff = max(1, int(max_depth or 0)) if int(max_depth or 0) else 20
    max_depth_eff = max(1, min(max_depth_eff, 50))

    root = DocumentFolderNode(name="", path="", depth=0, documents=max(0, int(total_documents or 0)), children=[])
    nodes_by_path: dict[str, DocumentFolderNode] = {"": root}

    for sp in source_paths:
        raw = str(sp or "").strip()
        if not raw:
            continue
        parts = [p for p in raw.split("/") if p]
        # Need at least one folder segment + filename.
        if len(parts) <= 1:
            continue

        folder_parts = parts[:-1]
        if len(folder_parts) > max_depth_eff:
            folder_parts = folder_parts[:max_depth_eff]

        parent_path = ""
        for idx, name in enumerate(folder_parts, start=1):
            path = f"{parent_path}/{name}" if parent_path else name
            node = nodes_by_path.get(path)
            if node is None:
                node = DocumentFolderNode(name=name, path=path, depth=idx, documents=0, children=[])
                nodes_by_path[path] = node
                nodes_by_path[parent_path].children.append(node)

            node.documents += 1
            parent_path = path

    _sort_tree(root)
    return root


def _sort_tree(node: DocumentFolderNode) -> None:
    node.children.sort(key=lambda c: (str(c.name or "").casefold(), str(c.path or "")))
    for c in node.children:
        _sort_tree(c)


__all__ = [
    "build_document_folder_tree",
]

