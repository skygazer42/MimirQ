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
  "name": "业务知识图谱",
  "import_id": "business_knowledge_v1",
  "dataset_name": "手动知识图谱",
  "replace_existing": false,
  "index_vectors": true,
  "entities": [
    {"key": "record:returns", "name": "退换货规则", "type": "KnowledgeRecord"},
    {"key": "policy:warranty", "name": "质保政策", "type": "Policy"},
    {"key": "team:support", "name": "客户支持团队", "type": "OwnerDomain"}
  ],
  "relations": [
    {
      "subject": "record:returns",
      "predicate": "depends_on_policy",
      "object": "policy:warranty",
      "evidence": "退换货处理需要先核对质保政策。",
      "source": "人工审核表第 8 行"
    },
    {
      "subject": "record:returns",
      "predicate": "owned_by",
      "object": "team:support"
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

Keep only high-confidence business graph rows in KG. Import stable structure
such as canonical records, owner domains, policies, process steps, contacts, and
URLs. Keep FAQ and long free-text policies in RAG documents unless a human has
approved explicit links to canonical business records.
