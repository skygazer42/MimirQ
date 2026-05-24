import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote parsing live playwright wiring', () => {
  it('exposes a dedicated script and config for the parsing workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-parsing']).toBe(
      'pnpm exec playwright test e2e/parsing-workbench.live.spec.ts --config playwright.remote-parsing.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-parsing.config.ts')
      )
    ).toBe(true)
  })
})
