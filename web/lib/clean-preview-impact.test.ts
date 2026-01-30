import { describe, expect, it } from 'vitest'

import { computeCleanPreviewImpact } from './clean-preview-impact'

describe('computeCleanPreviewImpact', () => {
  it('computes deltas and sums pii/secrets hits', () => {
    const preview: any = {
      input_chars: 100,
      output_chars: 80,
      input_lines: 10,
      output_lines: 8,
      added_lines: 1,
      removed_lines: 3,
      changed_lines: 2,
      urls_changed: 4,
      paragraphs_dropped: 5,
      references_removed_lines: 6,
      pii_hits: { email: 2, phone: 1 },
      secrets_hits: { api_key: 3 },
    }

    const impact = computeCleanPreviewImpact(preview)
    expect(impact).toBeTruthy()
    expect(impact?.deltaChars).toBe(-20)
    expect(impact?.deltaCharsPct).toBeCloseTo(-0.2)
    expect(impact?.deltaLines).toBe(-2)
    expect(impact?.piiHitsTotal).toBe(3)
    expect(impact?.secretsHitsTotal).toBe(3)
  })
})

