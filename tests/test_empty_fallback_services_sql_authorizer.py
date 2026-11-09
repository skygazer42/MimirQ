import sqlite3

from app.services.table_store_service import _apply_sqlite_readonly_authorizer


def test_sqlite_read_without_a_table_identity_is_denied():
    class Connection:
        callback = None

        def set_authorizer(self, callback):
            self.callback = callback

    connection = Connection()
    _apply_sqlite_readonly_authorizer(connection, allowed_tables={"sheet_0"})
    assert connection.callback(sqlite3.SQLITE_READ, None, "value", "main", None) == sqlite3.SQLITE_DENY
    assert connection.callback(sqlite3.SQLITE_READ, "sheet_0", "value", "main", None) == sqlite3.SQLITE_OK
