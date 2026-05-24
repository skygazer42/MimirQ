import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote dataset evidence workbench live playwright wiring', () => {
  it('exposes a dedicated script and config for the dataset evidence workbench page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-dataset-evidence']).toBe(
      'pnpm exec playwright test e2e/dataset-evidence-workbench.live.spec.ts --config playwright.remote-dataset-evidence.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-dataset-evidence.config.ts')
      )
    ).toBe(true)
  })
})
