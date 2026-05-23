import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote diagnostics live playwright wiring', () => {
  it('exposes a dedicated script and config for the diagnostics center', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-diagnostics']).toBe(
      'pnpm exec playwright test e2e/diagnostics.live.spec.ts --config playwright.remote-diagnostics.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-diagnostics.config.ts')
      )
    ).toBe(true)
  })
})
