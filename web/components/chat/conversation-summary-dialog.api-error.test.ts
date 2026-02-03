import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('conversation summary dialog api error formatting', () => {
  it('uses formatApiError for backend failures (request_id included)', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'conversation-summary-dialog.tsx'), 'utf8')

    expect(src).toContain('formatApiError(')
    expect(src).not.toContain('err?.response?.data?.detail')
  })
})

