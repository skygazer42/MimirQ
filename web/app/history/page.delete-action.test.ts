import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page delete action styling', () => {
  it('uses ghost icon buttons for hover actions instead of the default solid button surface', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('variant="ghost"')
    expect(src).toContain('hover:bg-destructive/10')
    expect(src).toContain('hover:bg-muted/80')
  })
})
