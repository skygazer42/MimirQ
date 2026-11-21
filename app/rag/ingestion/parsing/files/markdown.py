"""Markdown file parsing adapter used by raw-file ingestion."""

from .general import Markdown

parse_markdown_sections = Markdown

__all__ = ["Markdown", "parse_markdown_sections"]
