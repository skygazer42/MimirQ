import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote dataset workflow live playwright wiring', () => {
  it('exposes a dedicated script and config for the dataset workflow page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-dataset-workflow']).toBe(
      'pnpm exec playwright test e2e/dataset-workflow.live.spec.ts --config playwright.remote-dataset-workflow.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-dataset-workflow.config.ts')
      )
    ).toBe(true)
  })
})
