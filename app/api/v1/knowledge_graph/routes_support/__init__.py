"""Module-level helpers for ``app.api.v1.knowledge_graph.routes``.

This package exists to keep ``app/api/v1/knowledge_graph/routes.py`` at a maintainable
size. Responsibilities:

- ``common``: shared constants and the module logger.
- ``types``: request/query parameter models and dataclass containers.
- ``projection``: graph projection helpers (nodes/links/limits/pipeline scoping,
  document ACL resolution, and generic serialization/uuid utilities).
- ``merge_alias``: entity merge / alias suggestion helpers.
- ``undo``: merge/split resolution undo helpers (the routes stay in ``routes``).
- ``extraction``: KG extraction option/enqueue helpers (the routes stay in ``routes``).

Import direction: submodules may import from each other and from leaf modules
only -- they MUST NEVER import ``app.api.v1.knowledge_graph.routes`` (circular). The routes
module imports the helpers used by its endpoints directly from their owners.

This package intentionally does not re-export anything.
"""
