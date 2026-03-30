import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl chunk-preview router source', () => {
  it('uses the locale-aware router helper across chunk-preview entry-action components', () => {
    const ingestionPreviewDetailsDialog = read('components/chunk-preview/components/ingestion-preview-details-dialog.tsx')
    const topBar = read('components/chunk-preview/components/workbench/top-bar.tsx')

    expect(ingestionPreviewDetailsDialog).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(ingestionPreviewDetailsDialog).not.toContain("import { useRouter } from 'next/navigation'")

    expect(topBar).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(topBar).not.toContain("import { useRouter } from 'next/navigation'")
  })
})
