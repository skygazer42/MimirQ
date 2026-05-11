import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeDocumentsPanel batch delete tone', () => {
  it('uses a light danger treatment for the toolbar entry while keeping the final confirmation destructive', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(
      src,
      'bg-destructive/5 text-destructive hover:bg-destructive/15'
    )
    expectSourceToContain(src, 'onClick={() => setBatchDeleteOpen(true)}')
    expectSourceToContain(
      src,
      'variant="destructive" onClick={() => detachPromise(confirmBatchDelete())}'
    )
  })
})
