import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote graph diagnostics live playwright wiring', () => {
  it('exposes a dedicated script and config for the graph diagnostics page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-graph-diagnostics']).toBe(
      'pnpm exec playwright test e2e/graph-diagnostics.live.spec.ts --config playwright.remote-graph-diagnostics.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-graph-diagnostics.config.ts')
      )
    ).toBe(true)
  })
})
