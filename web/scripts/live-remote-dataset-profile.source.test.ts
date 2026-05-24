import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote dataset profile live playwright wiring', () => {
  it('exposes a dedicated script and config for the dataset profile page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-dataset-profile']).toBe(
      'pnpm exec playwright test e2e/dataset-profile.live.spec.ts --config playwright.remote-dataset-profile.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-dataset-profile.config.ts')
      )
    ).toBe(true)
  })
})
