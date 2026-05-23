import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote evidence live playwright wiring', () => {
  it('exposes a dedicated script and config for the evidence workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-evidence']).toBe(
      'pnpm exec playwright test e2e/evidence-workbench.live.spec.ts --config playwright.remote-evidence.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-evidence.config.ts')
      )
    ).toBe(true)
  })
})
