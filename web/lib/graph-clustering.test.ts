import { describe, expect, it } from 'vitest'

import { computeConnectedComponents } from './graph-clustering'

describe('computeConnectedComponents', () => {
  it('clusters nodes by connected components (undirected)', () => {
    const res = computeConnectedComponents({
      nodes: [
        { id: 'a', label: 'a' },
        { id: 'b', label: 'b' },
        { id: 'c', label: 'c' },
        { id: 'd', label: 'd' },
        { id: 'e', label: 'e' },
      ],
      links: [
        { source: 'a', target: 'b', label: 'x' },
        { source: 'b', target: 'c', label: 'x' },
        { source: 'd', target: 'e', label: 'x' },
      ],
    })

    expect(res.clusterCount).toBe(2)
    expect(res.clusterSizes).toEqual([3, 2])
    expect(res.nodeToCluster.a).toBe(res.nodeToCluster.b)
    expect(res.nodeToCluster.b).toBe(res.nodeToCluster.c)
    expect(res.nodeToCluster.d).toBe(res.nodeToCluster.e)
    expect(res.nodeToCluster.a).not.toBe(res.nodeToCluster.d)
  })

  it('ignores edges that reference missing nodes', () => {
    const res = computeConnectedComponents({
      nodes: [{ id: 'a', label: 'a' }, { id: 'b', label: 'b' }],
      links: [{ source: 'a', target: 'missing', label: 'x' }],
    })

    expect(res.clusterCount).toBe(2)
    expect(res.clusterSizes).toEqual([1, 1])
  })
})

