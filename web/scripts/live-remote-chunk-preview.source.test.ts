import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote chunk preview live playwright wiring', () => {
  it('exposes a dedicated script and config for the chunk preview workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-chunk-preview']).toBe(
      'pnpm exec playwright test e2e/chunk-preview.live.spec.ts --config playwright.remote-chunk-preview.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-chunk-preview.config.ts')
      )
    ).toBe(true)
  })
})
