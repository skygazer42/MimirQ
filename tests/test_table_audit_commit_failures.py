import logging
from uuid import uuid4

import pytest


class AuditSession:
    def __init__(self):
        self.rolled_back = False

    def add(self, item):
        pass

    def commit(self):
        raise RuntimeError("audit commit unavailable")

    def rollback(self):
        self.rolled_back = True


@pytest.mark.parametrize("operation", ["catalog_redaction", "table_query", "table_redaction"])
def test_audit_commit_failure_rolls_back_and_warns(operation, caplog):
    from app.api.v1 import dataset_tables, db_catalog

    db = AuditSession()
    args = dict(db=db, tenant_id=uuid4(), account_id="account", dataset_id=uuid4())
    with caplog.at_level(logging.WARNING):
        if operation == "catalog_redaction":
            db_catalog._audit_fls_redaction(**args, table_id=uuid4(), redacted_columns=["secret"])
        elif operation == "table_query":
            dataset_tables._audit_table_query(**args, table_id="table", sql="SELECT 1")
        else:
            dataset_tables._audit_fls_redaction(
                **args, source="preview", resource_type="dataset_table", resource_id="table"
            )

    assert db.rolled_back
    failures = [record for record in caplog.records if record.exc_info]
    assert failures, "audit persistence degradation must include the exception traceback"
    assert "audit" in failures[-1].message.lower()
