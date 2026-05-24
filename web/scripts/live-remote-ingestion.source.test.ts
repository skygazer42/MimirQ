import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote ingestion live playwright wiring', () => {
  it('exposes a dedicated script and config for the ingestion monitor workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-ingestion']).toBe(
      'pnpm exec playwright test e2e/ingestion-monitor.live.spec.ts --config playwright.remote-ingestion.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-ingestion.config.ts')
      )
    ).toBe(true)
  })
})
