import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote management live playwright wiring', () => {
  it('exposes a dedicated script and config for remote management-surface validation', () => {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-management']).toBe(
      'pnpm exec playwright test e2e/management-surfaces.live.spec.ts --config playwright.remote-management.config.ts'
    )
    expect(fs.existsSync(path.resolve(__dirname, '..', 'playwright.remote-management.config.ts'))).toBe(true)
  })
})
