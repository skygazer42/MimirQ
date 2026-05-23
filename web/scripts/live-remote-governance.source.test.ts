import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote governance live playwright wiring', () => {
  it('exposes a dedicated script and config for remote quarantine validation', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-governance']).toBe(
      'pnpm exec playwright test e2e/quarantine-surfaces.live.spec.ts --config playwright.remote-governance.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-governance.config.ts')
      )
    ).toBe(true)
  })
})
