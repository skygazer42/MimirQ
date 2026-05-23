import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote governance profiles live playwright wiring', () => {
  it('exposes a dedicated script and config for the governance profiles page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-governance-profiles']).toBe(
      'pnpm exec playwright test e2e/governance-profiles.live.spec.ts --config playwright.remote-governance-profiles.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-governance-profiles.config.ts')
      )
    ).toBe(true)
  })
})
