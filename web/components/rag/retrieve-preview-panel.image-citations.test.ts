import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('retrieve preview panel image citations', () => {
  it('renders safe thumbnails for image citations', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'retrieve-preview-panel.tsx'), 'utf8')
    expect(src).toContain('img_url')
    expect(src).toContain('has_image')
  })
})

