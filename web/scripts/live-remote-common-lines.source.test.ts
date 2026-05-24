import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote common-lines live playwright wiring', () => {
  it('exposes a dedicated script and config for the common-lines workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-common-lines']).toBe(
      'pnpm exec playwright test e2e/common-lines-workbench.live.spec.ts --config playwright.remote-common-lines.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-common-lines.config.ts')
      )
    ).toBe(true)
  })
})
