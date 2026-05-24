import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote dataset KG workbench live playwright wiring', () => {
  it('exposes a dedicated script and config for the dataset KG workbench page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-dataset-kg']).toBe(
      'pnpm exec playwright test e2e/dataset-kg-workbench.live.spec.ts --config playwright.remote-dataset-kg.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-dataset-kg.config.ts')
      )
    ).toBe(true)
  })
})
