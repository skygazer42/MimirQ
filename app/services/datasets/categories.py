"""Tenant-scoped dataset category trees, mutations, and assignments."""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import app.services.datasets.management as dataset_service
from app.api.schemas.datasets import DatasetCategoryNode, DatasetCategoryTreeResponse
from app.infrastructure.security.roles import UserRoles
from app.models.datasets.records import DatasetCategory, DatasetCategoryMembership

_EDIT_ROLES = UserRoles.EDIT_ROLES


def _assert_can_edit(db: Session, tenant_id: UUID, account_id: str) -> None:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    role = member.role.lower()
    if role not in _EDIT_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to manage dataset categories")


def would_create_cycle(*, category_id: UUID, new_parent_id: UUID | None, parent_by_id: dict[UUID, UUID | None]) -> bool:
    """
    Return True if setting `category.parent_id = new_parent_id` would create a cycle.

    This assumes `parent_by_id` maps category_id -> parent_id for the tenant.
    """
    if new_parent_id is None:
        return False
    if new_parent_id == category_id:
        return True

    seen: set[UUID] = set()
    cur: UUID | None = new_parent_id
    while cur is not None:
        if cur == category_id:
            return True
        if cur in seen:
            # Existing cycle in the tree; be conservative and block the move.
            return True
        seen.add(cur)
        cur = parent_by_id.get(cur)
    return False


def build_category_tree_nodes(items: Iterable[DatasetCategory]) -> list[DatasetCategoryNode]:
    """Build a tree from category rows, ordered by position, name, and ID."""
    nodes_by_id = {
        category.id: DatasetCategoryNode(
            id=category.id,
            name=category.name,
            parent_id=category.parent_id,
            sort_order=category.sort_order,
        )
        for category in items
    }

    roots: list[DatasetCategoryNode] = []
    for node in nodes_by_id.values():
        if node.parent_id in nodes_by_id:
            nodes_by_id[node.parent_id].children.append(node)
        else:
            roots.append(node)

    def sort_and_set_depth(nodes: list[DatasetCategoryNode], depth: int) -> None:
        nodes.sort(key=lambda node: (node.sort_order, node.name.casefold(), str(node.id)))
        for node in nodes:
            node.depth = depth
            sort_and_set_depth(node.children, depth + 1)

    sort_and_set_depth(roots, 0)
    return roots


def collect_descendant_ids(*, root_id: UUID, parent_by_id: dict[UUID, UUID | None]) -> set[UUID]:
    """
    Expand a category id to include its descendants (including itself).

    Uses a parent mapping to build a children adjacency list.
    """
    children_by_parent: dict[UUID | None, list[UUID]] = defaultdict(list)
    for cid, pid in parent_by_id.items():
        children_by_parent[pid].append(cid)

    out: set[UUID] = set()
    stack: list[UUID] = [root_id]
    while stack:
        cur = stack.pop()
        if cur in out:
            continue
        out.add(cur)
        stack.extend(children_by_parent.get(cur, []))
    return out


def get_category(db: Session, *, tenant_id: UUID, category_id: UUID) -> DatasetCategory:
    row = (
        db.query(DatasetCategory)
        .filter(DatasetCategory.tenant_id == tenant_id, DatasetCategory.id == category_id)
        .first()
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return row


def list_tree(db: Session, *, tenant_id: UUID, account_id: str) -> DatasetCategoryTreeResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)
    rows = (
        db.query(DatasetCategory)
        .filter(DatasetCategory.tenant_id == tenant_id)
        .order_by(DatasetCategory.sort_order.asc(), DatasetCategory.name.asc())
        .all()
    )
    return DatasetCategoryTreeResponse(total=len(rows), items=build_category_tree_nodes(rows))


