"""Support subpackage for the Dify external knowledge adapter.

Pure helper functions and constants mechanically extracted from
`app.api.v1.integrations_dify`. The parent module re-imports every name
defined here, so monkeypatching and external imports keep working through
the original module path.

Submodules MUST NOT import `app.api.v1.integrations_dify` (directly or
indirectly): the parent module imports this subpackage, and helpers here
must never resolve names through the parent module globals.
"""
