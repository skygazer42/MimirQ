from app.services.db_catalog_schema_doc_service import compute_schema_diff, extract_schema_from_markdown


def test_extract_schema_from_markdown_parses_tables_and_columns():
    md = """# Virtual DB Schema

- dataset_id: `x`
- generated_at: `y`

## demo.users

### Columns

| ordinal | name | type | nullable | comment |
|---:|---|---|:---:|---|
| 1 | `id` | int | N |  |
| 2 | `email` | varchar | Y |  |

## demo.orders

### Columns

| ordinal | name | type | nullable | comment |
|---:|---|---|:---:|---|
| 1 | `id` | int | N |  |
| 2 | `user_id` | int | N |  |
"""

    schema = extract_schema_from_markdown(md)
    assert sorted(schema.keys()) == ["demo.orders", "demo.users"]
    assert schema["demo.users"]["columns"]["id"]["data_type"] == "int"
    assert schema["demo.users"]["columns"]["id"]["nullable"] is False
    assert schema["demo.users"]["columns"]["email"]["nullable"] is True


def test_compute_schema_diff_detects_added_removed_and_changed_columns():
    old_md = """# Virtual DB Schema

## demo.users

### Columns

| ordinal | name | type | nullable | comment |
|---:|---|---|:---:|---|
| 1 | `id` | int | N |  |
| 2 | `email` | varchar | Y |  |
"""
    new_md = """# Virtual DB Schema

## demo.users

### Columns

| ordinal | name | type | nullable | comment |
|---:|---|---|:---:|---|
| 1 | `id` | bigint | N |  |
| 3 | `created_at` | datetime | N |  |
"""

    diff = compute_schema_diff(
        old_schema=extract_schema_from_markdown(old_md),
        new_schema=extract_schema_from_markdown(new_md),
        max_items=50,
    )

    assert diff["tables_added"]["count"] == 0
    assert diff["tables_removed"]["count"] == 0

    assert diff["columns_added"]["count"] == 1
    assert "demo.users.created_at" in diff["columns_added"]["items"]

    assert diff["columns_removed"]["count"] == 1
    assert "demo.users.email" in diff["columns_removed"]["items"]

    assert diff["columns_changed"]["count"] == 1
    item = diff["columns_changed"]["items"][0]
    assert item["table"] == "demo.users"
    assert item["column"] == "id"
    assert item["old"]["data_type"] == "int"
    assert item["new"]["data_type"] == "bigint"

