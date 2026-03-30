import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl navigation source', () => {
  it('shares locale-aware navigation helpers across the first localized client surfaces', () => {
    const navigation = read('i18n/navigation.ts')
    const chatArea = read('components/chat-area.tsx')
    const chatPageClient = read('components/chat-page-client.tsx')
    const historyPageClient = read('app/history/page-client.tsx')
    const localeKnowledge = read('app/[locale]/knowledge/page.tsx')
    const localeEvaluations = read('app/[locale]/evaluations/page.tsx')

    expect(navigation).toContain("import { createNavigation } from 'next-intl/navigation'")
    expect(navigation).toContain("import { routing } from './routing'")
    expect(navigation).toContain('createNavigation(routing)')
    expect(navigation).toContain('export const { Link, getPathname, redirect, usePathname, useRouter }')

    expect(chatArea).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(chatArea).not.toContain("import { useRouter } from 'next/navigation'")

    expect(chatPageClient).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(chatPageClient).not.toContain("import { useRouter, useSearchParams } from 'next/navigation'")

    expect(historyPageClient).toContain("import { useRouter } from '@/i18n/navigation'")
    expect(historyPageClient).not.toContain("import { useRouter, useSearchParams } from 'next/navigation'")

    expect(localeKnowledge).toContain("export { default } from '../../knowledge/page'")
    expect(localeEvaluations).toContain("export { default } from '../../evaluations/page'")
  })
})
