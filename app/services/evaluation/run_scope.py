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

    want = set(case_ids)
    found = dict(rows)
    missing = want - set(found.keys())
    if missing:
        raise MissingCasesError("Some cases were not found")

    if any(case_ds != dataset_id for case_ds in found.values()):
        raise DatasetMismatchError("Some cases do not belong to dataset_id")
