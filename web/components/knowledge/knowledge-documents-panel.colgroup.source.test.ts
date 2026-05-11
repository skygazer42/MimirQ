import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeDocumentsPanel list table column sizing', () => {
  it('uses explicit column widths so dense metadata columns stop stealing space from the name column', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-documents-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'table-fixed')
    expectSourceToContain(src, '<colgroup>')
    expectSourceToContain(src, '<col className="w-9" />')
    expectSourceToContain(src, '{showDatasetColumn ? (')
    expectSourceToContain(src, '<col className="w-[10rem]" />')
    expectSourceToContain(src, '<col className="w-[6.5rem]" />')
    expectSourceToContain(src, '<col className="w-[6rem]" />')
    expectSourceToContain(src, '<col className="w-[4.5rem]" />')
    expectSourceToContain(src, '<col className="w-[8.5rem]" />')
  })
})
