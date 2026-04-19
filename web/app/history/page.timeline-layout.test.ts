import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page timeline layout', () => {
  it('uses grouped message sections with asymmetric left/right alignment instead of the old timeline grid', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')
    const messageSrc = fs.readFileSync(path.resolve(__dirname, '../../components/chat/message-item.tsx'), 'utf8')

    expect(src).toContain('space-y-0 px-0 pb-0')
    expect(src).toContain('groupMessagesByDay(messages, locale')
    expect(src).toContain('isUser ? "flex justify-end" : "flex justify-start"')
    expect(messageSrc).toContain('max-w-[78%]')
    expect(messageSrc).toContain('max-w-[88%]')
    expect(src).toContain("t('speakerQuestion')")
    expect(src).toContain("t('speakerAnswer')")
  })
})
