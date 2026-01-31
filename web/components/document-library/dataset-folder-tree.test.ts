import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { DatasetFolderTreeView } from '@/components/document-library/dataset-folder-tree'

import type { DocumentFolderNode } from '@/types'

describe('DatasetFolderTreeView', () => {
  it('renders folder names and document counts', () => {
    const root: DocumentFolderNode = {
      name: '',
      path: '',
      depth: 0,
      documents: 3,
      children: [
        {
          name: 'foo',
          path: 'foo',
          depth: 1,
          documents: 2,
          children: [
            {
              name: 'bar',
              path: 'foo/bar',
              depth: 2,
              documents: 1,
              children: [],
            },
          ],
        },
      ],
    }

    const html = renderToStaticMarkup(
      createElement(DatasetFolderTreeView, {
        root,
        selectedPath: null,
        expandAll: true,
        onSelect: () => undefined,
      })
    )

    expect(html).toContain('foo')
    expect(html).toContain('bar')
    expect(html).toContain('2')
    expect(html).toContain('1')
  })
})

