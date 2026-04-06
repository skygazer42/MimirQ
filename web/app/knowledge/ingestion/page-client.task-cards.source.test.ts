import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion monitor task cards', () => {
  it('shows the prominent progress block only for active tasks and keeps actions out of the metadata row', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain("const isActiveStatus = doc.status === 'processing' || doc.status === 'pending'")
    expect(src).toContain('isActiveStatus && doc.current_stage')
    expect(src).toContain('absolute right-5 top-4 z-20')
    expect(src).toContain('border-sky-200/60 bg-sky-50/80')
    expect(src).not.toContain('<span>Progress</span>')
  })
})
