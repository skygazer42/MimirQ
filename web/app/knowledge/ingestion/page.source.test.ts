import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge ingestion page source', () => {
  it('wraps the client page in AppFrame and keeps the route-level description source markers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain("import { AppFrame } from '@/components/app-frame'")
    expect(src).toContain('<AppFrame>')
    expect(src).toContain('</AppFrame>')
    expect(src).toContain('<span className="text-muted-foreground/60">|</span>')
    expect(src).toContain("<span>{t('descriptionMarker')}</span>")
  })
})
