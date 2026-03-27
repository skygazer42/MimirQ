import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('lottie animation source', () => {
  it('uses same-origin animation assets so offline caching can cover them', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'lottie-animation.tsx'), 'utf8')

    expect(src).toContain('"/lottie/empty-documents.json"')
    expect(src).toContain('"/lottie/thinking.json"')
    expect(src).toContain('"/lottie/processing.json"')
    expect(src).not.toContain('lottiefiles.com')
  })
})
