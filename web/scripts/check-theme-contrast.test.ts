import { describe, expect, it } from 'vitest'

import { extractBlock } from './check-theme-contrast.mjs'

describe('theme contrast selector extraction', () => {
  it.each(["'", '"'])('accepts CSS attribute values quoted with %s', (quote) => {
    const source = `html.dark[data-surface-theme=${quote}ocean${quote}] { --foreground: 210 25% 90%; }`

    expect(extractBlock(source, 'html.dark[data-surface-theme="ocean"]')).toContain('--foreground: 210 25% 90%;')
  })

  it('requires the requested theme and dark-mode selector', () => {
    const source = `
      html:not(.dark)[data-surface-theme='ocean'] { --foreground: 210 25% 10%; }
      html.dark[data-surface-theme='deepsea'] { --foreground: 210 25% 95%; }
    `

    expect(extractBlock(source, 'html.dark[data-surface-theme="ocean"]')).toBeNull()
  })
})
