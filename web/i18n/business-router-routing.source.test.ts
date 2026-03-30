import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl business router source', () => {
  it('uses the locale-aware router helper across low-risk business components', () => {
    const graphPageActions = read('app/graph/use-graph-page-actions.ts')
    const chatMessageItem = read('components/chat/message-item.tsx')
    const dataGovernancePanel = read('components/data-governance-panel.tsx')
    const datasetsPage = read('components/datasets/datasets-page.tsx')
    const governanceCommonLinesPage = read('components/governance-common-lines/governance-common-lines-page.tsx')
    const parsingEditorActions = read('components/parsing/use-parsing-editor-actions.ts')
    const taskCenter = read('components/task-center.tsx')

    expect(graphPageActions).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(graphPageActions).not.toContain("import { useRouter } from 'next/navigation'")

    expect(chatMessageItem).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(chatMessageItem).not.toContain("import { useRouter } from 'next/navigation'")

    expect(dataGovernancePanel).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(dataGovernancePanel).toContain("import { useSearchParams } from 'next/navigation'")
    expect(dataGovernancePanel).not.toContain("import { useRouter, useSearchParams } from 'next/navigation'")

    expect(datasetsPage).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(datasetsPage).not.toContain("import { useRouter } from 'next/navigation'")

    expect(governanceCommonLinesPage).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(governanceCommonLinesPage).not.toContain("import { useRouter } from 'next/navigation'")

    expect(parsingEditorActions).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(parsingEditorActions).not.toContain("import { useRouter } from 'next/navigation'")

    expect(taskCenter).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(taskCenter).not.toContain("import { useRouter } from 'next/navigation'")
  })
})
