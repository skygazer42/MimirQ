import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('remote graph live playwright wiring', () => {
  it('exposes a dedicated script and config for the graph page', () => {
    const pkg = JSON.parse(
      fs.readFileSync(path.resolve(__dirname, '..', 'package.json'), 'utf8')
    ) as {
      scripts?: Record<string, string>
    }

    expect(pkg.scripts?.['e2e:live:remote-graph']).toBe(
      'pnpm exec playwright test e2e/graph.live.spec.ts --config playwright.remote-graph.config.ts'
    )
    expect(
      fs.existsSync(
        path.resolve(__dirname, '..', 'playwright.remote-graph.config.ts')
      )
    ).toBe(true)
  })

  it('asserts exact scoped KG counts instead of a loose header regex', () => {
    const spec = fs.readFileSync(
      path.resolve(__dirname, '..', 'e2e', 'graph.live.spec.ts'),
      'utf8'
    )

    expect(spec).toContain(
      "const expectedStatsLabel = `E:${expectedStats.events} N:${expectedStats.entities} L:${expectedStats.links}`"
    )
    expect(spec).not.toContain("page.getByText(/E:\\d+ N:\\d+ L:\\d+/)")
  })
})
