import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote document health live playwright wiring', () => {
  it('exposes a dedicated script and config for the document health page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-document-health']).toBe(
      'pnpm exec playwright test e2e/document-health.live.spec.ts --config playwright.remote-document-health.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-document-health.config.ts')
      )
    ).toBe(true)
  })
})
