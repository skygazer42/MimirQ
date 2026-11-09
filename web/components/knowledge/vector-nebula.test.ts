import { describe, expect, it, vi } from 'vitest'
vi.mock('next/dynamic', () => ({ default: () => () => null }))
vi.mock('@/i18n/navigation', () => ({ Link: () => null }))
import { buildNebula } from './vector-nebula'

describe('Nebula actual slice data', () => {
  it('does not turn a document filename or an unread metadata count into actual chunk nodes', () => {
    const graph = buildNebula([{ id: 'doc-1', filename: '文档.pdf', file_type: 'pdf', metadata: { chunk_count: 999 } }], new Map([['doc-1', []]]))
    expect(graph.nodes).toEqual([])
    expect(graph.links).toEqual([])
    expect(graph.clusters[0].chunkCount).toBe(0)
  })
  it('preserves actual slice identity and only joins adjacent slices of the same document', () => {
    const graph = buildNebula([{ id: 'doc-1', filename: '文档.pdf' }], new Map([['doc-1', [{ id: 'a', content: '第一段', chunk_index: 0 }, { id: 'b', content: '第二段', chunk_index: 1 }]]]))
    expect(graph.nodes.map(node => node.id)).toEqual(['doc-1:a', 'doc-1:b'])
    expect(graph.links).toEqual([{ source: 'doc-1:a', target: 'doc-1:b', color: graph.nodes[0].color }])
    expect(graph.clusters[0].chunkCount).toBe(2)
  })
})
