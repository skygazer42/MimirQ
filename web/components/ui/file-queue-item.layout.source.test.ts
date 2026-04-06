import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('FileQueueItem layout', () => {
  it('keeps parsed status metadata on a single dense row with quieter active styling', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'file-queue-item.tsx'), 'utf8')

    expect(src).toContain("const parsedSummary = [file.parser, file.chunkStrategyLabel].filter(Boolean).join(' · ')")
    expect(src).toContain('ml-auto shrink-0 font-mono tabular-nums')
    expect(src).toContain('rounded-md border border-transparent px-2.5 py-2')
    expect(src).toContain("isActive\n          ? 'bg-primary/[0.055] shadow-none'")
  })
})
