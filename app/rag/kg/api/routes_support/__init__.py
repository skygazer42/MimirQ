"""Module-level helpers split out of ``app.rag.kg.api.routes``.

This package exists to keep ``app/rag/kg/api/routes.py`` at a maintainable
size. Responsibilities:

- ``common``: shared constants and the module logger.
- ``schemas``: request/query parameter models and dataclass containers.
- ``projection``: graph projection helpers (nodes/links/limits/pipeline scoping,
  document ACL resolution, and generic serialization/uuid utilities).
- ``merge_alias``: entity merge / alias suggestion helpers.
- ``undo``: merge/split resolution undo helpers (the routes stay in ``routes``).
- ``extraction``: KG extraction option/enqueue helpers (the routes stay in ``routes``).

Import direction: submodules may import from each other and from leaf modules
only -- they MUST NEVER import ``app.rag.kg.api.routes`` (circular). The routes
module re-imports every name below, so existing references such as
``app.rag.kg.api.routes._scope_chunks_to_pipeline`` keep working unchanged.

This package intentionally does not re-export anything.
"""
