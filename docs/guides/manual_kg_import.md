# Manual KG Import

MimirQ supports importing a manually governed knowledge graph into the existing
KG tables. Domain-specific extraction and alignment should happen outside the
core application; MimirQ only validates, stores, scopes, queries, and rolls back
curated graph rows.

## Payload

Send JSON to `POST /api/v1/kg/imports/preview` for validation, then
`POST /api/v1/kg/imports` to write it.

```json
{
  "name": "常州政务事项图谱",
  "import_id": "changzhou_service_items_v1",
  "dataset_name": "手动知识图谱",
  "replace_existing": false,
  "index_vectors": true,
  "entities": [
    {"key": "service:permit", "name": "烟草专卖零售许可证新办", "type": "ServiceItem"},
    {"key": "material:id", "name": "身份证明", "type": "Material"},
    {"key": "district:cz", "name": "常州市", "type": "District"}
  ],
  "relations": [
    {
      "subject": "service:permit",
      "predicate": "requires_material",
      "object": "material:id",
      "evidence": "办理该事项需要提交身份证明。",
      "source": "人工审核表第 12 行"
    },
    {
      "subject": "service:permit",
      "predicate": "applicable_in",
      "object": "district:cz"
    }
  ]
}
```

The graph page also accepts `.json` and `.jsonl` files from **图谱工具 -> 导入KG**.
JSONL rows can use `kind: "entity"` or `kind: "relation"`; relation rows are
also detected when they contain `subject`, `predicate`, and `object`.

## Storage Model

Each import creates one completed synthetic document and chunks for provenance.
The import is scoped by `manual_kg_import_id` and `pipeline_hash`, so existing
KG graph, stats, search, and GraphML export APIs continue to work.

By default, imports also embed KG events and entities, persist vectors on
`KgSourceEvent.content_vector` / `KgEntity.vector`, and write them to the
existing `kg_events` / `kg_entities` vector collections. Vector indexing is
fail-open: if the embedding provider or vector store is temporarily unavailable,
the governed KG rows are still committed, the API response returns
`vector_index.status`, and the document metadata records the same `vector_index`
status. Set `index_vectors: false` for offline/import-only runs.

Use `GET /api/v1/kg/imports` to list import batches and
`DELETE /api/v1/kg/imports/{import_id}` to roll back a batch.

## Recommended Governance

Keep only high-confidence business graph rows in KG. For government-service
data, import stable service-item structure such as item, region, level, material,
process step, phone, and online URL. Keep FAQ and long free-text laws in RAG
documents unless a human has approved explicit links to canonical service items.
