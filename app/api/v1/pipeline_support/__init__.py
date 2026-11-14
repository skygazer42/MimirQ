"""Domain helpers for the pipeline HTTP API.

Annotations, capability metadata, clean previews, governance profile imports,
and ingestion previews each have an explicit owning submodule. HTTP routes and
the import-time built-in snapshots remain in pipeline.py.

Submodules depend on their actual rule and data owners, never on the pipeline
route module. Required snapshot data is passed explicitly. This ordinary package
does not aggregate helpers or preserve private test patch names.
"""
