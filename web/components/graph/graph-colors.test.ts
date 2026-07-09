import { describe, expect, it } from 'vitest'

import { buildTypeColorMap, resolveGraphTypeColor } from './graph-colors'

describe('graph entity colors', () => {
  it('assigns clearly separated semantic colors to common entity families', () => {
    const nodes = [
      { id: 'person-1', label: 'Alice', meta: { kind: 'entity', type: 'Person' } },
      { id: 'org-1', label: 'OpenAI', meta: { kind: 'entity', type: 'Organization' } },
      { id: 'loc-1', label: 'Shanghai', meta: { kind: 'entity', type: 'Location' } },
      { id: 'law-1', label: 'Regulation A', meta: { kind: 'entity', type: 'Regulation' } },
      { id: 'material-1', label: 'ID Card', meta: { kind: 'entity', type: 'Material' } },
    ]

    const colorMap = buildTypeColorMap(nodes)

    expect(colorMap.get('Person')).toBe('#f59e0b')
    expect(colorMap.get('Organization')).toBe('#2563eb')
    expect(colorMap.get('Location')).toBe('#10b981')
    expect(colorMap.get('Regulation')).toBe('#8b5cf6')
    expect(colorMap.get('Material')).toBe('#ef4444')
  })

  it('normalizes common aliases to the same semantic family color', () => {
    expect(resolveGraphTypeColor('Person')).toBe(resolveGraphTypeColor('人物'))
    expect(resolveGraphTypeColor('Organization')).toBe(resolveGraphTypeColor('机构'))
    expect(resolveGraphTypeColor('Location')).toBe(resolveGraphTypeColor('地区'))
    expect(resolveGraphTypeColor('Regulation')).toBe(resolveGraphTypeColor('政策法规'))
  })
})
