import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('next security headers source', () => {
  it('does not send HSTS for local Docker HTTP origins used by live-stack tests', () => {
    const src = fs.readFileSync(path.resolve(__dirname, '../next.config.mjs'), 'utf8')

    expect(src).toContain("'web'")
    expect(src).toContain("'mimirq-api'")
    expect(src).toContain('NEXT_DISABLE_HSTS')
    expect(src).toContain("isLocalDevOrigin(process.env.NEXT_PUBLIC_API_URL || '')")
    expect(src).toContain('if (shouldSendHsts)')
    expect(src).not.toContain(`if (process.env.NODE_ENV === 'production') {
  sharedSecurityHeaders.push({
    key: 'Strict-Transport-Security'`)
  })
})
