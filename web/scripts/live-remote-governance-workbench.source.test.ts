import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote governance workbench live playwright wiring', () => {
  it('exposes a dedicated script and config for the data-governance workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-governance-workbench']).toBe(
      'pnpm exec playwright test e2e/governance-workbench.live.spec.ts --config playwright.remote-governance-workbench.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(
          __dirname,
          '..',
          'playwright.remote-governance-workbench.config.ts'
        )
      )
    ).toBe(true)
  })
})
