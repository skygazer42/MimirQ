import { describe, expect, it } from 'vitest'
import type { EnterpriseOntologyDefinitionView as Definition } from '@/types/enterprise-ontology'
import enMessages from '@/i18n/messages/en'
import {
  assetCategories,
  assetObjectId,
  bindingCoverage,
  emptyDefinition,
  getAssets,
  objectLinks,
} from './ontology-model'

const definition: Definition = {
  ...emptyDefinition(),
  ontology: 'maintenance',
  object_types: {
    equipment: { label: '设备', key: ['id'], properties: { id: 'string', name: 'string', status: 'string' } },
    order: { key: ['id'], properties: { id: 'string' } },
  },
  relations: { has_order: { from: 'equipment', to: 'order', cardinality: 'one_to_many' } },
  bindings: [
    {
      object_type: 'equipment',
      role: 'primary',
      asset_id: 'ops.equipment',
      identity_columns: ['asset_id'],
      columns: { id: 'asset_id', name: ' ' },
    },
    {
      object_type: 'equipment',
      role: 'enrichment',
      asset_id: 'ops.details',
      identity_columns: ['asset_id'],
      columns: { id: 'asset_id', status: { column: 'state' } },
    },
    {
      object_type: 'equipment',
      role: 'document_evidence',
      asset_id: 'docs',
      identity_columns: [],
      columns: { name: 'document_name' },
    },
  ],
  metrics: {
    equipment_count: {
      object_type: 'equipment',
      property: 'id',
      aggregate: 'count',
      timezone: 'UTC',
      before_observation: false,
    },
  },
  functions: {
    count_equipment: { metric: 'equipment_count', executor: 'metric', returns: 'number' },
    unrelated: { metric: 'missing', executor: 'metric', returns: 'number' },
  },
  actions: {
    close: { object_type: 'equipment', target: 'maintenance', parameters: {}, approval_required: true },
    inspect_order: { object_type: 'order', target: 'maintenance', parameters: {}, approval_required: false },
  },
  action_workflows: { repair: { actions: ['inspect_order', 'close'] }, other: { actions: ['inspect_order'] } },
  concepts: {
    passenger_support: {
      label: '特殊旅客保障',
      description: '申请与材料要求。',
      aliases: ['轮椅', '担架'],
      sources: ['policy-document-id'],
    },
  },
}

describe('ontology studio derived facts', () => {
  it('counts each mapped property once and excludes document evidence and blank mappings', () => {
    expect(bindingCoverage(definition, 'equipment')).toEqual({ covered: 2, total: 3, percent: 67 })
    expect(bindingCoverage(emptyDefinition(), '')).toEqual({ covered: 0, total: 0, percent: 0 })
    expect(
      bindingCoverage(
        { ...definition, bindings: definition.bindings.map((item) => ({ ...item, asset_id: '' })) },
        'equipment',
      ).covered,
    ).toBe(0)
  })

  it('follows function metric dependencies and any matching workflow step for the selected object', () => {
    const links = objectLinks(definition, 'equipment')
    expect(links.functions.map(([id]) => id)).toEqual(['count_equipment'])
    expect(links.actions.map(([id]) => id)).toEqual(['close'])
    expect(links.workflows.map(([id]) => id)).toEqual(['repair'])
    expect(links.relations.map(([id]) => id)).toEqual(['has_order'])
  })

  it('exposes configured concepts and their document-source bindings in the asset directory', () => {
    expect(getAssets(definition, 'concepts')).toEqual([
      { id: 'passenger_support', label: '特殊旅客保障', detail: '轮椅、担架' },
    ])
  })

  it('exposes all eleven real asset categories and counts bindings individually', () => {
    expect(assetCategories.map((item) => item.id)).toEqual([
      'object_types',
      'relations',
      'bindings',
      'metrics',
      'rules',
      'functions',
      'actions',
      'action_workflows',
      'document_metadata',
      'concepts',
      'document_templates',
    ])
    expect(getAssets(definition, 'bindings')).toHaveLength(3)
    expect(getAssets(definition, 'object_types')[0]).toEqual({ id: 'equipment', label: '设备' })
    expect(getAssets(definition, 'rules')).toEqual([])
  })

  it('keeps English navigation and command copy for the independent route', () => {
    expect(enMessages.Navbar.items.enterpriseOntology).toBe('Enterprise ontology')
    expect(enMessages.CommandMenu.modules.ontology.keywords).toContain('ontology')
  })

  it('keeps inspector facts bound to the selected asset owner', () => {
    expect(assetObjectId(definition, 'functions', 'count_equipment')).toBe('equipment')
    expect(assetObjectId(definition, 'actions', 'inspect_order')).toBe('order')
    expect(assetObjectId(definition, 'bindings', '0')).toBe('equipment')
    expect(assetObjectId(definition, 'document_templates', 'report')).toBeUndefined()
  })
})
