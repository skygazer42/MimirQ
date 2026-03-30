import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('root layout source', () => {
  it('keeps the global shell lean while mounting the web vitals reporter', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'layout.tsx'), 'utf8')

    expect(src).toContain("import { connection } from 'next/server'")
    expect(src).toContain("import { getLocale, getMessages } from 'next-intl/server'")
    expect(src).toContain("import { NextIntlClientProvider } from 'next-intl'")
    expect(src).not.toContain("@xyflow/react/dist/style.css")
    expect(src).not.toContain('PipelineCapabilitiesProvider')
    expect(src).not.toContain('ParserBackendProvider')
    expect(src).not.toContain('ChunkStrategyProvider')
    expect(src).not.toContain('PipelineOptionsProvider')
    expect(src).toContain('WebVitalsReporter')
    expect(src).toContain('<WebVitalsReporter />')
    expect(src).toContain('ServiceWorkerRegistrar')
    expect(src).toContain('<ServiceWorkerRegistrar />')
    expect(src).toContain('<AuthGuard>{children}</AuthGuard>')
    expect(src).toContain('<NextIntlClientProvider')
    expect(src).toContain('manifest:')
    expect(src).toContain('prefers-color-scheme: light')
    expect(src).toContain('prefers-color-scheme: dark')
    expect(src).toContain('const locale = await getLocale()')
    expect(src).toContain('const messages = await getMessages()')
    expect(src).toContain('dir={documentDir}')
    expect(src).toContain('export default async function RootLayout')
    expect(src).toContain('await connection()')
  })
})
