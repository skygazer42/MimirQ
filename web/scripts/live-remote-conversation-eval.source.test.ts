import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote conversation evaluation live playwright wiring', () => {
  it('exposes a dedicated script and config for the conversation evaluation workbench', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-conversation-eval']).toBe(
      'pnpm exec playwright test e2e/conversation-evaluation.live.spec.ts --config playwright.remote-conversation-eval.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-conversation-eval.config.ts')
      )
    ).toBe(true)
  })
})
