import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl chunk-preview context source', () => {
  it('uses the locale-aware router helper and syncs chunk deep links through the internal chunk-preview route', () => {
    const context = read('components/chunk-preview/context.tsx')

    expect(context).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(context).toContain("import { useSearchParams } from 'next/navigation'")
    expect(context).not.toContain("import { useRouter, useSearchParams } from 'next/navigation'")
    expect(context).toContain("const path = '/chunk-preview'")
    expect(context).not.toContain('window.location.pathname')
  })
})
