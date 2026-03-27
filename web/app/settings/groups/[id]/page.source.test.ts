import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('settings group detail page source', () => {
  it('labels the icon-only remove-member trigger for assistive tech', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page.tsx'), 'utf8')

    expect(src).toContain('aria-label={removing ? `正在移除成员 ${uid}` : `移除成员 ${uid}`}')
    expect(src).toContain('<Trash2 className="h-4 w-4" />')
  })
})
