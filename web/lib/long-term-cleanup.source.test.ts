import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

import { readMessageCatalogSource } from './source-test-utils'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8')
}

describe('long-term cleanup source guards', () => {
  it('removes the legacy parsed-files hook in favor of the zustand store', () => {
    expect(fs.existsSync(path.resolve(__dirname, '..', 'hooks/use-parsed-files.ts'))).toBe(false)
    expect(read('store/use-parsed-files-store.ts')).not.toContain('Math.random(')
  })

  it('keeps the graph service under lib instead of the standalone services directory', () => {
    expect(fs.existsSync(path.resolve(__dirname, '..', 'services/graph-service.ts'))).toBe(false)
    expect(read('lib/graph-service.ts')).not.toContain('Math.random(')
  })

  it('keeps tailwind content paths limited to real project directories', () => {
    const src = read('tailwind.config.ts')

    expect(src).not.toContain("'./pages/**/*.{ts,tsx}'")
    expect(src).not.toContain("'./src/**/*.{ts,tsx}'")
  })

  it('keeps blink keyframes defined in only one place', () => {
    const globals = read('app/globals.css')
    const tailwind = read('tailwind.config.ts')

    expect(globals).not.toContain('@keyframes blink')
    expect(tailwind).toContain('"blink": {')
  })

  it('keeps the event bus and auth header fallback on typed, production-safe paths', () => {
    const eventBus = read('lib/event-bus.ts')
    const authHeaders = read('lib/auth-headers.ts')

    expect(eventBus).not.toContain('payload: any')
    expect(eventBus).not.toContain('(payload: any)')
    expect(authHeaders).not.toContain("userId || 'demo'")
    expect(authHeaders).toContain("process.env.NODE_ENV === 'development'")
  })

  it('keeps document detail tabs accessible and seeds centralized messages for future i18n work', () => {
    const dialog = [
      read('components/document-detail-dialog.tsx'),
      read('components/document-detail-dialog/document-detail-activity-panel.tsx'),
    ].join('\n')
    const messageCatalog = readMessageCatalogSource(path.resolve(__dirname, '..'))

    expect(dialog).toContain('role="tablist"')
    expect(dialog).toContain('role="tab"')
    expect(dialog).toContain('role="tabpanel"')
    expect(dialog).toContain('aria-controls={')
    expect(dialog).toContain('aria-labelledby={')
    expect(dialog).toContain("import { useTranslations } from 'next-intl'")
    expect(dialog).toContain("const commonT = useTranslations('Common')")
    expect(dialog).toContain("const documentsT = useTranslations('Documents')")
    expect(messageCatalog).toContain('Common:')
    expect(messageCatalog).toContain('Documents:')
  })

  it('keeps business-specific parser controls out of the ui primitives directory', () => {
    expect(fs.existsSync(path.resolve(__dirname, '..', 'components/ui/parser-dropdown.tsx'))).toBe(false)
    expect(fs.existsSync(path.resolve(__dirname, '..', 'components/ui/chunk-strategy-dropdown.tsx'))).toBe(false)
    expect(fs.existsSync(path.resolve(__dirname, '..', 'components/business/parser-dropdown.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, '..', 'components/business/chunk-strategy-dropdown.tsx'))).toBe(true)
  })
})
