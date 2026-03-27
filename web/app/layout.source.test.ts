import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('root layout source', () => {
  it('mounts the web vitals reporter at the app root', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'layout.tsx'), 'utf8')

    expect(src).toContain('WebVitalsReporter')
    expect(src).toContain('<WebVitalsReporter />')
  })
})
