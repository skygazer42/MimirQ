import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote web live playwright wiring', () => {
  it('exposes a dedicated script and config for remote web page-host validation', () => {
    const pkg = JSON.parse(fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-web']).toBe(
      'pnpm exec playwright test e2e/backend-business-surfaces.live.spec.ts --config playwright.remote-web.config.ts'
    )
    expect(fs.existsSync(path.resolve(__dirname, '..', 'playwright.remote-web.config.ts'))).toBe(true)
  })
})
