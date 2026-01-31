import { describe, expect, it } from 'vitest'

import { flattenDatasetCategoryTree } from '@/lib/dataset-categories'

import type { DatasetCategoryNode } from '@/types'

describe('flattenDatasetCategoryTree', () => {
  it('flattens a tree with depth', () => {
    const items: DatasetCategoryNode[] = [
      {
        id: 'a',
        name: 'A',
        parent_id: null,
        sort_order: 0,
        depth: 0,
        datasets: 0,
        children: [
          {
            id: 'b',
            name: 'B',
            parent_id: 'a',
            sort_order: 0,
            depth: 1,
            datasets: 0,
            children: [],
          },
        ],
      },
    ]

    expect(flattenDatasetCategoryTree(items)).toEqual([
      { id: 'a', name: 'A', depth: 0 },
      { id: 'b', name: 'B', depth: 1 },
    ])
  })
})

