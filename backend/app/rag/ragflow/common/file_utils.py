"""
File utilities for ragflow.
Integrated from third_party/ragflow/common/file_utils.py
"""
import os
from pathlib import Path

PROJECT_BASE = os.getenv("RAG_PROJECT_BASE") or os.getenv("RAG_DEPLOY_BASE")


def get_project_base_directory(*args):
    """Get the project base directory."""
    global PROJECT_BASE
    if PROJECT_BASE is None:
        PROJECT_BASE = str(Path(__file__).resolve().parents[4])  # app/rag/ragflow/common -> backend

    if args:
        return os.path.join(PROJECT_BASE, *args)
    return PROJECT_BASE


def traversal_files(base):
    """Traverse all files in a directory."""
    for root, ds, fs in os.walk(base):
        for f in fs:
            fullname = os.path.join(root, f)
            yield fullname