def create_category(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    name: str,
    parent_id: UUID | None = None,
    sort_order: int | None = None,
) -> DatasetCategory:
    _assert_can_edit(db, tenant_id, account_id)
    if parent_id is not None:
        get_category(db, tenant_id=tenant_id, category_id=parent_id)

    row = DatasetCategory(
        tenant_id=tenant_id,
        name=name.strip() or "untitled",
        parent_id=parent_id,
        sort_order=0 if sort_order is None else sort_order,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_category(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    category_id: UUID,
    name: str | None = None,
    sort_order: int | None = None,
) -> DatasetCategory:
    _assert_can_edit(db, tenant_id, account_id)
    row = get_category(db, tenant_id=tenant_id, category_id=category_id)

    if name is not None:
        row.name = name.strip() or "untitled"
    if sort_order is not None:
        row.sort_order = sort_order
    db.commit()
    db.refresh(row)
    return row


def delete_category(db: Session, *, tenant_id: UUID, account_id: str, category_id: UUID) -> None:
    _assert_can_edit(db, tenant_id, account_id)
    row = get_category(db, tenant_id=tenant_id, category_id=category_id)

    # Conservative: refuse deleting non-leaf nodes to avoid accidental cascades.
    has_child = (
        db.query(DatasetCategory.id)
        .filter(DatasetCategory.tenant_id == tenant_id, DatasetCategory.parent_id == row.id)
        .first()
        is not None
    )
    if has_child:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Category not empty")

    db.delete(row)
    db.commit()


def move_category(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    category_id: UUID,
    parent_id: UUID | None = None,
    sort_order: int | None = None,
) -> DatasetCategory:
    _assert_can_edit(db, tenant_id, account_id)
    row = get_category(db, tenant_id=tenant_id, category_id=category_id)

    if parent_id is not None:
        get_category(db, tenant_id=tenant_id, category_id=parent_id)

    # Cycle guard: load parent links for tenant once.
    parent_by_id: dict[UUID, UUID | None] = {
        cid: pid
        for cid, pid in db.query(DatasetCategory.id, DatasetCategory.parent_id)
        .filter(DatasetCategory.tenant_id == tenant_id)
        .all()
    }
    if would_create_cycle(category_id=row.id, new_parent_id=parent_id, parent_by_id=parent_by_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent: cycle detected")

    row.parent_id = parent_id
    if sort_order is not None:
        row.sort_order = sort_order
    db.commit()
    db.refresh(row)
    return row


def list_dataset_category_ids(db: Session, *, tenant_id: UUID, account_id: str, dataset_id: UUID) -> list[UUID]:
    ds = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    rows = (
        db.query(DatasetCategoryMembership.category_id)
        .filter(
            DatasetCategoryMembership.tenant_id == tenant_id,
            DatasetCategoryMembership.dataset_id == dataset_id,
        )
        .all()
    )
    return sorted([cid for (cid,) in rows], key=str)


def set_dataset_categories(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    category_ids: list[UUID],
) -> list[UUID]:
    ds = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_writable(db, ds, account_id)

    normalized = list(dict.fromkeys(category_ids))

    if normalized:
        rows = (
            db.query(DatasetCategory.id)
            .filter(DatasetCategory.tenant_id == tenant_id, DatasetCategory.id.in_(normalized))
            .all()
        )
        found = {r[0] for r in rows}
        missing = [str(cid) for cid in normalized if cid not in found]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown category id(s): {', '.join(missing)}"
            )

    # Replace assignment.
    db.query(DatasetCategoryMembership).filter(
        DatasetCategoryMembership.tenant_id == tenant_id,
        DatasetCategoryMembership.dataset_id == dataset_id,
    ).delete(synchronize_session=False)

    if normalized:
        db.add_all(
            [
                DatasetCategoryMembership(
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    category_id=cid,
                )
                for cid in normalized
            ]
        )
    db.commit()
    return sorted(normalized, key=str)


__all__ = [
    "build_category_tree_nodes",
    "collect_descendant_ids",
    "create_category",
    "delete_category",
    "get_category",
    "list_dataset_category_ids",
    "list_tree",
    "move_category",
    "set_dataset_categories",
    "update_category",
    "would_create_cycle",
]
