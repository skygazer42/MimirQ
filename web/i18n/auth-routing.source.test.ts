import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl auth routing source', () => {
  it('uses locale-aware navigation helpers across auth entry points and callback routes', () => {
    const authGuard = read('components/auth-guard.tsx')
    const authPage = read('app/auth/page.tsx')
    const oidcCallback = read('app/auth/oidc/callback/page.tsx')
    const samlCallback = read('app/auth/saml/callback/page.tsx')

    expect(authGuard).toContain('@/i18n/navigation')
    expect(authGuard).not.toContain("from 'next/navigation'")

    expect(authPage).toContain('@/i18n/navigation')
    expect(authPage).not.toContain("import { useRouter } from 'next/navigation'")

    expect(oidcCallback).toContain('@/i18n/navigation')
    expect(oidcCallback).toContain("import { useSearchParams } from 'next/navigation'")

    expect(samlCallback).toContain('@/i18n/navigation')
    expect(samlCallback).not.toContain("import { useRouter } from 'next/navigation'")

    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/auth/oidc/callback/page.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(webRoot, 'app/[locale]/auth/saml/callback/page.tsx'))).toBe(true)
  })
})
