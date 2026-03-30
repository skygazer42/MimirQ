import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(webRoot, relativePath), 'utf8')
}

describe('next-intl locale routing source', () => {
  it('wires routing, request config, proxy, and locale wrappers for the initial rollout surface', () => {
    const routing = read('i18n/routing.ts')
    const request = read('i18n/request.ts')
    const proxy = read('proxy.ts')
    const localeLayout = read('app/[locale]/layout.tsx')
    const localeHome = read('app/[locale]/page.tsx')
    const localeHistory = read('app/[locale]/history/page.tsx')

    expect(routing).toContain("import { defineRouting } from 'next-intl/routing'")
    expect(routing).toContain("locales: ['zh-CN']")
    expect(routing).toContain("defaultLocale: 'zh-CN'")

    expect(request).toContain("import { getRequestConfig } from 'next-intl/server'")
    expect(request).toContain("import zhCNMessages from './messages/zh-CN'")
    expect(request).toContain('return {')
    expect(request).toContain('locale,')
    expect(request).toContain('messages: zhCNMessages')

    expect(proxy).toContain("import createMiddleware from 'next-intl/middleware'")
    expect(proxy).toContain("import { routing } from './i18n/routing'")
    expect(proxy).toContain('const handleI18nRouting = createMiddleware(routing)')
    expect(proxy).toContain('const response = handleI18nRouting(')

    expect(localeLayout).toContain("import { setRequestLocale } from 'next-intl/server'")
    expect(localeLayout).toContain("import { notFound } from 'next/navigation'")
    expect(localeLayout).toContain('const { locale } = await params')
    expect(localeLayout).toContain('routing.locales.includes(')
    expect(localeLayout).toContain('notFound()')
    expect(localeLayout).toContain('setRequestLocale(locale)')

    expect(localeHome).toContain("export { default } from '../page'")
    expect(localeHistory).toContain("export { default } from '../../history/page'")
  })
})
