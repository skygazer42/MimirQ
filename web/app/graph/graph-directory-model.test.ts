import { describe, expect, it } from 'vitest'
import type { GraphData } from '@/lib/graph-parser'
import { buildDirectoryIndex, getNeighborhood, searchDirectory } from './graph-directory-model'

const graph: GraphData = {
  nodes: [
    { id: 'a', label: '系统架构', meta: { kind: 'entity', type: '能力', aliases: ['D2'] } },
    { id: 'b', label: '技术选型', meta: { kind: 'entity', type: '行为' } },
    { id: 'c', label: '交付质量', meta: { kind: 'entity', type: '目标' } },
    { id: 'event-1', label: '架构评审', meta: { kind: 'event' } },
    { id: 'isolated', label: '独立实体', meta: { kind: 'entity' } },
  ],
  links: [
    { source: 'a', target: 'b', label: '包含' },
    { source: { id: 'a' }, target: { id: 'b' }, label: '关联' } as unknown as GraphData['links'][number],
    { source: 'b', target: 'c', label: '影响' },
    { source: 'event-1', target: 'a', label: '涉及' },
    { source: 'a', target: 'a', label: '自引用' },
    { source: 'missing', target: 'a', label: '过期端点' },
  ],
}

describe('graph directory and neighborhood projection', () => {
  it('counts distinct loaded neighbors without inflating parallel links or self loops', () => {
    const index = buildDirectoryIndex(graph)
    expect(index.neighbors.get('a')?.size).toBe(2)
    expect(index.neighbors.get('isolated')?.size).toBe(0)
    expect(index.groups.flatMap(group => group.nodes).map(node => node.id).sort()).toEqual(graph.nodes.map(node => node.id).sort())
    expect(index.groups.find(group => group.label === '事件')?.nodes.map(node => node.id)).toEqual(['event-1'])
  })

  it('searches aliases and keeps original groups and degree counts intact', () => {
    const index = buildDirectoryIndex(graph)
    expect(searchDirectory(index.groups, ' d2 ').flatMap(group => group.nodes).map(node => node.id)).toEqual(['a'])
    expect(searchDirectory(index.groups, '不存在')).toEqual([])
    expect(index.groups.flatMap(group => group.nodes)).toHaveLength(5)
  })

  it('projects one or two hops, retaining directed parallel edges and excluding missing endpoints', () => {
    const index = buildDirectoryIndex(graph)
    const one = getNeighborhood(graph, index, 'a', 1)
    expect(one.nodes.map(node => node.id).sort()).toEqual(['a', 'b', 'event-1'])
    expect(one.links.map(link => link.label)).toEqual(['包含', '关联', '涉及', '自引用'])
    expect(one.links[0]).toMatchObject({ source: 'a', target: 'b' })
    expect(getNeighborhood(graph, index, 'a', 2).nodes.map(node => node.id).sort()).toEqual(['a', 'b', 'c', 'event-1'])
    expect(graph.links[1].source).toEqual({ id: 'a' })
  })

  it('keeps an isolated selection visible and uses the whole graph when selection is cleared or stale', () => {
    const index = buildDirectoryIndex(graph)
    expect(getNeighborhood(graph, index, 'isolated', 1)).toEqual({ nodes: [graph.nodes[4]], links: [] })
    expect(getNeighborhood(graph, index, null, 1)).toBe(graph)
    expect(getNeighborhood(graph, index, 'previous-scope', 1)).toBe(graph)
  })
})
