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
    expect(src).toContain('text-[11px] font-medium leading-none text-muted-foreground/72')
    expect(src).toContain('mt-1 text-[13px] font-semibold leading-none')
    expect(src).toContain('h-px w-full bg-border/70 dark:bg-border/70')
    expect(src).toContain('筛选面板')
    expect(src).toContain('导航')
  })
})
