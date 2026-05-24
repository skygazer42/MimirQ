import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote dataset precheck live playwright wiring', () => {
  it('exposes a dedicated script and config for the dataset precheck page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-dataset-precheck']).toBe(
      'pnpm exec playwright test e2e/dataset-precheck.live.spec.ts --config playwright.remote-dataset-precheck.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-dataset-precheck.config.ts')
      )
    ).toBe(true)
  })
})
