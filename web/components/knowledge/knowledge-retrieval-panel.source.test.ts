import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeRetrievalPanel module', () => {
  it('exports KnowledgeRetrievalPanel and sources copy from next-intl', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-retrieval-panel.tsx'), 'utf8')

    expect(src).toContain('export function KnowledgeRetrievalPanel')
    expect(src).toContain("useTranslations('KnowledgeRetrievalPanel')")
    expect(src).toContain('const metricCards = useMemo(')
    expect(src).toMatch(/import\s*\{[\s\S]*\buseMemo\b[\s\S]*\}\s*from 'react'/)
    expect(src).toContain('t("header.title")')
    expect(src).toContain('t("actions.run")')
    expect(src).toContain('t("header.currentDataset")')
    expect(src).toContain('t("header.noneSelected")')
    expect(src).toContain('t("actions.running")')
    expect(src).toContain('t("empty.title")')
    expect(src).toContain('t("empty.description")')
    expect(src).toContain('t("empty.waitingForDataset")')
    expect(src).toContain('t("samples.missingInBackend")')
    expect(src).toContain('t("samples.orphanIds")')
    expect(src).not.toContain('Diagnostic Center')
    expect(src).not.toContain('Auditing...')
    expect(src).not.toContain('Initialization Required')
    expect(src).not.toContain('Run audit to sync indices')
    expect(src).not.toContain('Waiting for Dataset Selection')
  })
})
