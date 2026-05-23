import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote observability live playwright wiring', () => {
  it('exposes a dedicated script and config for the observability page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-observability']).toBe(
      'pnpm exec playwright test e2e/observability.live.spec.ts --config playwright.remote-observability.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-observability.config.ts')
      )
    ).toBe(true)
  })
})
