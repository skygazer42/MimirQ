import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote dataset ingestion policy live playwright wiring', () => {
  it('exposes a dedicated script and config for the dataset ingestion policy page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-dataset-ingestion-policy']).toBe(
      'pnpm exec playwright test e2e/dataset-ingestion-policy.live.spec.ts --config playwright.remote-dataset-ingestion-policy.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-dataset-ingestion-policy.config.ts')
      )
    ).toBe(true)
  })
})
