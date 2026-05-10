import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('feedback loop API source', () => {
  it('exposes feedback loop candidate preview and hard-negative export on the domain client', () => {
    const apiSrc = fs.readFileSync(path.resolve(__dirname, 'api/feedback.ts'), 'utf8')
    const typeSrc = fs.readFileSync(path.resolve(__dirname, '../types/chat.ts'), 'utf8')

    expect(apiSrc).toContain('loopCandidates')
    expect(apiSrc).toContain('/feedback/loop/candidates')
    expect(apiSrc).toContain('exportHardNegatives')
    expect(apiSrc).toContain('/feedback/loop/hard-negatives/export')
    expect(typeSrc).toContain('export interface FeedbackLoopCandidatesResponse')
    expect(typeSrc).toContain('export interface FeedbackLoopHardNegativeExportResponse')
  })
})
