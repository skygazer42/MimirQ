"""Capability discovery for parser exports and backend families."""


from typing import Any

from app.parsing.backends import normalize_parser_backend
from app.parsing.parsers.registry import (
    get_parser_backend_family,
    get_parser_export,
    iter_parser_backend_families,
    iter_parser_exports,
)


def get_parser_capabilities() -> tuple[object, ...]:
    return iter_parser_exports()


def get_parser_capability(name: str):
    return get_parser_export(name)


def get_parser_backend_capabilities(backend: str | None) -> dict[str, Any]:
    requested = str(backend or "").strip().lower() or "auto"
    normalized = normalize_parser_backend(requested) or requested
    family = get_parser_backend_family(normalized)
    if family is None:
        return {
            "requested_backend": requested,
            "resolved_backend": None,
            "aliases": [],
            "tier": "experimental",
            "category": "unknown",
            "supports_pdf": False,
            "supports_non_pdf": False,
            "user_selectable": False,
            "implicit_only": False,
            "default": False,
            "optional": False,
            "experimental": True,
            "lazy_modules": [],
        }
    return {
        "requested_backend": requested,
        "resolved_backend": family.canonical_name,
        "aliases": list(family.aliases),
        "tier": family.tier,
        "category": family.category,
        "supports_pdf": family.supports_pdf,
        "supports_non_pdf": family.supports_non_pdf,
        "user_selectable": family.user_selectable,
        "implicit_only": family.implicit_only,
        "default": family.tier == "default",
        "optional": family.tier == "optional",
        "experimental": family.tier == "experimental",
        "lazy_modules": list(family.lazy_modules),
        **({"non_pdf_extensions": list(family.non_pdf_extensions)} if family.non_pdf_extensions else {}),
    }


def list_parser_backend_capabilities(*, include_implicit: bool = True) -> list[dict[str, Any]]:
    return [
        {
            "resolved_backend": family.canonical_name,
            "aliases": list(family.aliases),
            "tier": family.tier,
            "category": family.category,
            "supports_pdf": family.supports_pdf,
            "supports_non_pdf": family.supports_non_pdf,
            "user_selectable": family.user_selectable,
            "implicit_only": family.implicit_only,
            "default": family.tier == "default",
            "optional": family.tier == "optional",
            "experimental": family.tier == "experimental",
            "lazy_modules": list(family.lazy_modules),
            **({"non_pdf_extensions": list(family.non_pdf_extensions)} if family.non_pdf_extensions else {}),
        }
        for family in iter_parser_backend_families(include_implicit=include_implicit)
    ]


__all__ = [
    "get_parser_backend_capabilities",
    "get_parser_capabilities",
    "get_parser_capability",
    "list_parser_backend_capabilities",
]
