import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote knowledge nebula live playwright wiring', () => {
  it('exposes a dedicated script and config for the knowledge nebula page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-knowledge-nebula']).toBe(
      'pnpm exec playwright test e2e/knowledge-nebula.live.spec.ts --config playwright.remote-knowledge-nebula.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-knowledge-nebula.config.ts')
      )
    ).toBe(true)
  })
})
