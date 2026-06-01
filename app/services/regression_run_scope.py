from __future__ import annotations

import logging
from collections.abc import Sequence
from uuid import UUID


class MissingCasesError(ValueError):
    pass


class DatasetMismatchError(ValueError):
    pass


def validate_case_ids_belong_to_dataset(
    *,
    dataset_id: UUID,
    case_ids: Sequence[UUID],
    rows: Sequence[tuple[UUID, UUID | None]],
) -> None:
    """
    Ensure all requested case_ids exist and belong to dataset_id.

    `rows` is typically a DB projection of (case_id, dataset_id).
    """
    if not case_ids:
        return

    ds_id = UUID(str(dataset_id))
    want = {UUID(str(x)) for x in case_ids if x is not None}
    found: dict[UUID, UUID | None] = {}
    for cid, case_ds in rows or []:
        try:
            key = UUID(str(cid))
        except Exception:
            logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if case_ds is None:
            found[key] = None
            continue
        try:
            found[key] = UUID(str(case_ds))
        except Exception:
            found[key] = None

    missing = want - set(found.keys())
    if missing:
        raise MissingCasesError("Some cases were not found")

    mismatched = [cid for cid, case_ds in found.items() if case_ds is None or case_ds != ds_id]
    if mismatched:
        raise DatasetMismatchError("Some cases do not belong to dataset_id")

