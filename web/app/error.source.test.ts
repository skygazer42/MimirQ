import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('global error page source', () => {
  it('uses the shared RouteError wrapper', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'error.tsx'), 'utf8')

    expect(src).toContain("import { RouteError } from '@/components/route-error'")
    expect(src).toContain('<RouteError')
  })
})
