import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote dataset tables live playwright wiring', () => {
  it('exposes a dedicated script and config for the dataset tables page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-dataset-tables']).toBe(
      'pnpm exec playwright test e2e/dataset-tables.live.spec.ts --config playwright.remote-dataset-tables.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-dataset-tables.config.ts')
      )
    ).toBe(true)
  })
})
