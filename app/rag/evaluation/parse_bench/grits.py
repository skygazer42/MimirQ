"""
Lightweight parse-bench GriTS proxy.

This module keeps the plan-facing parse_bench path while reusing the shared
dependency-free scorer from parsing quality helpers.
"""

from app.parsing.quality.grits import compute_table_collection_grits, compute_table_grits

__all__ = ["compute_table_collection_grits", "compute_table_grits"]
