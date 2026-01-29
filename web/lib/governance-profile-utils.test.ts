import { describe, expect, it } from 'vitest'

import type { GovernanceProfilePayload } from '@/types'

import { buildCleanPreviewRequestFromGovernanceProfile } from './governance-profile-utils'

describe('buildCleanPreviewRequestFromGovernanceProfile', () => {
  it('maps governance pipeline_patch + regex_rules into clean-preview request', () => {
    const payload: GovernanceProfilePayload = {
      version: '1',
      input_formats: ['markdown'],
      pipeline_patch: {
        governance_max_blank_lines: 2,
        governance_unwrap_lines: false,
        governance_remove_boilerplate: true,
        governance_normalize_urls: true,
        governance_normalize_urls_strip_tracking: false,
      },
      regex_rules: [{ pattern: 'foo', repl: 'bar', flags: 0 }],
    }

    const req = buildCleanPreviewRequestFromGovernanceProfile(payload, 'foo', {
      includeDiff: true,
      inputFormat: 'markdown',
    })

    expect(req.markdown).toBe('foo')
    expect(req.rules).toEqual([{ pattern: 'foo', repl: 'bar', flags: 0 }])
    expect(req.max_blank_lines).toBe(2)
    expect(req.unwrap_lines).toBe(false)
    expect(req.remove_boilerplate).toBe(true)
    expect(req.normalize_urls).toBe(true)
    expect(req.normalize_urls_strip_tracking).toBe(false)
    expect(req.include_diff).toBe(true)
  })
})

