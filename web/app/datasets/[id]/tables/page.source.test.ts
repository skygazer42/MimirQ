import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('dataset tables page source', () => {
  it('loads dataset metadata and table assets through TanStack Query', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, "from '@tanstack/react-query'")
    expectSourceToContain(src, 'useQuery')
    expectSourceToContain(src, 'queryKey: queryKeys.datasets.detail')
    expectSourceToContain(src, 'queryKey: queryKeys.datasets.tables')
    expectSourceNotToContain(src, 'const [dataset, setDataset]')
    expectSourceNotToContain(src, 'const [items, setItems]')
    expectSourceNotToContain(src, 'setIsLoading')
  })
})
