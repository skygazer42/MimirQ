import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote similarity live playwright wiring', () => {
  it('exposes a dedicated script and config for the similarity workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-similarity']).toBe(
      'pnpm exec playwright test e2e/similarity-workbench.live.spec.ts --config playwright.remote-similarity.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-similarity.config.ts')
      )
    ).toBe(true)
  })
})
