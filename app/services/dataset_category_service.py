"""
Dataset category service.

Provides:
- CRUD operations for tenant-scoped dataset categories (tree)
- Move operation with cycle guard
- Pure helpers for building trees (unit-testable)
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.api.schemas.dataset_category import DatasetCategoryNode
from app.core.constants import UserRoles
from app.models.dataset_category import DatasetCategory, DatasetCategoryMembership
from app.services.dataset_service import DatasetService
from app.rag.core.logging import get_logger

_EDIT_ROLES = UserRoles.EDIT_ROLES


def _assert_can_edit(db: Session, tenant_id: UUID, account_id: str) -> None:
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = str(getattr(member, "role", "") or "").lower()
    if role not in _EDIT_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No permission to manage dataset categories")


def _get_item_field(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


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


def build_category_tree_nodes(items: Iterable[Any]) -> list[DatasetCategoryNode]:
    """
    Build a sorted category tree from items that look like:
      {id, name, parent_id, sort_order}
    or SQLAlchemy DatasetCategory rows with the same attributes.
    """
    nodes_by_id: dict[UUID, DatasetCategoryNode] = {}
    parent_by_id: dict[UUID, UUID | None] = {}

    for it in items:
        cid = _get_item_field(it, "id")
        if cid is None:
            continue
        cid = UUID(str(cid))
        name = str(_get_item_field(it, "name", "") or "").strip() or "untitled"
        parent_id = _get_item_field(it, "parent_id", None)
        parent_uuid = UUID(str(parent_id)) if parent_id else None
        sort_order = int(_get_item_field(it, "sort_order", 0) or 0)

        parent_by_id[cid] = parent_uuid
        nodes_by_id[cid] = DatasetCategoryNode(
            id=cid,
            name=name,
            parent_id=parent_uuid,
            sort_order=sort_order,
            depth=0,
            datasets=int(_get_item_field(it, "datasets", 0) or 0),
            children=[],
        )

    roots: list[DatasetCategoryNode] = []
    for cid, node in nodes_by_id.items():
        pid = parent_by_id.get(cid)
        if pid and pid in nodes_by_id:
            nodes_by_id[pid].children.append(node)
        else:
            roots.append(node)

    def sort_and_set_depth(node: DatasetCategoryNode) -> None:
        node.children.sort(key=lambda c: (int(c.sort_order or 0), str(c.name or "").casefold(), str(c.id)))
        for child in node.children:
            child.depth = int(node.depth or 0) + 1
            sort_and_set_depth(child)

    roots.sort(key=lambda c: (int(c.sort_order or 0), str(c.name or "").casefold(), str(c.id)))
    for r in roots:
        r.depth = 0
        sort_and_set_depth(r)

    return roots


def collect_descendant_ids(*, root_id: UUID, parent_by_id: dict[UUID, UUID | None]) -> set[UUID]:
    """
    Expand a category id to include its descendants (including itself).

    Uses a parent mapping to build a children adjacency list.
    """
    from collections import defaultdict

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


class DatasetCategoryService:
    @staticmethod
    def get_category(db: Session, *, tenant_id: UUID, category_id: UUID) -> DatasetCategory:
        row = (
            db.query(DatasetCategory)
            .filter(DatasetCategory.tenant_id == tenant_id, DatasetCategory.id == category_id)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
        return row

    @staticmethod
    def list_tree(db: Session, *, tenant_id: UUID, account_id: str) -> list[DatasetCategoryNode]:
        DatasetService.ensure_member(db, tenant_id, account_id)
        rows = (
            db.query(DatasetCategory)
            .filter(DatasetCategory.tenant_id == tenant_id)
            .order_by(DatasetCategory.sort_order.asc(), DatasetCategory.name.asc())
            .all()
        )
        return build_category_tree_nodes(rows)

    @staticmethod
    def create(
        db: Session,
        *,
        tenant_id: UUID,
        account_id: str,
        name: str,
        parent_id: UUID | None = None,
        sort_order: int | None = None,
    ) -> DatasetCategory:
        _assert_can_edit(db, tenant_id, account_id)
        parent = None
        if parent_id is not None:
            parent = DatasetCategoryService.get_category(db, tenant_id=tenant_id, category_id=parent_id)

        row = DatasetCategory(
            tenant_id=tenant_id,
            name=str(name or "").strip() or "untitled",
            parent_id=parent.id if parent is not None else None,
            sort_order=int(sort_order or 0),
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def update(
        db: Session,
        *,
        tenant_id: UUID,
        account_id: str,
        category_id: UUID,
        name: str | None = None,
        sort_order: int | None = None,
    ) -> DatasetCategory:
        _assert_can_edit(db, tenant_id, account_id)
        row = DatasetCategoryService.get_category(db, tenant_id=tenant_id, category_id=category_id)

        if name is not None:
            row.name = str(name or "").strip() or "untitled"
        if sort_order is not None:
            row.sort_order = int(sort_order or 0)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def delete(db: Session, *, tenant_id: UUID, account_id: str, category_id: UUID) -> None:
        _assert_can_edit(db, tenant_id, account_id)
        row = DatasetCategoryService.get_category(db, tenant_id=tenant_id, category_id=category_id)

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

    @staticmethod
    def move(
        db: Session,
        *,
        tenant_id: UUID,
        account_id: str,
        category_id: UUID,
        parent_id: UUID | None = None,
        sort_order: int | None = None,
    ) -> DatasetCategory:
        _assert_can_edit(db, tenant_id, account_id)
        row = DatasetCategoryService.get_category(db, tenant_id=tenant_id, category_id=category_id)

        # Resolve and validate parent (same tenant).
        parent = None
        if parent_id is not None:
            parent = DatasetCategoryService.get_category(db, tenant_id=tenant_id, category_id=parent_id)

        # Cycle guard: load parent links for tenant once.
        parent_by_id: dict[UUID, UUID | None] = {
            UUID(str(cid)): (UUID(str(pid)) if pid else None)
            for cid, pid in db.query(DatasetCategory.id, DatasetCategory.parent_id)
            .filter(DatasetCategory.tenant_id == tenant_id)
            .all()
        }
        if would_create_cycle(category_id=row.id, new_parent_id=parent.id if parent else None, parent_by_id=parent_by_id):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid parent: cycle detected")

        row.parent_id = parent.id if parent is not None else None
        if sort_order is not None:
            row.sort_order = int(sort_order or 0)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def list_dataset_category_ids(db: Session, *, tenant_id: UUID, account_id: str, dataset_id: UUID) -> list[UUID]:
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)

        rows = (
            db.query(DatasetCategoryMembership.category_id)
            .filter(
                DatasetCategoryMembership.tenant_id == tenant_id,
                DatasetCategoryMembership.dataset_id == dataset_id,
            )
            .all()
        )
        out: list[UUID] = []
        seen: set[UUID] = set()
        for (cid,) in rows:
            if cid is None:
                continue
            if cid in seen:
                continue
            seen.add(cid)
            out.append(cid)
        out.sort(key=lambda x: str(x))
        return out

    @staticmethod
    def set_dataset_categories(
        db: Session,
        *,
        tenant_id: UUID,
        account_id: str,
        dataset_id: UUID,
        category_ids: list[UUID],
    ) -> list[UUID]:
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

        normalized: list[UUID] = []
        seen: set[UUID] = set()
        for cid in category_ids or []:
            try:
                cid2 = UUID(str(cid))
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue
            if cid2 in seen:
                continue
            seen.add(cid2)
            normalized.append(cid2)

        if normalized:
            rows = (
                db.query(DatasetCategory.id)
                .filter(DatasetCategory.tenant_id == tenant_id, DatasetCategory.id.in_(normalized))
                .all()
            )
            found = {r[0] for r in rows}
            missing = [str(cid) for cid in normalized if cid not in found]
            if missing:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unknown category id(s): {', '.join(missing)}")

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
        return sorted(normalized, key=lambda x: str(x))


__all__ = [
    "DatasetCategoryService",
    "build_category_tree_nodes",
    "collect_descendant_ids",
    "would_create_cycle",
]
