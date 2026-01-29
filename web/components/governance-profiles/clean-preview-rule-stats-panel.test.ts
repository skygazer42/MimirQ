import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { CleanPreviewRuleStatsPanel } from '@/components/governance-profiles/clean-preview-rule-stats-panel'

describe('CleanPreviewRuleStatsPanel', () => {
  it('renders only rules with hits > 0', () => {
    const html = renderToStaticMarkup(
      createElement(CleanPreviewRuleStatsPanel, {
        ruleStats: [
          { index: 0, pattern: '(?m)^foo$', repl: '', flags: 0, hits: 0 },
          { index: 1, pattern: '(?m)^bar$', repl: '', flags: 0, hits: 3 },
        ],
      })
    )

    expect(html).toContain('规则命中')
    expect(html).toContain('(?m)^bar$')
    expect(html).toContain('3')
    expect(html).not.toContain('(?m)^foo$')
  })

  it('renders an empty state when no rules hit', () => {
    const html = renderToStaticMarkup(
      createElement(CleanPreviewRuleStatsPanel, {
        ruleStats: [{ index: 0, pattern: '(?m)^foo$', repl: '', flags: 0, hits: 0 }],
      })
    )

    expect(html).toContain('无命中')
  })
})

