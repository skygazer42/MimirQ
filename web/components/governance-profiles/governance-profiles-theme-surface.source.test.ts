import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

const page = fs.readFileSync(
  path.resolve(__dirname, 'governance-profiles-page.tsx'),
  'utf8'
)

describe('governance profiles theme surfaces', () => {
  it('uses the Ocean background for the page and primary carriers', () => {
    expect(page).toContain(
      'className="flex-1 flex flex-col overflow-hidden bg-background"'
    )
    expect(page).toContain(
      'className="mt-4 overflow-hidden rounded-2xl border-border/50 bg-background shadow-none"'
    )
    expect(page).toContain(
      'className="mt-3 border-border/50 bg-background shadow-none"'
    )
    expect(page).toContain(
      "'group relative overflow-hidden rounded-2xl border-border/60 bg-background shadow-none"
    )
  })

  it('keeps the existing controls and empty state on the same surface', () => {
    expect(page).toContain(
      'className="h-9 border-border/60 bg-background pl-9'
    )
    expect(page).toContain(
      'className="mt-6 border-border/60 bg-background"'
    )
    expect(page).toContain('hover:shadow-soft')
  })
})
