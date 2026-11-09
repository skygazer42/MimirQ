import { describe, expect, it } from 'vitest'

import { buildCleanPreviewRequestFromGovernanceProfile } from './governance-profile-utils'

describe('governance preview mapping', () => {
  it('retains rule order, omission defaults and explicit user choices', () => {
    const result = buildCleanPreviewRequestFromGovernanceProfile({
      version: '1', input_formats: ['html'],
      pipeline_patch: {
        governance_regex_rules: [{ pattern: 'first', repl: '', flags: 0 }],
        governance_remove_toc_lines: false, governance_max_blank_lines: 0, governance_pii_mask: '',
      },
      regex_rules: [{ pattern: '' }, { pattern: 'second', repl: 'replacement', flags: 2 }, { pattern: 'third' }],
    }, '<p>text</p>', { diffMaxLines: 0, useDefaultRules: false })

    expect(result.rules).toEqual([{ pattern: 'first', repl: '', flags: 0 }, { pattern: 'second', repl: 'replacement', flags: 2 }, { pattern: 'third', repl: '', flags: 0 }])
    expect(result).toMatchObject({ input_format: 'html', markdown: '<p>text</p>', max_blank_lines: 0, remove_toc_lines: false, pii_mask: '', diff_max_lines: 0, use_default_rules: false })
  })
})
