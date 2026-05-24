import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote ablations live playwright wiring', () => {
  it('exposes a dedicated script and config for the retrieval ablations workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-ablations']).toBe(
      'pnpm exec playwright test e2e/retrieval-ablations.live.spec.ts --config playwright.remote-ablations.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-ablations.config.ts')
      )
    ).toBe(true)
  })
})
