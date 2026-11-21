"""Shared account roles and authorization role groups."""


class UserRoles:
    """User role constants."""

    OWNER = "owner"
    ADMIN = "admin"
    AUDITOR = "auditor"
    EDITOR = "editor"
    DATASET_OPERATOR = "dataset_operator"
    VIEWER = "viewer"

    # Editable roles
    EDIT_ROLES: frozenset[str] = frozenset({OWNER, ADMIN, EDITOR, DATASET_OPERATOR})

    # Admin roles
    ADMIN_ROLES: frozenset[str] = frozenset({OWNER, ADMIN})
