"""Compatibility shim (generated).

Do not edit directly; edit the canonical implementation under app/third_party/integrated_pipeline.
"""


from importlib import import_module as _import_module

_target = _import_module("app.third_party.integrated_pipeline.chunkers.laws")

def __getattr__(name: str):
    return getattr(_target, name)

def __dir__():
    return sorted(set(globals().keys()) | set(dir(_target)))
