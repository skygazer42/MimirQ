import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('KnowledgePage desktop scope collapse', () => {
  it('allows the embedded desktop scope rail to collapse while keeping the mobile scope dialog', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'knowledge-page.tsx'), 'utf8')

    expect(src).toContain("const [desktopScopeCollapsed, setDesktopScopeCollapsed] = useState(false)")
    expect(src).toContain("label={desktopScopeCollapsed ? t('actions.showScope') : t('actions.hideScope')}")
    expect(src).toContain('!desktopScopeCollapsed ? (')
    expect(src).toContain("title={t('dialogs.scope.title')}")
  })
})
