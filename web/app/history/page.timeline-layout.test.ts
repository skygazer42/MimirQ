import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page timeline layout', () => {
  it('uses separated conversation cards and grouped message sections instead of a flat stack', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('space-y-2 px-1 pb-2')
    expect(src).toContain('groupMessagesByDay(messages, locale')
    expect(src).toContain('md:grid-cols-[6rem_minmax(0,1fr)]')
    expect(src).toContain("t('speakerQuestion')")
    expect(src).toContain("t('speakerAnswer')")
  })
})
