// Module boundary checks; user flows are covered by the browser verification.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('knowledge route entry', () => {
  it('keeps the route entry as a thin wrapper', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')
    expect(src).toContain("@/components/knowledge/knowledge-page")
  })

})
