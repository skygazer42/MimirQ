import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('history page selected conversation header', () => {
  it('keeps the header compact without rendering a latest-message preview block', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).not.toContain("t('latestMessageLabel')")
    expect(src).not.toContain("selectedConversation.last_message || t('noMessage')")
  })

  it('suppresses the browser default focus outline on history list buttons', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'page-client.tsx'), 'utf8')

    expect(src).toContain('focus-visible:outline-none')
    expect(src).toContain('focus-visible:ring-0')
  })
})
