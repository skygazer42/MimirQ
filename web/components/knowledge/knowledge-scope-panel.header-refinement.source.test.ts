import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgeScopePanel header refinement', () => {
  it('uses a micro navigation header with a filter icon and a token divider instead of the older heavy title stack', () => {
    const src = fs.readFileSync(
      path.resolve(__dirname, 'knowledge-scope-panel.tsx'),
      'utf8'
    )

    expect(src).toMatch(
      /import\s*\{[^}]*ChevronDown[^}]*Filter[^}]*\}\s*from\s*'lucide-react'/
    )
    expect(src).toContain('text-[10px] font-medium uppercase tracking-[0.16em]')
    expect(src).toContain('mt-0.5 text-[13px] font-medium')
    expect(src).toContain('h-px w-full bg-border/70 dark:bg-border/70')
    expect(src).toContain("t('header.subtitle')")
    expect(src).toContain("t('header.title')")
  })
})
