import { describe, expect, it } from 'vitest'

import { formatPreviewWarningMessage } from './preview-warnings'

describe('formatPreviewWarningMessage', () => {
  it('localizes semantic needs-review warnings from the backend', () => {
    const message = formatPreviewWarningMessage('14 chunks flagged needs_review (semantic heuristics)', {
      semanticNeedsReview: (count) => `需复核切块 ${count} 个`,
    })

    expect(message).toBe('需复核切块 14 个')
  })

  it('preserves unknown backend warnings', () => {
    const message = formatPreviewWarningMessage('parser warning: table fallback used', {
      semanticNeedsReview: (count) => `需复核切块 ${count} 个`,
    })

    expect(message).toBe('parser warning: table fallback used')
  })
})
