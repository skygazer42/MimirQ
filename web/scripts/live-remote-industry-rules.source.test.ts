import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote industry rules live playwright wiring', () => {
  it('exposes a dedicated script and config for the industry rules workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-industry-rules']).toBe(
      'pnpm exec playwright test e2e/industry-rules.live.spec.ts --config playwright.remote-industry-rules.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-industry-rules.config.ts')
      )
    ).toBe(true)
  })
})
