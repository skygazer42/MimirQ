import type { GraphData, GraphLink, GraphNode } from './graph-parser'
import { toTrimmedPrimitiveString } from './primitive-text'

type JsonRecord = Record<string, unknown>

function isRecord(v: unknown): v is JsonRecord {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}

function isNonEmptyObject(v: unknown): v is JsonRecord {
  return isRecord(v) && Object.keys(v).length > 0
}

function truthyCount(obj: JsonRecord, prefix: string) {
  return Object.entries(obj).filter(([k, v]) => k.startsWith(prefix) && !!v).length
}

function withSummary(summary: Array<string>) {
  return summary.map((s) => String(s || '').trim()).filter(Boolean)
}

function formatInherit(value: unknown) {
  const s = toTrimmedPrimitiveString(value)
  return s || '(inherit)'
}

type NodeMeta = {
  kind: 'bundle' | 'group' | 'subgroup'
  configured?: boolean
  summary?: string[]
  json?: unknown
}

function makeNode(id: string, label: string, configured: boolean, json: unknown, summary: string[] = [], color?: string): GraphNode {
  return {
    id,
    label,
    color: color ?? (configured ? '#3b82f6' : '#cbd5e1'),
    meta: {
      kind: 'group',
      configured,
      summary,
      json,
    } satisfies NodeMeta,
  }
}

function makeLink(source: string, target: string, label?: string): GraphLink {
  return {
    source,
    target,
    label,
    meta: { kind: 'contains' },
  }
}

export function buildDatasetConfigGraph(config: object): GraphData {
  const cfg = isRecord(config) ? config : {}

  const nodes: GraphNode[] = [
    {
      id: 'bundle',
      label: 'Dataset Config',
      color: '#0ea5e9',
      meta: { kind: 'bundle', configured: true, json: cfg } satisfies NodeMeta,
    },
  ]
  const links: GraphLink[] = []

  const addGroup = (id: string, label: string, configured: boolean, json: unknown, summary: string[] = []) => {
    nodes.push(makeNode(id, label, configured, json, summary))
    links.push(makeLink('bundle', id))
  }

  const addSub = (id: string, label: string, configured: boolean, json: unknown, summary: string[] = []) => {
    nodes.push({
      id,
      label,
      color: configured ? '#10b981' : '#cbd5e1',
      meta: { kind: 'subgroup', configured, json, summary } satisfies NodeMeta,
    })
    links.push(makeLink('pipeline', id))
  }

  // Ingestion defaults
  const parserBackend = String(cfg.default_parser_backend || '')
  const chunkStrategy = String(cfg.default_chunk_strategy || '')
  addGroup(
    'ingestion_defaults',
    'Ingestion Defaults',
    !!(parserBackend.trim() || chunkStrategy.trim()),
    {
      default_parser_backend: cfg.default_parser_backend ?? null,
      default_chunk_strategy: cfg.default_chunk_strategy ?? null,
    },
    withSummary([`parser_backend: ${formatInherit(parserBackend)}`, `chunk_strategy: ${formatInherit(chunkStrategy)}`])
  )

  // Pipeline (and sub-blocks)
  const pipeline = isNonEmptyObject(cfg.pipeline) ? cfg.pipeline : null
  addGroup(
    'pipeline',
    'Pipeline',
    isNonEmptyObject(pipeline),
    pipeline,
    withSummary([pipeline ? `governance_enabled: ${String(!!pipeline.governance_enabled)}` : 'governance_enabled: (inherit)'])
  )

  if (isNonEmptyObject(pipeline)) {
    const govConfigured = truthyCount(pipeline, 'governance_') > 0
    if (govConfigured) {
      addSub(
        'pipeline_governance',
        'Governance',
        true,
        Object.fromEntries(Object.entries(pipeline).filter(([k]) => k.startsWith('governance_'))),
        withSummary([`rules: ${truthyCount(pipeline, 'governance_')}`])
      )
    }

    const chunkConfigured = ['chunk_size', 'chunk_overlap', 'chunk_merge_small_min_chars', 'chunk_strategy_params'].some((k) => pipeline[k] != null)
    if (chunkConfigured) {
      addSub('pipeline_chunking', 'Chunking', true, {
        chunk_size: pipeline.chunk_size ?? null,
        chunk_overlap: pipeline.chunk_overlap ?? null,
        chunk_merge_small_min_chars: pipeline.chunk_merge_small_min_chars ?? null,
        chunk_strategy_params: pipeline.chunk_strategy_params ?? null,
      })
    }

    const indexingConfigured = [
      'chunk_vector_enabled',
      'bm25_index_enabled',
      'kg_enabled',
      'event_vector_enabled',
      'entity_vector_enabled',
    ].some((k) => pipeline[k] != null)
    if (indexingConfigured) {
      addSub('pipeline_indexing', 'Indexing', true, {
        chunk_vector_enabled: pipeline.chunk_vector_enabled ?? null,
        bm25_index_enabled: pipeline.bm25_index_enabled ?? null,
        kg_enabled: pipeline.kg_enabled ?? null,
        event_vector_enabled: pipeline.event_vector_enabled ?? null,
        entity_vector_enabled: pipeline.entity_vector_enabled ?? null,
      })
    }

    const tablesConfigured = Object.keys(pipeline).some((k) => k.startsWith('table_store_') && pipeline[k] != null)
    if (tablesConfigured) {
      addSub(
        'pipeline_tables',
        'Tables / TAG',
        true,
        Object.fromEntries(Object.entries(pipeline).filter(([k]) => k.startsWith('table_store_')))
      )
    }
  }

  // Ingestion policy (keep high-level)
  const ingestionPolicy = isRecord(cfg.ingestion_policy) ? cfg.ingestion_policy : null
  const policyRules = Array.isArray(ingestionPolicy?.rules) ? ingestionPolicy.rules : null
  const policyRuleCount = policyRules?.length
  addGroup(
    'ingestion_policy',
    'Ingestion Policy',
    isNonEmptyObject(ingestionPolicy),
    ingestionPolicy,
    withSummary([typeof policyRuleCount === 'number' ? `rules: ${policyRuleCount}` : 'rules: (none)'])
  )

  // RAG defaults
  const ragDefaults = cfg.rag_defaults || null
  addGroup('rag_defaults', 'RAG Defaults', isNonEmptyObject(ragDefaults), ragDefaults)

  // Prompt defaults
  const promptDefaults = {
    default_prompt_template_id: cfg.default_prompt_template_id ?? null,
    default_prompt_template_key: cfg.default_prompt_template_key ?? null,
    default_prompt_ab_experiment_key: cfg.default_prompt_ab_experiment_key ?? null,
  }
  addGroup(
    'prompt_defaults',
    'Prompt Defaults',
    Object.values(promptDefaults).some((v) => v != null && String(v).trim()),
    promptDefaults
  )

  // Optional nodes (backend may include these even if web TS types don't yet)
  if (cfg.chunk_targets_v2 != null) {
    addGroup('chunk_targets', 'Chunk Targets', isNonEmptyObject(cfg.chunk_targets_v2), cfg.chunk_targets_v2)
  }
  if (cfg.fls_policy != null) {
    addGroup('fls_policy', 'FLS Policy', isNonEmptyObject(cfg.fls_policy), cfg.fls_policy)
  }

  return { nodes, links }
}
