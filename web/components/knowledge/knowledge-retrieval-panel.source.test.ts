import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import {
  expectSourceNotToContain,
  expectSourceToContain,
} from '@/lib/source-test-utils'

describe('KnowledgeRetrievalPanel module', () => {
  it('exports KnowledgeRetrievalPanel and sources copy from next-intl', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-retrieval-panel.tsx'),
      'utf8'
    )

    expectSourceToContain(src, 'export function KnowledgeRetrievalPanel')
    expectSourceToContain(src, "useTranslations('KnowledgeRetrievalPanel')")
    expectSourceToContain(src, 'const metricCards = useMemo(')
    expect(src).toMatch(/import\s*\{[\s\S]*\buseMemo\b[\s\S]*\}\s*from 'react'/)
    expectSourceToContain(src, 't("header.title")')
    expectSourceToContain(src, 't("actions.run")')
    expectSourceToContain(src, 't("header.currentDataset")')
    expectSourceToContain(src, 't("header.noneSelected")')
    expectSourceToContain(src, 't("actions.running")')
    expectSourceToContain(src, 't("empty.title")')
    expectSourceToContain(src, 't("empty.description")')
    expectSourceToContain(src, 't("empty.waitingForDataset")')
    expectSourceToContain(src, 't("samples.missingInBackend")')
    expectSourceToContain(src, 't("samples.orphanIds")')
    expectSourceNotToContain(src, 'Diagnostic Center')
    expectSourceNotToContain(src, 'Auditing...')
    expectSourceNotToContain(src, 'Initialization Required')
    expectSourceNotToContain(src, 'Run audit to sync indices')
    expectSourceNotToContain(src, 'Waiting for Dataset Selection')
  })
})
