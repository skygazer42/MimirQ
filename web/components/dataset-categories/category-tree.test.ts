import fs from 'node:fs'
import path from 'node:path'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { DatasetCategoryTreeView } from '@/components/dataset-categories/category-tree'

import type { DatasetCategoryNode } from '@/types'

describe('DatasetCategoryTreeView', () => {
  it('renders category names', () => {
    const items: DatasetCategoryNode[] = [
      {
        id: 'root',
        name: 'Root',
        parent_id: null,
        sort_order: 0,
        depth: 0,
        datasets: 0,
        children: [
          {
            id: 'child',
            name: 'Child',
            parent_id: 'root',
            sort_order: 0,
            depth: 1,
            datasets: 0,
            children: [],
          },
        ],
      },
    ]

    const html = renderToStaticMarkup(
      createElement(DatasetCategoryTreeView, {
        items,
        selectedId: null,
        expandAll: true,
        onSelect: () => undefined,
      })
    )

    expect(html).toContain('全部分类')
    expect(html).toContain('Root')
    expect(html).toContain('Child')
  })

  it('exposes a create-category entry in the category tree source', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'category-tree.tsx'), 'utf8')

    expect(src).toContain('新建分类')
    expect(src).toContain('datasetCategoryApi.create')
    expect(src).toContain('datasetCategoryApi.delete')
    expect(src).toContain('删除分类')
    expect(src).toContain('title={node.name}')
    expect(src).toContain("title={selectedNodeName || '全部分类'}")
  })
})
