import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { readMessageCatalogSource } from '@/lib/source-test-utils'

describe('KnowledgeSettingsPanel monitoring summary labels', () => {
  it('sources the monitoring header and summary chips from i18n messages', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-settings-panel.tsx'), 'utf8')
    const messages = readMessageCatalogSource(path.resolve(__dirname, '../..'))

    expect(src).toContain("t('connectorRuns.title')")
    expect(src).toContain("t('connectorRuns.liveBadge')")
    expect(src).toContain("t('connectorRuns.summary.all')")
    expect(src).toContain("t('connectorRuns.summary.active')")
    expect(src).toContain("t('runStatus.failed')")
    expect(src).toContain("t('runStatus.completed')")
    expect(src).not.toContain(">Monitoring<")
    expect(src).not.toContain(">Live<")
    expect(src).not.toContain("label: 'All'")
    expect(src).not.toContain("label: 'Active'")
    expect(src).not.toContain("label: 'Failed'")
    expect(src).not.toContain("label: 'Done'")

    expect(messages).toContain("liveBadge: '实时'")
    expect(messages).toContain("summary: {")
    expect(messages).toContain("all: '全部'")
    expect(messages).toContain("active: '进行中'")
  })
})
