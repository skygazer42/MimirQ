import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('TenantQuotaPanel theme source', () => {
  it('uses semantic theme tokens for quota cards and raw JSON details', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'tenant-quota-panel.tsx'),
      'utf8'
    )

    expect(src).toContain('TENANT_QUOTA_PANEL_CLASS')
    expect(src).toContain('QUOTA_CARD_CLASS')
    expect(src).toContain('border-border/60')
    expect(src).toContain('text-muted-foreground')
    expect(src).toContain('bg-success')
    expect(src).toContain('bg-destructive')

    expect(src).not.toMatch(/\b(?:bg|text|border|divide|hover:bg|hover:text|hover:border|disabled:bg|disabled:text|accent)-(?:slate|blue|indigo|purple|red|emerald|amber|rose)-/)
    expect(src).not.toContain('bg-white')
    expect(src).not.toContain('text-white')
  })
})
