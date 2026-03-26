import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage mobile queue dialog', () => {
  it('exposes the queue panel via WorkbenchPanelDialog on small screens', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-queue-content.tsx'))).toBe(true)

    expect(src).toContain('<WorkbenchPanelDialog')
    expect(src).toContain('open={queueOpen}')
    expect(src).toContain('onOpenChange={setQueueOpen}')
    expect(src).toContain('title="队列"')
    expect(src).toContain('ParsingMobileQueueContent')
  })
})
