import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('web app manifest source', () => {
  it('defines an installable manifest with app shell metadata', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'manifest.ts'), 'utf8')

    expect(src).toContain("export default function manifest()")
    expect(src).toContain("name: 'MimirQ'")
    expect(src).toContain("display: 'standalone'")
    expect(src).toContain("start_url: '/'")
    expect(src).toContain("icons: [")
  })
})
