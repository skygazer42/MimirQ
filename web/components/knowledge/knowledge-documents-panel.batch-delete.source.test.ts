import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeDocumentsPanel batch delete confirmation', () => {
  it('uses AlertDialog for destructive batch delete (baseline-ui)', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, '<AlertDialog open={batchDeleteOpen}')
    expectSourceToContain(src, 't("batchDelete.title")')
    expectSourceNotToContain(src, '<Dialog open={batchDeleteOpen}')
  })
})
