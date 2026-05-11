import fs from 'node:fs'
import path from 'node:path'

import { describe, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('dataset workflow page source', () => {
  it('loads dataset metadata and workflow config through TanStack Query', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expectSourceToContain(src, "from '@tanstack/react-query'")
    expectSourceToContain(src, 'useQuery')
    expectSourceToContain(src, 'queryKey: queryKeys.datasets.detail')
    expectSourceToContain(src, 'queryKey: queryKeys.datasets.config')
    expectSourceNotToContain(src, 'const [dataset, setDataset]')
    expectSourceNotToContain(src, 'const [exportRes, setExportRes]')
    expectSourceNotToContain(src, 'setLoading')
    expectSourceNotToContain(src, 'const load = useCallback')
  })
})
