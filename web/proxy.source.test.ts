import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('proxy source', () => {
  it('generates a per-request nonce and enforces CSP on request and response headers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'proxy.ts'), 'utf8')

    expect(src).toContain("import { NextRequest, NextResponse } from 'next/server'")
    expect(src).toContain('export function proxy(')
    expect(src).toContain("requestHeaders.set('x-nonce', nonce)")
    expect(src).toContain("requestHeaders.set('Content-Security-Policy', cspHeader)")
    expect(src).toContain('const response = NextResponse.next({')
    expect(src).toContain("response.headers.set('Content-Security-Policy', cspHeader)")
    expect(src).not.toContain('Content-Security-Policy-Report-Only')
  })

  it('skips API routes, static assets, and prefetch requests', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'proxy.ts'), 'utf8')

    expect(src).toContain("source: '/((?!api|_next|.*\\\\..*).*)'")
    expect(src).toContain("key: 'next-router-prefetch'")
    expect(src).toContain("key: 'purpose', value: 'prefetch'")
  })
})
