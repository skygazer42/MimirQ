import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, '..', relativePath), 'utf8')
}

describe('type safety hotspots', () => {
  it('keeps chat formatting and chat area metadata filters on unknown-safe objects', () => {
    const formatter = read('hooks/use-chat-formatter.ts')
    const chatArea = read('components/chat-area.tsx')

    expect(formatter).not.toContain('metadata_filter?: Record<string, any> | null')
    expect(chatArea).not.toContain('metadata_filter?: Record<string, any> | null')
    expect(chatArea).not.toContain('icon: any')
  })

  it('keeps auth proxy routes free of any-based JSON helpers and error catches', () => {
    const exchangeRoute = read('app/api/oidc/exchange/route.ts')
    const logoutRoute = read('app/api/oidc/logout/route.ts')
    const refreshRoute = read('app/api/oidc/refresh/route.ts')
    const samlRoute = read('app/api/saml/acs/route.ts')

    expect(exchangeRoute).not.toContain('function jsonNoStore(data: any')
    expect(exchangeRoute).not.toContain('catch (e: any)')
    expect(logoutRoute).not.toContain('function jsonNoStore(data: any')
    expect(refreshRoute).not.toContain('function jsonNoStore(data: any')
    expect(refreshRoute).not.toContain('catch (e: any)')
    expect(samlRoute).not.toContain('function jsonNoStore(data: any')
  })

  it('keeps core chat types on unknown-safe payloads', () => {
    const types = read('types/index.ts')

    expect(types).not.toContain('data: any')
    expect(types).not.toContain('structured_data?: any')
    expect(types).not.toContain('next?: any')
    expect(types).not.toContain('metadata_filter?: Record<string, any>')
    expect(types).not.toContain('metrics: Record<string, any>')
  })

  it('keeps ragviz evidence workbench free of any-casts', () => {
    const src = read('components/ragviz/evidence-workbench.tsx')

    expect(src).not.toContain('data: any')
    expect(src).not.toContain('as any')
    expect(src).not.toContain(': any')
    expect(src).not.toContain('Record<string, any>')
  })
})
