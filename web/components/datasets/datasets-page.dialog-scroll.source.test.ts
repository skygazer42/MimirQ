import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('datasets page dialog scroll behavior', () => {
  it('makes create and edit dataset dialogs vertically scrollable when pipeline settings expand', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'datasets-page.tsx'), 'utf8')

    expect(src).toContain('max-h-[min(88vh,860px)]')
    expect(src).toContain('overflow-y-auto custom-scrollbar')
    expect(src).toContain('DialogContent className="max-w-xl p-0 sm:rounded-2xl"')
  })
})
